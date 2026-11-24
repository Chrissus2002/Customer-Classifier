-- =====================================================================
-- File: database/08_grants.sql
-- Purpose: Grant custom schemas (bronze/silver/gold) to Supabase roles
--
-- Why this file exists:
--   Hosted Supabase auto-grants project-created schemas to its internal
--   roles (authenticator, service_role, anon, authenticated). Self-hosted
--   Supabase does NOT — schemas created by our migration files are only
--   owned by the `postgres` superuser and inaccessible via PostgREST.
--
--   Without these grants, PostgREST (exposed via Kong on self-host) returns
--   `permission denied for schema silver` even for the service_role JWT.
--
-- Where this came from:
--   Discovered during first end-to-end self-host deploy on schipperinc VPS,
--   2026-04-07. `PGRST_DB_SCHEMAS=public,storage,graphql_public,bronze,silver,gold`
--   made the schemas VISIBLE to PostgREST but not ACCESSIBLE.
--
-- Idempotency: All GRANT/ALTER DEFAULT PRIVILEGES statements are safe to
-- re-run.
-- =====================================================================

DO $$
DECLARE
  target_schemas TEXT[] := ARRAY['bronze', 'silver', 'gold'];
  target_roles   TEXT[] := ARRAY['authenticator', 'service_role', 'anon', 'authenticated'];
  s TEXT;
  r TEXT;
BEGIN
  FOREACH s IN ARRAY target_schemas LOOP
    -- Skip schemas that don't exist (so this file is robust to being run
    -- before the schemas are created)
    IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = s) THEN
      RAISE NOTICE 'Schema % does not exist, skipping grants', s;
      CONTINUE;
    END IF;

    FOREACH r IN ARRAY target_roles LOOP
      -- Skip roles that don't exist on this install (e.g. older Supabase
      -- postgres image without `authenticated`)
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
        RAISE NOTICE 'Role % does not exist, skipping', r;
        CONTINUE;
      END IF;

      EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', s, r);
      EXECUTE format('GRANT ALL ON ALL TABLES IN SCHEMA %I TO %I', s, r);
      EXECUTE format('GRANT ALL ON ALL SEQUENCES IN SCHEMA %I TO %I', s, r);
      EXECUTE format('GRANT ALL ON ALL FUNCTIONS IN SCHEMA %I TO %I', s, r);

      -- Future tables/sequences created in this schema will inherit grants
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO %I', s, r);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON SEQUENCES TO %I', s, r);
      EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON FUNCTIONS TO %I', s, r);
    END LOOP;
  END LOOP;
END
$$;

COMMENT ON SCHEMA bronze IS 'Raw data layer. Accessible to service_role via PostgREST. No RLS.';
COMMENT ON SCHEMA silver IS 'Deduplicated / normalized layer. Tenant-isolated via RLS policies in 04_rls_policies.sql.';
COMMENT ON SCHEMA gold   IS 'Analytics views. Read-only.';
