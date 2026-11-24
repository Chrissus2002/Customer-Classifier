from typing import Optional
from datetime import datetime, timezone

from .base import BaseClassifier
from .models import ClassificationResult
from supabase_client import get_supabase_client

# Fallback config used only when a tenant has no rows in tenant_classifier_configs
_FALLBACK_STAGES = [
    "browsing", "product_evaluation", "purchase_intent", "order_support",
    "wholesale_inquiry", "location_inquiry", "no_customer_activity", "spam_unrelated",
]
_FALLBACK_VERSION = 1


def _compose_prompt(master_prompt: str, stages: list[dict]) -> str:
    """
    Compose the final prompt sent to the LLM.

    Pattern:
        {master_prompt}

        — separator —

        {master_prompt}

        ETAPAS VÁLIDAS:
        • stage_name: stage_description
        ...

        Valid labels: stage_name, ...
    """
    stages_section = "\n".join(
        f"• {s['stage_name']}: {s['stage_description']}" for s in stages
    )
    label_list = ", ".join(s["stage_name"] for s in stages)
    separator = "— " * 33
    return (
        f"{master_prompt}\n\n"
        f"{separator}\n"
        f"Voy a repetir las instrucciones para asegurarme de que las sigas:\n"
        f"{separator}\n\n"
        f"{master_prompt}\n\n"
        f"ETAPAS VÁLIDAS:\n{stages_section}\n\n"
        f"Valid labels: {label_list}"
    )


