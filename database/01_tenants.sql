-- =====================================================================
-- File: database/01_tenants.sql
-- Purpose: Tenants table - store tenant metadata and credentials
-- Each brand is a tenant
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.tenants (
  tenant_id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL,

  -- Wati integration
  wati_api_token TEXT, -- encrypted
  wati_phone_number TEXT,
  webhook_url TEXT, -- generated unique URL for this tenant
  default_phone_region TEXT,

  -- Configuration
  default_journey_stages TEXT[], -- e.g., ['browsing', 'purchase_intent', ...]

  -- Status
  first_login BOOLEAN DEFAULT TRUE,
  batch_import_contacts_done BOOLEAN DEFAULT FALSE,
  batch_import_messages_done BOOLEAN DEFAULT FALSE,
  status TEXT DEFAULT 'active', -- active, suspended
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  CONSTRAINT tenants_default_phone_region_format CHECK (
    default_phone_region IS NULL
    OR (
      default_phone_region = UPPER(default_phone_region)
      AND CHAR_LENGTH(default_phone_region) = 2
    )
  )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tenants_slug ON public.tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON public.tenants(status) WHERE status = 'active';

-- Comments
COMMENT ON TABLE public.tenants IS 'Multi-tenant configuration - each brand is a tenant';
COMMENT ON COLUMN public.tenants.wati_api_token IS 'Encrypted Wati API token for this tenant';
COMMENT ON COLUMN public.tenants.webhook_url IS 'Unique webhook URL for Wati to send events to this tenant';
COMMENT ON COLUMN public.tenants.default_phone_region IS 'Optional ISO 3166-1 alpha-2 region used when parsing national-format phone numbers';
COMMENT ON COLUMN public.tenants.default_journey_stages IS 'Default AI classification stages for this tenant';
