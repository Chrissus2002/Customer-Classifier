import os
from datetime import timedelta

from daemon_tasks.base import TaskResult
from database import (
    get_all_contacts_by_tenant,
    get_tenant_credentials,
)
from phone_identity import build_phone_identity, count_distinct_identity_keys, identity_from_contact_record
from wati_client import WatiAPIClient


def _identity_key_set(identities) -> set[str]:
    return {
        identity.phone_identity_key
        for identity in identities
        if identity.phone_identity_key
    }


class ExactContactDriftTask:
    name = "exact_contact_drift"
    interval = timedelta(hours=int(os.getenv("DIALO_EXACT_DRIFT_INTERVAL_HOURS", "4")))
    error_retry_interval = timedelta(minutes=int(os.getenv("DIALO_EXACT_DRIFT_RETRY_MINUTES", "15")))

    def __init__(self, threshold: int | None = None):
        default_threshold = int(os.getenv("DIALO_CONTACT_DRIFT_THRESHOLD", "50"))
        self.threshold = threshold if threshold is not None else default_threshold

    def run(self, tenant_id: int) -> TaskResult:
        tenant, ok = get_tenant_credentials(tenant_id)
        if not ok:
            return TaskResult.error(str(tenant))
        default_region = tenant.get("default_phone_region")

        wati = WatiAPIClient(str(tenant_id), tenant["wati_api_token"])

        wati_raw_contact_count = wati.get_contact_count()
        if wati_raw_contact_count is None:
            return TaskResult.error("Could not reach Wati API for raw contact count")

        contacts = wati.get_contacts()
        if contacts is None:
            return TaskResult.error("Could not fetch Wati contacts for exact drift check")

        wati_identities = [
            build_phone_identity(
                raw_input=contact.get("phone"),
                default_region=default_region,
                wati_contact_id=contact.get("id"),
            )
            for contact in contacts
        ]
        wati_identity_keys = _identity_key_set(wati_identities)
        wati_distinct_contact_count = count_distinct_identity_keys(wati_identities)

        db_contacts = get_all_contacts_by_tenant(tenant_id)
        active_contacts = [contact for contact in db_contacts if contact.get("is_canonical", True)]
        db_identities = [identity_from_contact_record(contact, default_region=default_region) for contact in active_contacts]
        db_identity_keys = _identity_key_set(db_identities)
        db_contact_count = count_distinct_identity_keys(db_identities)
        active_contact_count = len(active_contacts)
        shadow_covered_count = sum(
            1
            for contact in active_contacts
            if contact.get("phone_identity_key")
            and contact.get("wati_lookup_phone")
        )

        wati_only_keys = sorted(wati_identity_keys - db_identity_keys)
        db_only_keys = sorted(db_identity_keys - wati_identity_keys)
        exact_match = not wati_only_keys and not db_only_keys
        mismatch_count = len(wati_only_keys) + len(db_only_keys)
        contact_drift = wati_distinct_contact_count - db_contact_count
        threshold_exceeded = mismatch_count > self.threshold
        shadow_coverage_pct = round((shadow_covered_count / active_contact_count) * 100, 2) if active_contact_count else 100.0

        result = {
            "wati_raw_contact_count": wati_raw_contact_count,
            "wati_distinct_contact_count": wati_distinct_contact_count,
            "db_contact_count": db_contact_count,
            "contact_drift": contact_drift,
            "exact_match": exact_match,
            "wati_only_count": len(wati_only_keys),
            "db_only_count": len(db_only_keys),
            "mismatch_count": mismatch_count,
            "wati_only_keys_sample": wati_only_keys[:10],
            "db_only_keys_sample": db_only_keys[:10],
            "threshold": self.threshold,
            "threshold_exceeded": threshold_exceeded,
            "active_contact_count": active_contact_count,
            "shadow_covered_count": shadow_covered_count,
            "shadow_coverage_pct": shadow_coverage_pct,
            "normalization_strategy": "scripts.phone_identity.build_phone_identity",
        }

        notes = None
        if not exact_match:
            notes = (
                f"Exact identity mismatch: {len(wati_only_keys)} on Wati only, "
                f"{len(db_only_keys)} in DB only"
            )
            if threshold_exceeded:
                notes += f" (total mismatches {mismatch_count} exceeded threshold {self.threshold})"

        return TaskResult.success(result=result, notes=notes)
