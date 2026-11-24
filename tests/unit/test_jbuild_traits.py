import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JBUILD_ROOT = PROJECT_ROOT / "journey-builder"
if str(JBUILD_ROOT) not in sys.path:
    sys.path.insert(0, str(JBUILD_ROOT))


from jbuild.core.trait_classifier import TraitClassifierRunner
from jbuild.core.traits import (
    TraitService,
    normalize_allowed_values,
    should_replace_trait_value,
    source_rank,
    validate_resolution_source,
    validate_trait_definition,
)
from jbuild.adapters.supabase import SupabaseTraitStore


def test_trait_definition_validation_normalizes_keys_and_values():
    trait_key, value_type, allowed_values, resolver_mode = validate_trait_definition(
        " Customer_Type ",
        "ENUM",
        "retail, wholesale, unknown, retail",
        "mixed",
    )

    assert trait_key == "customer_type"
    assert value_type == "enum"
    assert allowed_values == ["retail", "wholesale", "unknown"]
    assert resolver_mode == "mixed"


def test_trait_definition_validation_rejects_enum_without_values():
    try:
        validate_trait_definition("customer_type", "enum")
    except ValueError as exc:
        assert "enum traits require" in str(exc)
    else:
        raise AssertionError("Expected enum trait without values to fail")


def test_source_precedence_matches_contract():
    assert source_rank("manual") > source_rank("imported")
    assert source_rank("imported") > source_rank("rule")
    assert source_rank("rule") > source_rank("classifier")
    assert validate_resolution_source("classifier") == "classifier"

    assert should_replace_trait_value("classifier", "2026-01-01", "manual", "2026-01-01")
    assert not should_replace_trait_value("manual", "2026-01-01", "classifier", "2026-01-02")
    assert should_replace_trait_value("rule", "2026-01-01", "rule", "2026-01-02")


def test_normalize_allowed_values_accepts_lists_and_strings():
    assert normalize_allowed_values(["retail", "retail", " wholesale "]) == ["retail", "wholesale"]
    assert normalize_allowed_values("retail, wholesale, unknown") == ["retail", "wholesale", "unknown"]


class RecordingRpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class RecordingStore:
    def __init__(self):
        self.upserts = []

    def upsert_contact_trait_values(self, tenant_id, rows):
        self.upserts.append((tenant_id, rows))
        return RecordingRpc({"inserted": 1, "updated": 0, "ignored": 0})


class RecordingQuery:
    def __init__(self):
        self.filters = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class RecordingTableClient:
    def __init__(self):
        self.query = RecordingQuery()

    def table(self, name):
        assert name == "tenant_trait_classifier_configs"
        return self.query


def test_trait_value_writes_delegate_to_atomic_rpc():
    store = RecordingStore()
    service = TraitService(store=store)

    response = service.upsert_contact_trait_values(
        310131,
        [
            {
                "contact_id": "00000000-0000-0000-0000-000000000001",
                "trait_id": "00000000-0000-0000-0000-000000000002",
                "resolved_value": "retail",
                "resolution_source": "manual",
            }
        ],
    )

    assert response.data["inserted"] == 1
    assert store.upserts[0][0] == 310131
    assert store.upserts[0][1][0]["resolution_source"] == "manual"


def test_trait_classifier_draft_lookup_ignores_inactive_history():
    client = RecordingTableClient()
    store = SupabaseTraitStore(client=client)

    store.get_draft_trait_classifier_config(
        310131,
        "00000000-0000-0000-0000-000000000002",
    )

    assert ("eq", "is_active", False) in client.query.filters
    assert ("is", "activated_at", "null") in client.query.filters


def test_core_trait_service_has_no_supabase_storage_coupling():
    source = (JBUILD_ROOT / "jbuild" / "core" / "traits.py").read_text()

    assert "scripts.supabase_client" not in source
    assert "tenant_trait_definitions" not in source
    assert "tenant_trait_classifier_configs" not in source
    assert ".schema(\"silver\")" not in source


class FakeTraitService:
    def get_trait_definition(self, tenant_id, *, trait_id=None, trait_key=None):
        return {
            "trait_id": trait_id or "00000000-0000-0000-0000-000000000002",
            "trait_key": trait_key or "customer_type",
            "allowed_values": ["retail", "wholesale", "unknown"],
        }

    def get_trait_classifier_config(self, tenant_id, trait_id, config_id):
        return None

    def get_active_trait_classifier_config(self, tenant_id, trait_id):
        return {
            "config_id": "00000000-0000-0000-0000-000000000003",
            "version": 7,
            "master_prompt": "Classify customer type.",
            "allowed_values_snapshot": ["retail", "wholesale", "unknown"],
            "provider": "mock",
            "model": "mock-v1",
        }

    def get_contact_messages(self, tenant_id, contact_id):
        return [
            {"direction": "inbound", "text": "I own a store and need wholesale pricing."},
            {"direction": "outbound", "text": "We can help with that."},
        ]


class FakeProvider:
    def classify(self, text, prompt, labels):
        assert "customer_type" in prompt
        assert labels == ["retail", "wholesale", "unknown"]
        return SimpleNamespace(
            journey_stage="wholesale",
            confidence=0.91,
            raw_response={"reasoning": "Mentions owning a store."},
        )

    def build_classifier_version(self, config_version=1):
        return f"mock/mock-v1/v{config_version}"


def test_trait_classifier_adapter_does_not_expose_journey_stage():
    runner = TraitClassifierRunner(
        service=FakeTraitService(),
        provider_factory=lambda **_: FakeProvider(),
    )

    result = runner.classify_contact(
        310131,
        "00000000-0000-0000-0000-000000000001",
        trait_key="customer_type",
    )

    assert result.resolved_value == "wholesale"
    assert result.classifier_version == "mock/mock-v1/v7"
    assert result.reasoning == "Mentions owning a store."
    assert not hasattr(result, "journey_stage")
    row = result.to_trait_value_row()
    assert row["resolution_source"] == "classifier"
    assert row["resolved_value"] == "wholesale"
