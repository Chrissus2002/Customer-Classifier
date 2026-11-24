-- =====================================================================
-- File: database/04_rls_policies.sql
-- Purpose: Row-Level Security policies for multi-tenant isolation
-- All tenant-scoped tables use current_setting('app.tenant_id', true) for isolation
-- =====================================================================

-- =====================================================================
-- RLS ON SILVER.CONTACTS
-- =====================================================================

ALTER TABLE silver.contacts ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_contacts ON silver.contacts
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_isolation_contacts ON silver.contacts IS 'Ensures contacts can only be accessed/modified within tenant context';

-- =====================================================================
-- RLS ON SILVER.CONTACT_WATI_KEYS
-- =====================================================================

ALTER TABLE silver.contact_wati_keys ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_contact_wati_keys ON silver.contact_wati_keys
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_isolation_contact_wati_keys ON silver.contact_wati_keys IS 'Ensures Wati contact mappings can only be accessed/modified within tenant context';

-- =====================================================================
-- RLS ON SILVER.MESSAGES
-- =====================================================================

ALTER TABLE silver.messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_messages ON silver.messages
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_isolation_messages ON silver.messages IS 'Ensures messages can only be accessed/modified within tenant context';

-- =====================================================================
-- RLS ON SILVER.JOURNEY_INTENT_RESULTS
-- =====================================================================

ALTER TABLE silver.journey_intent_results ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_classifications ON silver.journey_intent_results
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_isolation_classifications ON silver.journey_intent_results IS 'Ensures classifications can only be accessed/modified within tenant context';

-- =====================================================================
-- RLS ON JBUILD TRAIT TABLES
-- =====================================================================

ALTER TABLE public.tenant_trait_definitions ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_trait_definitions_tenant_isolation ON public.tenant_trait_definitions
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_trait_definitions_tenant_isolation ON public.tenant_trait_definitions IS 'Ensures jbuild trait definitions can only be accessed/modified within tenant context';

ALTER TABLE public.tenant_trait_classifier_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_trait_classifier_configs_tenant_isolation ON public.tenant_trait_classifier_configs
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_trait_classifier_configs_tenant_isolation ON public.tenant_trait_classifier_configs IS 'Ensures jbuild Trait Classifier configs can only be accessed/modified within tenant context';

ALTER TABLE silver.contact_trait_values ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_contact_trait_values ON silver.contact_trait_values
  FOR ALL
  USING (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  )
  WITH CHECK (
    current_setting('app.tenant_id', true) IS NOT NULL
    AND tenant_id = current_setting('app.tenant_id', true)::BIGINT
  );

COMMENT ON POLICY tenant_isolation_contact_trait_values ON silver.contact_trait_values IS 'Ensures current jbuild trait values can only be accessed/modified within tenant context';

-- =====================================================================
-- USAGE
-- =====================================================================

-- To set tenant context before queries:
-- SET app.tenant_id = 'tenant-uuid-here';
--
-- All subsequent queries will automatically filter to only that tenant's data
-- This ensures complete data isolation between tenants at the database level
