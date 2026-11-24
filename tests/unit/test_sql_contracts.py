from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_process_messages_sql_joins_through_contact_wati_keys():
    sql = (PROJECT_ROOT / "database" / "05_functions.sql").read_text()

    assert "JOIN silver.contact_wati_keys cwk" in sql
    assert "AND c.wati_contact_id = bm.wati_contact_id" not in sql


def test_webhook_sql_resolves_null_waid_outbound_through_conversation_history():
    sql = (PROJECT_ROOT / "database" / "05_functions.sql").read_text()

    assert "outbound message has no waId and no existing conversation contact" in sql
    assert "FROM silver.messages m" in sql
    assert "AND m.conversation_id = v_conversation_id" in sql
    assert "c.phone_normalized IS DISTINCT FROM v_tenant_phone_normalized" in sql


def test_contact_upserts_refresh_legacy_wati_contact_id():
    sql = (PROJECT_ROOT / "database" / "05_functions.sql").read_text()

    assert sql.count(
        "wati_contact_id = COALESCE(EXCLUDED.wati_contact_id, silver.contacts.wati_contact_id)"
    ) >= 2


def test_silver_schema_defines_contact_wati_keys_table():
    sql = (PROJECT_ROOT / "database" / "03_silver_layer.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS silver.contact_wati_keys" in sql
    assert "wati_lookup_phone TEXT" in sql


def test_jbuild_trait_schema_defines_current_value_contract():
    sql = (PROJECT_ROOT / "database" / "03_silver_layer.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS public.tenant_trait_definitions" in sql
    assert "CREATE TABLE IF NOT EXISTS public.tenant_trait_classifier_configs" in sql
    assert "CREATE TABLE IF NOT EXISTS silver.contact_trait_values" in sql
    assert "UNIQUE(tenant_id, contact_id, trait_id)" in sql
    assert "CHECK (resolution_source IN ('manual', 'imported', 'rule', 'classifier'))" in sql
    assert "allowed_values_snapshot JSONB NOT NULL" in sql
    assert "jsonb_array_length(allowed_values) > 0" in sql
    assert "tenant_trait_classifier_configs_one_draft_per_trait" in sql
    assert "jsonb_array_length(allowed_values_snapshot) > 0" in sql


def test_jbuild_trait_rls_policies_are_tenant_scoped():
    sql = (PROJECT_ROOT / "database" / "04_rls_policies.sql").read_text()

    assert "ALTER TABLE public.tenant_trait_definitions ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE public.tenant_trait_classifier_configs ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE silver.contact_trait_values ENABLE ROW LEVEL SECURITY" in sql
    assert "tenant_trait_definitions_tenant_isolation" in sql
    assert "tenant_trait_classifier_configs_tenant_isolation" in sql
    assert "tenant_isolation_contact_trait_values" in sql


def test_jbuild_trait_functions_enforce_activation_and_precedence():
    sql = (PROJECT_ROOT / "database" / "05_functions.sql").read_text()

    assert "CREATE OR REPLACE FUNCTION public.trait_resolution_source_rank" in sql
    assert "WHEN 'manual' THEN 4" in sql
    assert "WHEN 'classifier' THEN 1" in sql
    assert "CREATE OR REPLACE FUNCTION public.activate_trait_classifier_config" in sql
    assert "WHERE tenant_id = p_tenant_id" in sql
    assert "AND trait_id = p_trait_id" in sql
    assert "CREATE OR REPLACE FUNCTION public.upsert_contact_trait_values" in sql
    assert "ON CONFLICT (tenant_id, contact_id, trait_id) DO NOTHING" in sql
    assert "IF v_contact.is_canonical IS DISTINCT FROM true THEN" in sql
    assert "v_trait_definition.allowed_values ? v_resolved_value" in sql
    assert "v_resolved_value NOT IN ('true', 'false', 'unknown')" in sql


def test_contact_merge_reconciles_jbuild_trait_values():
    sql = (PROJECT_ROOT / "database" / "05_functions.sql").read_text()

    assert "Reconcile current jbuild trait values" in sql
    assert "UPDATE silver.contact_trait_values source_values" in sql
    assert "DELETE FROM silver.contact_trait_values" in sql
    assert "'trait_rows_reassigned', v_traits_reassigned" in sql
