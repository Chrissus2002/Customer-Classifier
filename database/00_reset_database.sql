-- ============================================================================
-- Database Reset Script
-- ============================================================================
-- This script drops all custom database objects to reset to a clean state
-- Run this before reapplying schema files 01-07 in order
--
-- WARNING: This will DELETE ALL DATA in the database!
--
-- Usage:
--   1. Run this script to drop all objects
--   2. Run schema files in order: 01_tenants.sql -> 07_gold_layer.sql
-- ============================================================================

-- Terminate all active connections (requires superuser - may not work on Supabase)
-- Uncomment if you have permissions:
-- SELECT pg_terminate_backend(pg_stat_activity.pid)
-- FROM pg_stat_activity
-- WHERE pg_stat_activity.datname = current_database()
--   AND pid <> pg_backend_pid();

BEGIN;

-- ============================================================================
-- Drop objects in reverse dependency order
-- ============================================================================

-- Drop Gold Layer (07) - Analytics views
DROP VIEW IF EXISTS gold.engaged_contacts CASCADE;
DROP VIEW IF EXISTS gold.journey_distribution CASCADE;
DROP VIEW IF EXISTS gold.contact_activity CASCADE;
DROP VIEW IF EXISTS gold.contact_metrics CASCADE;

-- Drop Webhook Logging (06) - Observability
DROP VIEW IF EXISTS public.webhook_processing_status CASCADE;
DROP FUNCTION IF EXISTS public.detect_duplicate_contacts() CASCADE;
DROP FUNCTION IF EXISTS public.debug_webhook(UUID) CASCADE;
DROP FUNCTION IF EXISTS public.check_webhook_health(INTEGER) CASCADE;
DROP FUNCTION IF EXISTS public.process_webhook_to_bronze() CASCADE;
DROP TABLE IF EXISTS public.webhook_processing_log CASCADE;
DROP TABLE IF EXISTS public.webhook_logs CASCADE;

-- Drop Functions (05) - Processing functions
DROP FUNCTION IF EXISTS public.upsert_contact_trait_values(BIGINT, JSONB) CASCADE;
DROP FUNCTION IF EXISTS public.activate_trait_classifier_config(BIGINT, UUID, UUID) CASCADE;
DROP FUNCTION IF EXISTS public.trait_resolution_source_rank(TEXT) CASCADE;
DROP FUNCTION IF EXISTS public.activate_classifier_config(BIGINT, UUID) CASCADE;
DROP FUNCTION IF EXISTS bronze.process_to_silver(UUID) CASCADE;
DROP FUNCTION IF EXISTS bronze.transform_webhook_to_silver() CASCADE;
DROP FUNCTION IF EXISTS silver.merge_contacts(BIGINT, UUID, UUID) CASCADE;
DROP FUNCTION IF EXISTS silver.merge_contacts(UUID, UUID, UUID) CASCADE;
DROP FUNCTION IF EXISTS bronze.normalize_phone(TEXT) CASCADE;
DROP FUNCTION IF EXISTS bronze.count_distinct_normalized_phones(TEXT[]) CASCADE;

-- Drop RLS Policies (04)
-- Note: Policies are dropped automatically when tables are dropped
DROP POLICY IF EXISTS tenant_isolation_classifications ON silver.journey_intent_results;
DROP POLICY IF EXISTS tenant_isolation_contact_trait_values ON silver.contact_trait_values;
DROP POLICY IF EXISTS tenant_isolation_messages ON silver.messages;
DROP POLICY IF EXISTS tenant_isolation_contact_wati_keys ON silver.contact_wati_keys;
DROP POLICY IF EXISTS tenant_isolation_contacts ON silver.contacts;
DROP POLICY IF EXISTS tenant_trait_classifier_configs_tenant_isolation ON public.tenant_trait_classifier_configs;
DROP POLICY IF EXISTS tenant_trait_definitions_tenant_isolation ON public.tenant_trait_definitions;

-- Drop Silver Layer (03) - Normalized tables and audit
DROP VIEW IF EXISTS silver.unique_contact_ids CASCADE;
DROP VIEW IF EXISTS silver.contacts_active CASCADE;
DROP TABLE IF EXISTS silver.contact_wati_keys CASCADE;
DROP TABLE IF EXISTS audit.message_reassignments CASCADE;
DROP TABLE IF EXISTS audit.contact_merges CASCADE;
DROP TABLE IF EXISTS public.tenant_segments CASCADE;
DROP TABLE IF EXISTS silver.contact_trait_values CASCADE;
DROP TABLE IF EXISTS public.tenant_trait_classifier_configs CASCADE;
DROP TABLE IF EXISTS public.tenant_trait_definitions CASCADE;
DROP TABLE IF EXISTS public.tenant_journey_stages CASCADE;
DROP TABLE IF EXISTS public.tenant_classifier_configs CASCADE;
DROP TABLE IF EXISTS silver.journey_intent_results CASCADE;
DROP TABLE IF EXISTS silver.messages CASCADE;
DROP TABLE IF EXISTS silver.contacts CASCADE;

-- Drop Bronze Layer (02) - Raw ingestion
DROP TABLE IF EXISTS public.import_jobs CASCADE;
DROP TABLE IF EXISTS public.daemon_task_runs CASCADE;
DROP TABLE IF EXISTS bronze.wati_messages CASCADE;
DROP TABLE IF EXISTS bronze.wati_contacts CASCADE;

-- Drop Tenants (01) - Core tenant management
DROP TABLE IF EXISTS public.tenants CASCADE;

-- ============================================================================
-- Drop custom schemas
-- ============================================================================

DROP SCHEMA IF EXISTS gold CASCADE;
DROP SCHEMA IF EXISTS audit CASCADE;
DROP SCHEMA IF EXISTS silver CASCADE;
DROP SCHEMA IF EXISTS bronze CASCADE;

COMMIT;

-- ============================================================================
-- Verification
-- ============================================================================

-- Check for remaining tables (should only see system tables)
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'auth', 'storage', 'extensions', 'supabase_functions')
ORDER BY schemaname, tablename;

-- Check for remaining views
SELECT schemaname, viewname
FROM pg_views
WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'auth', 'storage', 'extensions', 'supabase_functions')
ORDER BY schemaname, viewname;

-- Check for remaining functions
SELECT n.nspname as schema, p.proname as function
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'auth', 'storage', 'extensions', 'supabase_functions')
ORDER BY schema, function;

-- ============================================================================
-- Next Steps
-- ============================================================================
-- Run the following commands to rebuild the schema:
--
--   psql -f database/01_tenants.sql
--   psql -f database/02_bronze_layer.sql
--   psql -f database/03_silver_layer.sql
--   psql -f database/04_rls_policies.sql
--   psql -f database/05_functions.sql
--   psql -f database/06_webhook_logging.sql
--   psql -f database/07_gold_layer.sql
--
-- Or using Supabase MCP:
--   mcp__supabase__apply_migration for each file in order
-- ============================================================================
