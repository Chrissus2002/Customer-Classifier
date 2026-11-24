import os
from datetime import datetime, timedelta, timezone

from daemon_tasks.base import TaskResult
from database import (
    get_all_contacts_by_tenant,
    get_tenant_record,
    upsert_contact_identity_rows,
    upsert_contact_wati_key_rows,
)
from phone_identity import build_phone_identity


def build_contact_identity_refresh_plan(tenant_id: int):
    tenant, ok = get_tenant_record(tenant_id)
    if not ok:
        return str(tenant), False

    default_region = tenant.get("default_phone_region")
    contacts = get_all_contacts_by_tenant(tenant_id)
    active_contacts = [contact for contact in contacts if contact.get("is_canonical", True)]

    updates = []
    wati_key_rows = []
    identity_group_sizes: dict[str, int] = {}
    covered_active = 0
    wati_fallback_count = 0
    raw_fallback_count = 0
    now = datetime.now(timezone.utc).isoformat()

    for contact in contacts:
        desired_raw_primary = (
            contact.get("phone_raw_primary")
            or contact.get("phone_raw")
            or contact.get("wati_lookup_phone")
            or contact.get("phone_normalized")
        )
        desired_identity = build_phone_identity(
            raw_input=str(desired_raw_primary) if desired_raw_primary is not None else None,
            default_region=default_region,
            wati_contact_id=str(contact["wati_contact_id"]) if contact.get("wati_contact_id") is not None else None,
        )
        desired_lookup_phone = desired_identity.wati_lookup_phone
        is_active = contact.get("is_canonical", True)

        if is_active and desired_identity.phone_identity_key and desired_lookup_phone:
            covered_active += 1

        if is_active and desired_identity.phone_identity_key:
            identity_group_sizes[desired_identity.phone_identity_key] = (
                identity_group_sizes.get(desired_identity.phone_identity_key, 0) + 1
            )

        if is_active and desired_identity.normalization_status == "wati_fallback":
            wati_fallback_count += 1
        if is_active and desired_identity.normalization_status == "raw_fallback":
            raw_fallback_count += 1

        needs_update = any(
            [
                contact.get("phone_identity_key") != desired_identity.phone_identity_key,
                contact.get("phone_e164") != desired_identity.phone_e164,
                contact.get("normalization_status") != desired_identity.normalization_status,
                contact.get("normalization_region") != desired_identity.normalization_region,
                contact.get("phone_raw_primary") != desired_raw_primary,
                contact.get("wati_lookup_phone") != desired_lookup_phone,
            ]
        )

        if needs_update:
            updates.append(
                {
                    "contact_id": contact["contact_id"],
                    "tenant_id": contact["tenant_id"],
                    "phone_normalized": contact["phone_normalized"],
                    "phone_identity_key": desired_identity.phone_identity_key,
                    "phone_e164": desired_identity.phone_e164,
                    "normalization_status": desired_identity.normalization_status,
                    "normalization_region": desired_identity.normalization_region,
                    "phone_raw_primary": desired_raw_primary,
                    "wati_lookup_phone": desired_lookup_phone,
                }
            )

        if contact.get("wati_contact_id"):
            wati_key_rows.append(
                {
                    "tenant_id": contact["tenant_id"],
                    "contact_id": contact["contact_id"],
                    "wati_contact_id": contact["wati_contact_id"],
                    "wati_lookup_phone": desired_lookup_phone,
                    "is_primary": True,
                    "last_seen_at": now,
                }
            )

    active_count = len(active_contacts)
    merge_groups = [size for size in identity_group_sizes.values() if size > 1]
    keep_same_identity_count = sum(size for size in identity_group_sizes.values() if size == 1)
    would_merge_count = sum(merge_groups)
    coverage_pct = round((covered_active / active_count) * 100, 2) if active_count else 100.0

    plan = {
        "default_region": default_region,
        "contacts": contacts,
        "updates": updates,
        "wati_key_rows": wati_key_rows,
        "report": {
            "active_contacts": active_count,
            "keep_same_identity_count": keep_same_identity_count,
            "would_merge_count": would_merge_count,
            "wati_fallback_count": wati_fallback_count,
            "raw_fallback_count": raw_fallback_count,
            "covered_active_contacts": covered_active,
            "shadow_coverage_pct": coverage_pct,
            "distinct_identity_keys": len(identity_group_sizes),
            "updated_contacts": len(updates),
            "wati_key_rows": len(wati_key_rows),
        },
    }
    return plan, True


class ContactIdentityRefreshTask:
    name = "contact_identity_refresh"
    interval = timedelta(minutes=int(os.getenv("DIALO_CONTACT_IDENTITY_REFRESH_INTERVAL_MINUTES", "30")))
    error_retry_interval = timedelta(minutes=int(os.getenv("DIALO_CONTACT_IDENTITY_REFRESH_RETRY_MINUTES", "15")))

    def __init__(self, coverage_threshold: float | None = None):
        default_threshold = float(os.getenv("DIALO_CONTACT_IDENTITY_COVERAGE_THRESHOLD", "99.9"))
        self.coverage_threshold = coverage_threshold if coverage_threshold is not None else default_threshold

    def run(self, tenant_id: int) -> TaskResult:
        plan, ok = build_contact_identity_refresh_plan(tenant_id)
        if not ok:
            return TaskResult.error(str(plan))

        update_result, updated = upsert_contact_identity_rows(plan["updates"])
        if not updated:
            return TaskResult.error(str(update_result), result=plan["report"])

        key_result, keyed = upsert_contact_wati_key_rows(plan["wati_key_rows"])
        if not keyed:
            return TaskResult.error(str(key_result), result=plan["report"])

        result = dict(plan["report"])
        result["updated_contacts"] = int(update_result)
        result["wati_key_rows"] = int(key_result)

        notes = None
        if result["shadow_coverage_pct"] < self.coverage_threshold:
            notes = (
                f"Shadow identity coverage {result['shadow_coverage_pct']:.2f}% "
                f"is below threshold {self.coverage_threshold:.2f}%"
            )

        return TaskResult.success(result=result, notes=notes)
