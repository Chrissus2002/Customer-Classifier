from daemon_tasks.exact_contact_drift import ExactContactDriftTask


class DummyWatiClient:
    def __init__(self, tenant_id, token):
        self.tenant_id = tenant_id
        self.token = token

    def get_contact_count(self):
        return 9443

    def get_contacts(self):
        return [
            {"id": "mx-a", "phone": "5218123456789"},
            {"id": "mx-b", "phone": "528123456789"},
            {"id": "us-a", "phone": "14155550100"},
        ]


def test_exact_contact_drift_success_payload(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_tenant_credentials",
        lambda tenant_id: ({"wati_api_token": "token", "default_phone_region": "MX"}, True),
    )
    monkeypatch.setattr("daemon_tasks.exact_contact_drift.WatiAPIClient", DummyWatiClient)
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-mx",
                "tenant_id": tenant_id,
                "phone_normalized": "5218123456789",
                "phone_raw": "5218123456789",
                "phone_identity_key": "e164:+528123456789",
                "wati_lookup_phone": "5218123456789",
                "is_canonical": True,
            },
            {
                "contact_id": "contact-us",
                "tenant_id": tenant_id,
                "phone_normalized": "14155550100",
                "phone_raw": "14155550100",
                "phone_identity_key": None,
                "wati_contact_id": "us-a",
                "wati_lookup_phone": "14155550100",
                "is_canonical": True,
            },
        ],
    )

    task = ExactContactDriftTask(threshold=50)
    result = task.run(310131)

    assert result.status == "success"
    assert result.result["wati_raw_contact_count"] == 9443
    assert result.result["wati_distinct_contact_count"] == 2
    assert result.result["db_contact_count"] == 2
    assert result.result["contact_drift"] == 0
    assert result.result["exact_match"] is True
    assert result.result["wati_only_count"] == 0
    assert result.result["db_only_count"] == 0
    assert result.result["mismatch_count"] == 0
    assert result.result["active_contact_count"] == 2
    assert result.result["shadow_covered_count"] == 1
    assert result.result["shadow_coverage_pct"] == 50.0
    assert result.result["threshold_exceeded"] is False
    assert result.result["normalization_strategy"] == "scripts.phone_identity.build_phone_identity"
    assert result.notes is None


def test_exact_contact_drift_sets_threshold_note(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_tenant_credentials",
        lambda tenant_id: ({"wati_api_token": "token", "default_phone_region": None}, True),
    )
    monkeypatch.setattr("daemon_tasks.exact_contact_drift.WatiAPIClient", DummyWatiClient)
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-mx",
                "tenant_id": tenant_id,
                "phone_normalized": "5218123456789",
                "phone_raw": "5218123456789",
                "phone_identity_key": "e164:+528123456789",
                "wati_lookup_phone": "5218123456789",
                "is_canonical": True,
            },
        ],
    )

    task = ExactContactDriftTask(threshold=0)
    result = task.run(310131)

    assert result.status == "success"
    assert result.result["exact_match"] is False
    assert result.result["wati_only_count"] == 1
    assert result.result["db_only_count"] == 0
    assert result.result["mismatch_count"] == 1
    assert result.result["threshold_exceeded"] is True
    assert "Exact identity mismatch" in result.notes
    assert "exceeded threshold" in result.notes


def test_exact_contact_drift_flags_one_to_one_mismatch_even_when_counts_match(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_tenant_credentials",
        lambda tenant_id: ({"wati_api_token": "token", "default_phone_region": None}, True),
    )
    monkeypatch.setattr("daemon_tasks.exact_contact_drift.WatiAPIClient", DummyWatiClient)
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-mx",
                "tenant_id": tenant_id,
                "phone_normalized": "5218123456789",
                "phone_raw": "5218123456789",
                "phone_identity_key": "e164:+528123456789",
                "wati_lookup_phone": "5218123456789",
                "is_canonical": True,
            },
            {
                "contact_id": "contact-other",
                "tenant_id": tenant_id,
                "phone_normalized": "16175550123",
                "phone_raw": "16175550123",
                "phone_identity_key": "e164:+16175550123",
                "wati_lookup_phone": "16175550123",
                "is_canonical": True,
            },
        ],
    )

    task = ExactContactDriftTask(threshold=10)
    result = task.run(310131)

    assert result.status == "success"
    assert result.result["wati_distinct_contact_count"] == 2
    assert result.result["db_contact_count"] == 2
    assert result.result["contact_drift"] == 0
    assert result.result["exact_match"] is False
    assert result.result["wati_only_count"] == 1
    assert result.result["db_only_count"] == 1
    assert result.result["mismatch_count"] == 2
    assert result.result["threshold_exceeded"] is False
    assert result.notes == "Exact identity mismatch: 1 on Wati only, 1 in DB only"


def test_exact_contact_drift_returns_error_on_count_failure(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.exact_contact_drift.get_tenant_credentials",
        lambda tenant_id: ("tenant missing", False),
    )

    task = ExactContactDriftTask()
    result = task.run(310131)

    assert result.status == "error"
    assert result.error_message == "tenant missing"
