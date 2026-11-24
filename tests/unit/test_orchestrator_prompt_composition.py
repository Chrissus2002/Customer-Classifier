"""Unit tests for orchestrator prompt composition and version-drift detection."""

import pytest
from unittest.mock import MagicMock, patch

from scripts.classifiers.orchestrator import JourneyClassifier, _compose_prompt
from scripts.classifiers.models import ClassificationResult


# ── _compose_prompt ──────────────────────────────────────────────────

SAMPLE_STAGES = [
    {"stage_name": "browsing", "stage_description": "Exploring catalog"},
    {"stage_name": "purchase_intent", "stage_description": "Ready to buy"},
]


class TestComposePrompt:
    def test_contains_master_prompt_twice(self):
        composed = _compose_prompt("MY PROMPT", SAMPLE_STAGES)
        assert composed.count("MY PROMPT") == 2

    def test_contains_stage_names(self):
        composed = _compose_prompt("PROMPT", SAMPLE_STAGES)
        assert "browsing" in composed
        assert "purchase_intent" in composed

    def test_contains_stage_descriptions(self):
        composed = _compose_prompt("PROMPT", SAMPLE_STAGES)
        assert "Exploring catalog" in composed
        assert "Ready to buy" in composed

    def test_contains_valid_labels_line(self):
        composed = _compose_prompt("PROMPT", SAMPLE_STAGES)
        assert "browsing, purchase_intent" in composed or "browsing,purchase_intent" in composed.replace(" ", "")

    def test_empty_stages(self):
        composed = _compose_prompt("PROMPT", [])
        assert "PROMPT" in composed
        assert "Valid labels:" in composed

    def test_separator_present(self):
        composed = _compose_prompt("PROMPT", SAMPLE_STAGES)
        assert "—" in composed


# ── JourneyClassifier.get_tenant_config ──────────────────────────────


def make_mock_classifier():
    mock = MagicMock()
    mock.build_classifier_version.side_effect = lambda v: f"mock/mock/v{v}"
    mock.classify.return_value = ClassificationResult(
        journey_stage="browsing",
        confidence=0.9,
        classifier_version="mock/mock/v1",
        raw_response={"reasoning": "test"},
    )
    return mock


def make_orchestrator_with_db(config_data, stages_data):
    """Build a JourneyClassifier with a mocked Supabase client."""
    with patch("scripts.classifiers.orchestrator.get_supabase_client") as mock_client_fn:
        client = MagicMock()
        mock_client_fn.return_value = client

        # tenant_classifier_configs query
        config_chain = MagicMock()
        config_chain.execute.return_value = MagicMock(data=config_data)
        client.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value = config_chain

        # tenant_journey_stages query
        stages_chain = MagicMock()
        stages_chain.execute.return_value = MagicMock(data=stages_data)
        # The second table() call for stages returns stages_chain via order()
        # We need to set up table().select().eq().order() → stages_chain
        # Use side_effect on table to return different objects for different calls

        call_count = [0]
        original_table = client.table

        def table_side_effect(name):
            call_count[0] += 1
            tbl = MagicMock()
            if name == "tenant_classifier_configs":
                tbl.select.return_value.eq.return_value.eq.return_value.limit.return_value = config_chain
            elif name == "tenant_journey_stages":
                tbl.select.return_value.eq.return_value.order.return_value = stages_chain
            return tbl

        client.table.side_effect = table_side_effect
        orch = JourneyClassifier(classifier=make_mock_classifier())
        orch.client = client
        return orch, client, config_chain, stages_chain


class TestGetTenantConfig:
    def test_returns_prompt_stages_version(self):
        config_data = [{"config_id": "cfg-1", "version": 2, "master_prompt": "MASTER"}]
        stages_data = [
            {"stage_name": "browsing", "stage_description": "desc1", "display_order": 1},
            {"stage_name": "order_support", "stage_description": "desc2", "display_order": 2},
        ]
        orch, client, _, _ = make_orchestrator_with_db(config_data, stages_data)

        prompt, stages, version = orch.get_tenant_config(YOUR_TENANT_ID)
        assert prompt == "MASTER"
        assert version == 2
        assert len(stages) == 2
        assert stages[0]["stage_name"] == "browsing"

    def test_fallback_when_no_config(self):
        orch, client, _, _ = make_orchestrator_with_db([], [])
        prompt, stages, version = orch.get_tenant_config(YOUR_TENANT_ID)
        assert prompt == ""
        assert version == 1
        assert len(stages) == 8  # fallback list


# ── Version drift detection ──────────────────────────────────────────