class JourneyClassifier:
    """
    Orchestrates per-contact classification:
    1. Loads tenant classifier config once (prompt + stages + version)
    2. Composes the prompt from master_prompt + stage descriptions
    3. Fetches conversation messages per contact
    4. Calls the LLM classifier
    5. Stores the result in silver.journey_intent_results
    """

    def __init__(self, classifier: BaseClassifier):
        self.classifier = classifier
        self.client = get_supabase_client()

    def get_contact_messages(self, contact_id: str, limit: int = 50) -> list[dict]:
        """Fetch conversation history for a contact, ordered by timestamp."""
        response = (
            self.client.schema("silver").table("messages")
            .select("text, direction, timestamp")
            .eq("contact_id", contact_id)
            .order("timestamp", desc=False)
            .limit(limit)
            .execute()
        )
        return response.data or []

    def get_tenant_config(self, tenant_id: int) -> tuple[str, list[dict], int]:
        """
        Load the active classifier config for a tenant.

        Returns:
            (master_prompt, stages, version)
            stages = [{"stage_name": ..., "stage_description": ..., "display_order": ...}, ...]
        """
        config_resp = (
            self.client.table("tenant_classifier_configs")
            .select("config_id, version, master_prompt")
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not config_resp.data:
            # No config in DB — return fallback so the worker doesn't crash
            fallback_stages = [
                {"stage_name": s, "stage_description": "", "display_order": i + 1}
                for i, s in enumerate(_FALLBACK_STAGES)
            ]
            return "", fallback_stages, _FALLBACK_VERSION

        config = config_resp.data[0]
        config_id = config["config_id"]
        version = config["version"]
        master_prompt = config["master_prompt"]

        stages_resp = (
            self.client.table("tenant_journey_stages")
            .select("stage_name, stage_description, display_order")
            .eq("config_id", config_id)
            .order("display_order")
            .execute()
        )
        stages = stages_resp.data or []
        return master_prompt, stages, version

    def format_conversation(self, messages: list[dict]) -> str:
        """Format messages into a readable conversation string for the LLM."""
        lines = []
        for msg in messages:
            direction = "Customer" if msg.get("direction") == "inbound" else "Business"
            text = msg.get("text") or "[non-text message]"
            lines.append(f"{direction}: {text}")
        return "\n".join(lines)

    def classify_contact(
        self,
        tenant_id: int,
        contact_id: str,
        tenant_config: Optional[tuple] = None,
        prompt: Optional[str] = None,
    ) -> ClassificationResult:
        """
        Classify a single contact based on their conversation history.

        Args:
            tenant_id: Tenant owning the contact.
            contact_id: UUID of the contact.
            tenant_config: Optional pre-loaded (master_prompt, stages, version) tuple.
                           If None, loads from DB (incurs a DB round trip per contact).
            prompt: Optional fully-composed prompt override. Bypasses composition.

        Returns:
            ClassificationResult.
        """
        if tenant_config is None:
            tenant_config = self.get_tenant_config(tenant_id)
        master_prompt, stages, version = tenant_config

        messages = self.get_contact_messages(contact_id)
        stage_names = [s["stage_name"] for s in stages] if stages else _FALLBACK_STAGES

        if not messages:
            return ClassificationResult(
                journey_stage=stage_names[0],
                confidence=0.0,
                classifier_version=self.classifier.build_classifier_version(version),
                raw_response={"reasoning": "no_messages"},
            )

        messages = [msg for msg in messages if msg.get("direction") != "system"]

        conversation_text = self.format_conversation(messages)
        if prompt:
            classification_prompt = prompt
        elif master_prompt and stages:
            classification_prompt = _compose_prompt(master_prompt, stages)
        else:
            # Fallback: no config in DB, use bare stage names (degraded mode)
            classification_prompt = "Classify the conversation into one of the valid labels."

        result = self.classifier.classify(
            text=conversation_text,
            prompt=classification_prompt,
            labels=stage_names,
        )
        result.classifier_version = self.classifier.build_classifier_version(version)
        return result

    def classify_and_store(
        self,
        tenant_id: int,
        contact_id: str,
        tenant_config: Optional[tuple] = None,
        prompt: Optional[str] = None,
    ) -> ClassificationResult:
        """Classify a contact and write the result to the database."""
        result = self.classify_contact(tenant_id, contact_id, tenant_config, prompt)

        latest_msg = (
            self.client.schema("silver").table("messages")
            .select("timestamp")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .eq("direction", "inbound")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        last_inbound_message_at = latest_msg.data[0]["timestamp"] if latest_msg.data else None
        classification_record = {
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "journey_stage": result.journey_stage,
            "confidence": result.confidence,
            "classifier_version": result.classifier_version,
            "classified_at": datetime.now(timezone.utc).isoformat(),
            "last_inbound_message_at": last_inbound_message_at,
            "reasoning": result.raw_response.get("reasoning"),
        }

        resp = (self.client.schema("silver").table("journey_intent_results")
         .upsert(classification_record, on_conflict="tenant_id, contact_id")
         .execute())

        if not resp.data:
            raise RuntimeError(
                f"Failed to persist classification for contact {contact_id} "
                f"(upsert returned no data)"
            )

        return result

    def get_unclassified_contacts(
        self, tenant_id: int, limit: int = 100, since_date: Optional[str] = "2026-01-01"
    ) -> tuple[list[dict], set[str]]:
        """
        Find contacts that need classification:
        1. Never classified (no row in journey_intent_results)
        2. Stale — a new inbound message arrived after last_inbound_message_at
        3. Version-drift — contact was classified with an older config version than the active one
        """
        all_contacts = []
        page_size = 1000
        offset = 0
        while True:
            contacts_resp = (
                self.client.schema("silver").table("unique_contact_ids")
                .select("contact_id")
                .eq("tenant_id", tenant_id)
                .gte("timestamp", since_date)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            if not contacts_resp.data:
                break
            all_contacts.extend([c["contact_id"] for c in contacts_resp.data])
            if len(contacts_resp.data) < page_size:
                break
            offset += page_size

        print(f"Found {len(all_contacts)} contacts with messages")
        all_contact_ids = set(all_contacts)

        # Load current active version for drift detection
        active_version = _FALLBACK_VERSION
        try:
            ver_resp = (
                self.client.table("tenant_classifier_configs")
                .select("version")
                .eq("tenant_id", tenant_id)
                .eq("is_active", True)
                .limit(1)
                .execute()
            )
            if ver_resp.data:
                active_version = ver_resp.data[0]["version"]
        except Exception as e:
            print(f"Warning: could not fetch active config version: {e}")

        # Load most recent classification per contact
        classified_resp = (
            self.client.schema("silver").table("journey_intent_results")
            .select("contact_id, last_inbound_message_at, classifier_version")
            .eq("tenant_id", tenant_id)
            .order("classified_at", desc=True)
            .execute()
        )

        latest_classification: dict[str, dict] = {}
        for row in (classified_resp.data or []):
            cid = row["contact_id"]
            if cid not in latest_classification:
                latest_classification[cid] = row

        never_classified = all_contact_ids - set(latest_classification.keys())

        # Stale: new inbound message since last classification
        stale = set()
        classified_with_timestamp = {
            cid: info["last_inbound_message_at"]
            for cid, info in latest_classification.items()
            if cid in all_contact_ids and info.get("last_inbound_message_at")
        }
        if classified_with_timestamp:
            batch_size = 50
            contact_ids = list(classified_with_timestamp.keys())
            current_latest: dict[str, str] = {}
            for i in range(0, len(contact_ids), batch_size):
                batch = contact_ids[i : i + batch_size]
                msgs_resp = (
                    self.client.schema("silver").table("messages")
                    .select("contact_id, timestamp")
                    .eq("tenant_id", tenant_id)
                    .eq("direction", "inbound")
                    .gte("timestamp", since_date)
                    .in_("contact_id", batch)
                    .order("timestamp", desc=True)
                    .execute()
                )
                for row in (msgs_resp.data or []):
                    cid = row["contact_id"]
                    if cid not in current_latest:
                        current_latest[cid] = row["timestamp"]

            for cid, stored_ts in classified_with_timestamp.items():
                if cid in current_latest and current_latest[cid] > stored_ts:
                    stale.add(cid)

        # Version-drift: classified with an older config version
        version_drift = set()
        for cid, info in latest_classification.items():
            if cid not in all_contact_ids:
                continue
            cv = info.get("classifier_version") or ""
            # Format: "provider/model/vN" — extract vN suffix
            if cv and "/v" in cv:
                try:
                    stored_v = int(cv.rsplit("/v", 1)[-1])
                    if stored_v < active_version:
                        version_drift.add(cid)
                except (ValueError, IndexError):
                    pass

        candidates = list((never_classified | stale | version_drift))[:limit]
        print(
            f"  Never classified: {len(never_classified)}, "
            f"Stale (new messages): {len(stale)}, "
            f"Version drift (v{active_version} active): {len(version_drift)}, "
            f"Total candidates: {len(candidates)}"
        )
        return [{"contact_id": cid} for cid in candidates], stale
