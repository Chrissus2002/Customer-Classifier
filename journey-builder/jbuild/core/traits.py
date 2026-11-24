"""Core services for jbuild trait definitions and current trait values."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Iterable, Protocol
from uuid import UUID


VALID_VALUE_TYPES = {"enum", "boolean", "text"}
VALID_RESOLVER_MODES = {"mixed", "imported", "rule", "manual", "classifier"}
VALID_RESOLUTION_SOURCES = {"manual", "imported", "rule", "classifier"}
SOURCE_PRECEDENCE = {
    "manual": 4,
    "imported": 3,
    "rule": 2,
    "classifier": 1,
}
TRAIT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class TraitStore(Protocol):
    """Storage contract required by the jbuild trait core."""

    def list_trait_definitions(self, tenant_id: int, include_inactive: bool = False) -> list[dict[str, Any]]:
        ...

    def upsert_trait_definition(self, row: dict[str, Any]) -> dict[str, Any]:
        ...

    def get_trait_definition(
        self,
        tenant_id: int,
        *,
        trait_id: str | None = None,
        trait_key: str | None = None,
    ) -> dict[str, Any] | None:
        ...

    def get_trait_classifier_config(
        self,
        tenant_id: int,
        trait_id: str,
        config_id: str,
    ) -> dict[str, Any] | None:
        ...

    def get_active_trait_classifier_config(self, tenant_id: int, trait_id: str) -> dict[str, Any] | None:
        ...

    def get_draft_trait_classifier_config(self, tenant_id: int, trait_id: str) -> dict[str, Any] | None:
        ...

    def update_trait_classifier_draft(
        self,
        config_id: str,
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...

    def insert_trait_classifier_config(self, row: dict[str, Any]) -> dict[str, Any] | None:
        ...

    def activate_trait_classifier_config(self, tenant_id: int, trait_id: str, config_id: str) -> Any:
        ...

    def get_trait_classifier_version_history(
        self,
        tenant_id: int,
        trait_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        ...

    def upsert_contact_trait_values(self, tenant_id: int, rows: list[dict[str, Any]]) -> Any:
        ...

    def get_contact_trait_values(
        self,
        tenant_id: int,
        *,
        contact_ids: list[str] | None = None,
        trait_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        ...

    def get_contact_messages(self, tenant_id: int, contact_id: str, limit: int = 50) -> list[dict[str, Any]]:
        ...


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_trait_key(trait_key: str) -> str:
    normalized = (trait_key or "").strip().lower()
    if not TRAIT_KEY_RE.match(normalized):
        raise ValueError(
            "trait_key must start with a lowercase letter and contain only "
            "lowercase letters, numbers, and underscores"
        )
    return normalized


def normalize_allowed_values(values: Iterable[str] | str | None) -> list[str] | None:
    if values is None:
        return None
    if isinstance(values, str):
        values = values.split(",")
    normalized = []
    for value in values:
        item = str(value).strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized or None


def validate_trait_definition(
    trait_key: str,
    value_type: str,
    allowed_values: Iterable[str] | str | None = None,
    resolver_mode: str = "mixed",
) -> tuple[str, str, list[str] | None, str]:
    normalized_key = normalize_trait_key(trait_key)
    normalized_type = (value_type or "").strip().lower()
    if normalized_type not in VALID_VALUE_TYPES:
        raise ValueError(f"value_type must be one of {sorted(VALID_VALUE_TYPES)}")

    normalized_mode = (resolver_mode or "mixed").strip().lower()
    if normalized_mode not in VALID_RESOLVER_MODES:
        raise ValueError(f"resolver_mode must be one of {sorted(VALID_RESOLVER_MODES)}")

    normalized_values = normalize_allowed_values(allowed_values)
    if normalized_type == "enum" and not normalized_values:
        raise ValueError("enum traits require at least one allowed value")

    return normalized_key, normalized_type, normalized_values, normalized_mode


def source_rank(source: str) -> int:
    return SOURCE_PRECEDENCE.get((source or "").strip().lower(), 0)


def validate_resolution_source(source: str) -> str:
    normalized = (source or "").strip().lower()
    if normalized not in VALID_RESOLUTION_SOURCES:
        raise ValueError(f"resolution_source must be one of {sorted(VALID_RESOLUTION_SOURCES)}")
    return normalized


def looks_like_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def should_replace_trait_value(
    existing_source: str,
    existing_resolved_at: str | datetime | None,
    incoming_source: str,
    incoming_resolved_at: str | datetime | None,
) -> bool:
    existing_rank = source_rank(existing_source)
    incoming_rank = source_rank(incoming_source)
    if incoming_rank > existing_rank:
        return True
    if incoming_rank < existing_rank:
        return False
    if existing_resolved_at is None:
        return True
    if incoming_resolved_at is None:
        return False
    return str(incoming_resolved_at) >= str(existing_resolved_at)


class TraitService:
    """Trait domain service used by jbuild CLI, API, and worker adapters."""

    def __init__(self, store: TraitStore):
        self.store = store

    def list_trait_definitions(self, tenant_id: int, include_inactive: bool = False) -> list[dict[str, Any]]:
        return self.store.list_trait_definitions(tenant_id, include_inactive=include_inactive)

    def create_or_update_trait_definition(
        self,
        tenant_id: int,
        trait_key: str,
        value_type: str,
        *,
        display_label: str | None = None,
        description: str | None = None,
        allowed_values: Iterable[str] | str | None = None,
        resolver_mode: str = "mixed",
        is_active: bool = True,
    ) -> dict[str, Any]:
        trait_key, value_type, allowed_values, resolver_mode = validate_trait_definition(
            trait_key,
            value_type,
            allowed_values,
            resolver_mode,
        )
        row = {
            "tenant_id": tenant_id,
            "trait_key": trait_key,
            "display_label": display_label or trait_key.replace("_", " ").title(),
            "description": description,
            "value_type": value_type,
            "allowed_values": allowed_values,
            "resolver_mode": resolver_mode,
            "is_active": is_active,
            "updated_at": utc_now_iso(),
        }
        return self.store.upsert_trait_definition(row)

    def get_trait_definition(
        self,
        tenant_id: int,
        *,
        trait_id: str | None = None,
        trait_key: str | None = None,
    ) -> dict[str, Any] | None:
        if not trait_id and not trait_key:
            raise ValueError("trait_id or trait_key is required")

        normalized_key = normalize_trait_key(trait_key) if trait_key else None
        return self.store.get_trait_definition(tenant_id, trait_id=trait_id, trait_key=normalized_key)

    def require_trait_id(self, tenant_id: int, trait_id_or_key: str) -> str:
        trait = None
        if looks_like_uuid(trait_id_or_key):
            trait = self.get_trait_definition(tenant_id, trait_id=trait_id_or_key)
        if trait is None:
            trait = self.get_trait_definition(tenant_id, trait_key=trait_id_or_key)
        if trait is None:
            raise ValueError(f"Trait not found for tenant {tenant_id}: {trait_id_or_key}")
        return str(trait["trait_id"])

    def get_trait_classifier_config(
        self,
        tenant_id: int,
        trait_id: str,
        config_id: str,
    ) -> dict[str, Any] | None:
        return self.store.get_trait_classifier_config(tenant_id, trait_id, config_id)

    def get_active_trait_classifier_config(self, tenant_id: int, trait_id: str) -> dict[str, Any] | None:
        return self.store.get_active_trait_classifier_config(tenant_id, trait_id)

    def get_draft_trait_classifier_config(self, tenant_id: int, trait_id: str) -> dict[str, Any] | None:
        return self.store.get_draft_trait_classifier_config(tenant_id, trait_id)

    def save_trait_classifier_draft(
        self,
        tenant_id: int,
        trait_id: str,
        master_prompt: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        allowed_values_snapshot: Iterable[str] | str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        trait = self.get_trait_definition(tenant_id, trait_id=trait_id)
        if trait is None:
            raise ValueError(f"Trait {trait_id} not found for tenant {tenant_id}")

        labels = normalize_allowed_values(allowed_values_snapshot) or normalize_allowed_values(
            trait.get("allowed_values")
        )
        if not labels:
            raise ValueError("Trait Classifier drafts require allowed values")

        draft_row = {
            "master_prompt": master_prompt,
            "provider": provider,
            "model": model,
            "allowed_values_snapshot": labels,
            "notes": notes,
        }
        draft = self.get_draft_trait_classifier_config(tenant_id, trait_id)
        if draft:
            return self.store.update_trait_classifier_draft(draft["config_id"], draft_row) or draft

        history = self.get_trait_classifier_version_history(tenant_id, trait_id, limit=1)
        next_version = int(history[0]["version"]) + 1 if history else 1
        row = {
            "tenant_id": tenant_id,
            "trait_id": trait_id,
            "version": next_version,
            **draft_row,
            "is_active": False,
        }
        return self.store.insert_trait_classifier_config(row) or row

    def activate_trait_classifier_config(self, tenant_id: int, trait_id: str, config_id: str) -> Any:
        return self.store.activate_trait_classifier_config(tenant_id, trait_id, config_id)

    def get_trait_classifier_version_history(
        self,
        tenant_id: int,
        trait_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.store.get_trait_classifier_version_history(tenant_id, trait_id, limit=limit)

    def upsert_contact_trait_values(self, tenant_id: int, rows: list[dict[str, Any]]) -> Any:
        prepared = [self._prepare_trait_value_row(tenant_id, row) for row in rows]
        return self.store.upsert_contact_trait_values(tenant_id, prepared)

    def set_contact_trait_value(
        self,
        tenant_id: int,
        contact_id: str,
        trait_id_or_key: str,
        resolved_value: str,
        *,
        resolution_source: str,
        confidence: float | None = None,
        reasoning: str | None = None,
        classifier_version: str | None = None,
        source_metadata: dict[str, Any] | None = None,
        resolved_at: str | None = None,
    ) -> Any:
        row = {
            "contact_id": contact_id,
            "trait_id": self.require_trait_id(tenant_id, trait_id_or_key),
            "resolved_value": resolved_value,
            "resolution_source": resolution_source,
            "confidence": confidence,
            "reasoning": reasoning,
            "classifier_version": classifier_version,
            "source_metadata": source_metadata or {},
            "resolved_at": resolved_at or utc_now_iso(),
        }
        return self.upsert_contact_trait_values(tenant_id, [row])

    def get_contact_trait_values(
        self,
        tenant_id: int,
        *,
        contact_ids: list[str] | None = None,
        trait_ids: list[str] | None = None,
        trait_keys: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if trait_ids and trait_keys:
            raise ValueError("Pass trait_ids or trait_keys, not both")
        resolved_trait_ids = trait_ids
        if trait_keys:
            resolved_trait_ids = [self.require_trait_id(tenant_id, key) for key in trait_keys]
        return self.store.get_contact_trait_values(
            tenant_id,
            contact_ids=contact_ids,
            trait_ids=resolved_trait_ids,
        )

    def get_contact_messages(self, tenant_id: int, contact_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.get_contact_messages(tenant_id, contact_id, limit=limit)

    def _prepare_trait_value_row(self, tenant_id: int, row: dict[str, Any]) -> dict[str, Any]:
        trait_id = row.get("trait_id")
        trait_key = row.get("trait_key")
        if not trait_id and trait_key:
            trait_id = self.require_trait_id(tenant_id, str(trait_key))
        if not trait_id:
            raise ValueError("trait_id or trait_key is required")
        resolved_value = str(row.get("resolved_value") or "").strip()
        if not resolved_value:
            raise ValueError("resolved_value is required")
        return {
            "contact_id": row["contact_id"],
            "trait_id": str(trait_id),
            "resolved_value": resolved_value,
            "resolution_source": validate_resolution_source(str(row.get("resolution_source") or "")),
            "confidence": row.get("confidence"),
            "reasoning": row.get("reasoning"),
            "classifier_version": row.get("classifier_version"),
            "source_metadata": row.get("source_metadata") or {},
            "resolved_at": row.get("resolved_at") or utc_now_iso(),
        }