class TestVersionDriftInGetUnclassifiedContacts:
    """
    Integration-ish: mock the DB and verify version-drift contacts surface.
    """

    def _make_orch(self):
        with patch("scripts.classifiers.orchestrator.get_supabase_client") as mcf:
            client = MagicMock()
            mcf.return_value = client
            orch = JourneyClassifier(classifier=make_mock_classifier())
            orch.client = client
            return orch, client

    def test_version_drift_contacts_included(self):
        orch, client = self._make_orch()

        # unique_contact_ids returns 2 contacts
        contacts_page = MagicMock()
        contacts_page.data = [
            {"contact_id": "aaa"},
            {"contact_id": "bbb"},
        ]
        (client.schema.return_value.table.return_value
         .select.return_value.eq.return_value.gte.return_value
         .range.return_value.execute.return_value) = contacts_page

        # active version = 3
        ver_resp = MagicMock()
        ver_resp.data = [{"version": 3}]
        (client.table.return_value.select.return_value
         .eq.return_value.eq.return_value.limit.return_value
         .execute.return_value) = ver_resp

        # journey_intent_results: aaa classified with v1 (drift), bbb with v3 (current)
        classified_resp = MagicMock()
        classified_resp.data = [
            {"contact_id": "aaa", "last_inbound_message_at": "2026-01-01T10:00:00", "classifier_version": "mock/mock/v1"},
            {"contact_id": "bbb", "last_inbound_message_at": "2026-01-01T10:00:00", "classifier_version": "mock/mock/v3"},
        ]
        (client.schema.return_value.table.return_value
         .select.return_value.eq.return_value.order.return_value
         .execute.return_value) = classified_resp

        # No stale inbound (all messages match stored timestamps)
        msgs_resp = MagicMock()
        msgs_resp.data = [
            {"contact_id": "aaa", "timestamp": "2026-01-01T10:00:00"},
            {"contact_id": "bbb", "timestamp": "2026-01-01T10:00:00"},
        ]
        (client.schema.return_value.table.return_value
         .select.return_value.eq.return_value.eq.return_value
         .gte.return_value.in_.return_value.order.return_value
         .execute.return_value) = msgs_resp

        candidates, stale = orch.get_unclassified_contacts(YOUR_TENANT_ID, limit=100)
        candidate_ids = {c["contact_id"] for c in candidates}
        assert "aaa" in candidate_ids, "version-drifted contact must be a candidate"
        assert "bbb" not in candidate_ids, "current-version contact must not appear"

    def test_no_drift_when_versions_match(self):
        orch, client = self._make_orch()

        contacts_page = MagicMock()
        contacts_page.data = [{"contact_id": "ccc"}]
        (client.schema.return_value.table.return_value
         .select.return_value.eq.return_value.gte.return_value
         .range.return_value.execute.return_value) = contacts_page

        ver_resp = MagicMock()
        ver_resp.data = [{"version": 2}]
        (client.table.return_value.select.return_value
         .eq.return_value.eq.return_value.limit.return_value
         .execute.return_value) = ver_resp

        classified_resp = MagicMock()
        classified_resp.data = [
            {"contact_id": "ccc", "last_inbound_message_at": "2026-01-01T10:00:00", "classifier_version": "mock/mock/v2"},
        ]
        (client.schema.return_value.table.return_value
         .select.return_value.eq.return_value.order.return_value
         .execute.return_value) = classified_resp

        msgs_resp = MagicMock()
        msgs_resp.data = [{"contact_id": "ccc", "timestamp": "2026-01-01T10:00:00"}]
        (client.schema.return_value.table.return_value
         .select.return_value.eq.return_value.eq.return_value
         .gte.return_value.in_.return_value.order.return_value
         .execute.return_value) = msgs_resp

        candidates, _ = orch.get_unclassified_contacts(YOUR_TENANT_ID, limit=100)
        assert all(c["contact_id"] != "ccc" for c in candidates), "up-to-date contact must not be a candidate"


# ── classify_contact uses tenant_config param ──────────────────────

class TestClassifyContactTenantConfigParam:
    def test_uses_provided_tenant_config(self):
        """classify_contact should not call get_tenant_config when tenant_config is provided."""
        with patch("scripts.classifiers.orchestrator.get_supabase_client") as mcf:
            client = MagicMock()
            mcf.return_value = client

            mock_provider = make_mock_classifier()
            orch = JourneyClassifier(classifier=mock_provider)
            orch.client = client

            # Messages response
            msgs_resp = MagicMock()
            msgs_resp.data = [{"text": "Hola", "direction": "inbound", "timestamp": "t1"}]
            (client.schema.return_value.table.return_value
             .select.return_value.eq.return_value.order.return_value
             .execute.return_value) = msgs_resp

            tenant_config = ("MY PROMPT", SAMPLE_STAGES, 2)
            # Spy on get_tenant_config
            original_get = orch.get_tenant_config
            call_log = []
            orch.get_tenant_config = lambda tid: call_log.append(tid) or original_get(tid)

            orch.classify_contact(YOUR_TENANT_ID, "some-contact-id", tenant_config=tenant_config)
            assert call_log == [], "get_tenant_config must not be called when tenant_config is provided"
            mock_provider.classify.assert_called_once()
