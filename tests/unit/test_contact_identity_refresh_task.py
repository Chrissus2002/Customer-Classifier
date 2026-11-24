from daemon_tasks.contact_identity_refresh import (
    ContactIdentityRefreshTask,
    build_contact_identity_refresh_plan,
)


def test_build_contact_identity_refresh_plan_reports_merges_and_fallbacks(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.get_tenant_record",
        lambda tenant_id: ({"wati_api_token": "token", "default_phone_region": "GB"}, True),
    )
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-1",
                "tenant_id": tenant_id,
                "phone_normalized": "442079460056",
                "phone_raw": "+44 20 7946 0056",
                "wati_contact_id": "wati-1",
                "is_canonical": True,
            },
            {
                "contact_id": "contact-2",
                "tenant_id": tenant_id,
                "phone_normalized": "02079460056",
                "phone_raw": "020 7946 0056",
                "wati_contact_id": "wati-2",
                "is_canonical": True,
            },
            {
                "contact_id": "contact-3",
                "tenant_id": tenant_id,
                "phone_normalized": "000111",
                "phone_raw": "000111",
                "wati_contact_id": None,
                "is_canonical": True,
            },
        ],
    )

    plan, ok = build_contact_identity_refresh_plan(310131)

    assert ok is True
    assert plan["report"]["active_contacts"] == 3
    assert plan["report"]["would_merge_count"] == 2
    assert plan["report"]["keep_same_identity_count"] == 1
    assert plan["report"]["raw_fallback_count"] == 1
    assert plan["report"]["covered_active_contacts"] == 3
    assert plan["report"]["shadow_coverage_pct"] == 100.0
    assert len(plan["updates"]) == 3
    assert len(plan["wati_key_rows"]) == 2


def test_contact_identity_refresh_task_persists_rows(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.build_contact_identity_refresh_plan",
        lambda tenant_id: (
            {
                "updates": [{"contact_id": "c1", "tenant_id": tenant_id, "phone_normalized": "14155550100"}],
                "wati_key_rows": [{"tenant_id": tenant_id, "contact_id": "c1", "wati_contact_id": "wati-1"}],
                "report": {
                    "active_contacts": 1,
                    "keep_same_identity_count": 1,
                    "would_merge_count": 0,
                    "wati_fallback_count": 0,
                    "raw_fallback_count": 0,
                    "covered_active_contacts": 1,
                    "shadow_coverage_pct": 100.0,
                    "distinct_identity_keys": 1,
                    "updated_contacts": 1,
                    "wati_key_rows": 1,
                },
            },
            True,
        ),
    )
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.upsert_contact_identity_rows",
        lambda rows: (len(rows), True),
    )
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.upsert_contact_wati_key_rows",
        lambda rows: (len(rows), True),
    )

    result = ContactIdentityRefreshTask().run(310131)

    assert result.status == "success"
    assert result.result["updated_contacts"] == 1
    assert result.result["wati_key_rows"] == 1
    assert result.notes is None


def test_build_contact_identity_refresh_plan_upgrades_stale_legacy_lookup_phone(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.get_tenant_record",
        lambda tenant_id: ({"wati_api_token": "token", "default_phone_region": "US"}, True),
    )
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-1",
                "tenant_id": tenant_id,
                "phone_normalized": "4155550100",
                "phone_raw": "4155550100",
                "wati_lookup_phone": "4155550100",
                "wati_contact_id": "wati-1",
                "is_canonical": True,
            },
        ],
    )

    plan, ok = build_contact_identity_refresh_plan(310131)

    assert ok is True
    assert plan["report"]["covered_active_contacts"] == 1
    assert plan["report"]["shadow_coverage_pct"] == 100.0
    assert plan["updates"][0]["phone_identity_key"] == "e164:+14155550100"
    assert plan["updates"][0]["wati_lookup_phone"] == "14155550100"
    assert plan["wati_key_rows"][0]["wati_lookup_phone"] == "14155550100"


def test_contact_identity_refresh_task_returns_error_on_upsert_failure(monkeypatch):
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.build_contact_identity_refresh_plan",
        lambda tenant_id: (
            {
                "updates": [{"contact_id": "c1", "tenant_id": tenant_id, "phone_normalized": "14155550100"}],
                "wati_key_rows": [],
                "report": {"shadow_coverage_pct": 0.0},
            },
            True,
        ),
    )
    monkeypatch.setattr(
        "daemon_tasks.contact_identity_refresh.upsert_contact_identity_rows",
        lambda rows: ("write failed", False),
    )

    result = ContactIdentityRefreshTask().run(310131)

    assert result.status == "error"
    assert result.error_message == "write failed"
