"""Supabase storage adapter for the jbuild trait contract."""

from __future__ import annotations

from typing import Any


def _response_data(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    return data or []


def _get_default_client():
    from scripts.supabase_client import get_supabase_client

    return get_supabase_client()


class SupabaseTraitStore:
    """Supabase implementation of the storage contract required by jbuild."""

    def __init__(self, client: Any | None = None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = _get_default_client()
        return self._client

    def list_trait_definitions(self, tenant_id: int, include_inactive: bool = False) -> list[dict[str, Any]]:
        query = (
            self.client.table("tenant_trait_definitions")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("trait_key")
        )
        if not include_inactive:
            query = query.eq("is_active", True)
        return _response_data(query.execute())

    def upsert_trait_definition(self, row: dict[str, Any]) -> dict[str, Any]:
        response = (
            self.client.table("tenant_trait_definitions")
            .upsert(row, on_conflict="tenant_id,trait_key")
            .execute()
        )
        rows = _response_data(response)
        return rows[0] if rows else row

    def get_trait_definition(
        self,
        tenant_id: int,
        *,
        trait_id: str | None = None,
        trait_key: str | None = None,
    ) -> dict[str, Any] | None:
        query = (
            self.client.table("tenant_trait_definitions")
            .select("*")
            .eq("tenant_id", tenant_id)
            .limit(1)
        )
        if trait_id:
            query = query.eq("trait_id", trait_id)
        else:
            query = query.eq("trait_key", trait_key)

        rows = _response_data(query.execute())
        return rows[0] if rows else None

    def get_trait_classifier_config(
        self,
        tenant_id: int,
        trait_id: str,
        config_id: str,
    ) -> dict[str, Any] | None:
        rows = _response_data(
            self.client.table("tenant_trait_classifier_configs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("trait_id", trait_id)
            .eq("config_id", config_id)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    def get_active_trait_classifier_config(self, tenant_id: int, trait_id: str) -> dict[str, Any] | None:
        rows = _response_data(
            self.client.table("tenant_trait_classifier_configs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("trait_id", trait_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    def get_draft_trait_classifier_config(self, tenant_id: int, trait_id: str) -> dict[str, Any] | None:
        rows = _response_data(
            self.client.table("tenant_trait_classifier_configs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("trait_id", trait_id)
            .eq("is_active", False)
            .is_("activated_at", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return rows[0] if rows else None

    def update_trait_classifier_draft(
        self,
        config_id: str,
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        rows = _response_data(
            self.client.table("tenant_trait_classifier_configs")
            .update(row)
            .eq("config_id", config_id)
            .execute()
        )
        return rows[0] if rows else None

    def insert_trait_classifier_config(self, row: dict[str, Any]) -> dict[str, Any] | None:
        rows = _response_data(
            self.client.table("tenant_trait_classifier_configs")
            .insert(row)
            .execute()
        )
        return rows[0] if rows else None

    def activate_trait_classifier_config(self, tenant_id: int, trait_id: str, config_id: str) -> Any:
        return self.client.rpc(
            "activate_trait_classifier_config",
            {
                "p_tenant_id": tenant_id,
                "p_trait_id": trait_id,
                "p_config_id": config_id,
            },
        ).execute()

    def get_trait_classifier_version_history(
        self,
        tenant_id: int,
        trait_id: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return _response_data(
            self.client.table("tenant_trait_classifier_configs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("trait_id", trait_id)
            .order("version", desc=True)
            .limit(limit)
            .execute()
        )

    def upsert_contact_trait_values(self, tenant_id: int, rows: list[dict[str, Any]]) -> Any:
        return self.client.rpc(
            "upsert_contact_trait_values",
            {
                "p_tenant_id": tenant_id,
                "p_rows": rows,
            },
        ).execute()

    def get_contact_trait_values(
        self,
        tenant_id: int,
        *,
        contact_ids: list[str] | None = None,
        trait_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            self.client.schema("silver")
            .table("contact_trait_values")
            .select("*")
            .eq("tenant_id", tenant_id)
        )
        if contact_ids:
            query = query.in_("contact_id", contact_ids)
        if trait_ids:
            query = query.in_("trait_id", trait_ids)
        return _response_data(query.execute())

    def get_contact_messages(self, tenant_id: int, contact_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return _response_data(
            self.client.schema("silver")
            .table("messages")
            .select("text, direction, timestamp")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .order("timestamp", desc=False)
            .limit(limit)
            .execute()
        )


def create_trait_service(client: Any | None = None):
    from jbuild.core.traits import TraitService

    return TraitService(SupabaseTraitStore(client=client))
