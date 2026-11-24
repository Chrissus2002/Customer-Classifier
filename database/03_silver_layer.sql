-- =====================================================================
-- File: database/03_silver_layer.sql
-- Purpose: Silver Layer - Processed, deduplicated data layer
-- Also includes audit schema for merge tracking
-- =====================================================================

-- Create schemas
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS audit;

-- =====================================================================
-- SILVER LAYER TABLES
-- =====================================================================

-- Contacts (Silver Layer)
CREATE TABLE IF NOT EXISTS silver.contacts (
  contact_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  batch_id UUID REFERENCES public.import_jobs(job_id),  -- NULL for webhooks

  -- Legacy compatibility identity
  phone_normalized TEXT NOT NULL, -- current Wati/MX-compatible dedupe and lookup key
  phone_raw TEXT, -- exactly as received from Wati

  -- Shadow canonical identity (dialo-5, populated by Python reconciliation)
  phone_identity_key TEXT,
  phone_e164 TEXT,
  normalization_status TEXT,
  normalization_region TEXT,
  phone_raw_primary TEXT,
  wati_lookup_phone TEXT,

  -- Profile
  name TEXT,

  -- Source where the contact came from
  source TEXT,

  -- External references
  wati_contact_id TEXT, -- Legacy primary Wati identity kept for compatibility

  -- Merge tracking
  is_canonical BOOLEAN DEFAULT true,
  merged_into UUID REFERENCES silver.contacts(contact_id),
  merged_at TIMESTAMPTZ,

  -- Timestamps
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(tenant_id, phone_normalized)
);

-- Indexes for contacts
CREATE INDEX IF NOT EXISTS idx_contacts_tenant ON silver.contacts(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_contacts_phone ON silver.contacts(tenant_id, phone_normalized);
CREATE INDEX IF NOT EXISTS idx_contacts_identity_key ON silver.contacts(tenant_id, phone_identity_key) WHERE phone_identity_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_phone_e164 ON silver.contacts(tenant_id, phone_e164) WHERE phone_e164 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_source ON silver.contacts(tenant_id, source);
CREATE INDEX IF NOT EXISTS idx_contacts_wati_lookup_phone ON silver.contacts(tenant_id, wati_lookup_phone) WHERE wati_lookup_phone IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_contacts_wati_id ON silver.contacts(tenant_id, wati_contact_id);
CREATE INDEX IF NOT EXISTS idx_contacts_canonical ON silver.contacts(tenant_id) WHERE is_canonical = true;

COMMENT ON TABLE silver.contacts IS 'Deduplicated contacts. phone_normalized remains the legacy compatibility key; phone_identity_key is the shadow canonical multi-country identity.';
COMMENT ON COLUMN silver.contacts.phone_normalized IS 'Legacy Wati-compatible dedupe and lookup key retained for backward compatibility';
COMMENT ON COLUMN silver.contacts.phone_identity_key IS 'Shadow canonical contact identity populated by the Python phone_identity parser';
COMMENT ON COLUMN silver.contacts.phone_e164 IS 'Best canonical E.164 form when parsing succeeds';
COMMENT ON COLUMN silver.contacts.normalization_status IS 'How phone_identity_key was derived (e164, assumed_region, wati_fallback, raw_fallback, missing)';
COMMENT ON COLUMN silver.contacts.normalization_region IS 'Tenant region context used during canonical parsing';
COMMENT ON COLUMN silver.contacts.phone_raw_primary IS 'Preferred raw phone value retained for audit and display';
COMMENT ON COLUMN silver.contacts.wati_lookup_phone IS 'Explicit Wati-facing phone used for getMessages and campaign CSV exports';
COMMENT ON COLUMN silver.contacts.contact_id IS 'Technical identifier - UUID for FK references';
COMMENT ON COLUMN silver.contacts.is_canonical IS 'False if contact was merged into another contact';
COMMENT ON COLUMN silver.contacts.merged_into IS 'Points to canonical contact if this contact was merged';

-- View for active contacts only
CREATE OR REPLACE VIEW silver.contacts_active AS
SELECT * FROM silver.contacts WHERE is_canonical = true;

-- Provider identity mapping: multiple Wati contacts can collapse into one Dialo contact
CREATE TABLE IF NOT EXISTS silver.contact_wati_keys (
  contact_key_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  contact_id UUID NOT NULL REFERENCES silver.contacts(contact_id) ON DELETE CASCADE,
  wati_contact_id TEXT NOT NULL,
  wati_lookup_phone TEXT,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(tenant_id, wati_contact_id)
);

CREATE INDEX IF NOT EXISTS idx_contact_wati_keys_contact ON silver.contact_wati_keys(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_wati_keys_lookup_phone ON silver.contact_wati_keys(tenant_id, wati_lookup_phone);
CREATE INDEX IF NOT EXISTS idx_contact_wati_keys_primary ON silver.contact_wati_keys(contact_id, is_primary);

COMMENT ON TABLE silver.contact_wati_keys IS 'Many-to-one mapping from Wati contact identities to canonical Dialo contacts';
COMMENT ON COLUMN silver.contact_wati_keys.wati_lookup_phone IS 'Provider-facing phone Dialo should pass back to Wati APIs for this contact identity';

-- Messages (Silver Layer)
CREATE TABLE IF NOT EXISTS silver.messages (
  message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  contact_id UUID NOT NULL REFERENCES silver.contacts(contact_id),
  batch_id UUID REFERENCES public.import_jobs(job_id),  -- NULL for webhooks

  -- Message content
  text TEXT,
  direction TEXT, -- 'inbound', 'outbound'
  message_type TEXT, -- 'text', 'image', 'template'

  -- External reference
  wati_message_id TEXT,
  conversation_id TEXT,

  -- Timestamps
  timestamp TIMESTAMPTZ NOT NULL, -- when message was sent/received
  created_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(tenant_id, wati_message_id) -- prevent duplicate webhook processing
);

-- Indexes for messages
CREATE INDEX IF NOT EXISTS idx_messages_contact ON silver.messages(contact_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_tenant_time ON silver.messages(tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_messages_wati_id ON silver.messages(tenant_id, wati_message_id);

COMMENT ON TABLE silver.messages IS 'Processed messages linked to contacts';
COMMENT ON COLUMN silver.messages.wati_message_id IS 'Unique constraint prevents duplicate webhook processing';

-- View used by the classifier orchestrator to get one row per contact with messages
DROP VIEW IF EXISTS silver.unique_contact_ids CASCADE;
CREATE VIEW silver.unique_contact_ids AS
SELECT contact_id, tenant_id, MAX(timestamp) AS timestamp
FROM silver.messages
GROUP BY contact_id, tenant_id;

-- Journey Classifications
CREATE TABLE IF NOT EXISTS silver.journey_intent_results (
  result_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  contact_id UUID NOT NULL REFERENCES silver.contacts(contact_id),

  -- Classification result
  journey_stage TEXT NOT NULL, -- tenant-specific stage name
  confidence FLOAT,
  reasoning TEXT,

  -- Context
  classifier_version TEXT, -- track which classifier produced this
  classified_at TIMESTAMPTZ DEFAULT NOW(),
  last_inbound_message_at TIMESTAMPTZ, -- timestamp of contact's most recent inbound message at classification time

  -- Latest result per contact
  UNIQUE(tenant_id, contact_id)
);

-- Indexes for journey classifications
CREATE INDEX IF NOT EXISTS idx_classifications_contact ON silver.journey_intent_results(contact_id, classified_at DESC);
CREATE INDEX IF NOT EXISTS idx_classifications_tenant ON silver.journey_intent_results(tenant_id, journey_stage);
CREATE INDEX IF NOT EXISTS idx_classifications_version ON silver.journey_intent_results(classifier_version);

COMMENT ON TABLE silver.journey_intent_results IS 'AI classification results - journey stage per contact';
COMMENT ON COLUMN silver.journey_intent_results.classifier_version IS 'Tracks which classifier config version was used';

-- =====================================================================
-- CONFIGURATION TABLES
-- =====================================================================

-- Tenant Classifier Configs (master prompt per tenant per version)
CREATE TABLE IF NOT EXISTS public.tenant_classifier_configs (
  config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  version INTEGER NOT NULL,
  master_prompt TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  activated_at TIMESTAMPTZ,
  notes TEXT,
  UNIQUE(tenant_id, version)
);

-- Enforce at most one active config per tenant
CREATE UNIQUE INDEX IF NOT EXISTS tenant_classifier_configs_one_active_per_tenant
  ON public.tenant_classifier_configs(tenant_id) WHERE is_active;

COMMENT ON TABLE public.tenant_classifier_configs IS 'Master classifier prompt per tenant per version. One active version at a time.';

-- Journey Stages (child rows for a classifier config version)
CREATE TABLE IF NOT EXISTS public.tenant_journey_stages (
  stage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  config_id UUID NOT NULL REFERENCES public.tenant_classifier_configs(config_id) ON DELETE CASCADE,
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  stage_name TEXT NOT NULL,
  stage_description TEXT NOT NULL,
  display_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(config_id, stage_name)
);

CREATE INDEX IF NOT EXISTS idx_journey_stages_config ON public.tenant_journey_stages(config_id, display_order);

COMMENT ON TABLE public.tenant_journey_stages IS 'Journey stage definitions per classifier config version. Cascades on config delete.';

-- RLS: classifier config tables are tenant-scoped
ALTER TABLE public.tenant_classifier_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_classifier_configs_tenant_isolation ON public.tenant_classifier_configs
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id', true)::BIGINT)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::BIGINT);

ALTER TABLE public.tenant_journey_stages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_journey_stages_tenant_isolation ON public.tenant_journey_stages
  FOR ALL
  USING (tenant_id = current_setting('app.tenant_id', true)::BIGINT)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::BIGINT);

-- Tenant Segments
-- Trait Definitions
CREATE TABLE IF NOT EXISTS public.tenant_trait_definitions (
  trait_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  trait_key TEXT NOT NULL,
  display_label TEXT NOT NULL,
  description TEXT,
  value_type TEXT NOT NULL,
  allowed_values JSONB,
  resolver_mode TEXT NOT NULL DEFAULT 'mixed',
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(tenant_id, trait_key),
  CHECK (trait_key ~ '^[a-z][a-z0-9_]*$'),
  CHECK (value_type IN ('enum', 'boolean', 'text')),
  CHECK (
    value_type <> 'enum'
    OR (
      allowed_values IS NOT NULL
      AND jsonb_typeof(allowed_values) = 'array'
      AND jsonb_array_length(allowed_values) > 0
    )
  ),
  CHECK (resolver_mode IN ('mixed', 'imported', 'rule', 'manual', 'classifier'))
);

CREATE INDEX IF NOT EXISTS idx_trait_definitions_tenant
  ON public.tenant_trait_definitions(tenant_id, is_active, trait_key);

COMMENT ON TABLE public.tenant_trait_definitions IS 'Tenant-scoped reusable chat trait catalog for jbuild';
COMMENT ON COLUMN public.tenant_trait_definitions.trait_key IS 'Stable machine key such as customer_type';
COMMENT ON COLUMN public.tenant_trait_definitions.allowed_values IS 'JSON array of valid labels for enum-like traits';

-- Trait Classifier Configs
CREATE TABLE IF NOT EXISTS public.tenant_trait_classifier_configs (
  config_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  trait_id UUID NOT NULL REFERENCES public.tenant_trait_definitions(trait_id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  master_prompt TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  allowed_values_snapshot JSONB NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  activated_at TIMESTAMPTZ,
  notes TEXT,

  UNIQUE(tenant_id, trait_id, version),
  CHECK (version > 0),
  CHECK (
    jsonb_typeof(allowed_values_snapshot) = 'array'
    AND jsonb_array_length(allowed_values_snapshot) > 0
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS tenant_trait_classifier_configs_one_active_per_trait
  ON public.tenant_trait_classifier_configs(tenant_id, trait_id) WHERE is_active;

CREATE UNIQUE INDEX IF NOT EXISTS tenant_trait_classifier_configs_one_draft_per_trait
  ON public.tenant_trait_classifier_configs(tenant_id, trait_id)
  WHERE is_active = false AND activated_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_trait_classifier_configs_trait
  ON public.tenant_trait_classifier_configs(tenant_id, trait_id, version DESC);

COMMENT ON TABLE public.tenant_trait_classifier_configs IS 'Per-trait classifier config versions for jbuild Trait Classifiers';
COMMENT ON COLUMN public.tenant_trait_classifier_configs.allowed_values_snapshot IS 'Label set frozen at author/test time for this Trait Classifier version';

-- Current Trait Values
CREATE TABLE IF NOT EXISTS silver.contact_trait_values (
  trait_value_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  contact_id UUID NOT NULL REFERENCES silver.contacts(contact_id) ON DELETE CASCADE,
  trait_id UUID NOT NULL REFERENCES public.tenant_trait_definitions(trait_id) ON DELETE CASCADE,
  resolved_value TEXT NOT NULL,
  resolution_source TEXT NOT NULL,
  confidence FLOAT,
  reasoning TEXT,
  classifier_version TEXT,
  source_metadata JSONB,
  resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE(tenant_id, contact_id, trait_id),
  CHECK (resolution_source IN ('manual', 'imported', 'rule', 'classifier')),
  CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE INDEX IF NOT EXISTS idx_contact_trait_values_lookup
  ON silver.contact_trait_values(tenant_id, trait_id, resolved_value);
CREATE INDEX IF NOT EXISTS idx_contact_trait_values_contact
  ON silver.contact_trait_values(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_trait_values_source
  ON silver.contact_trait_values(tenant_id, resolution_source);

COMMENT ON TABLE silver.contact_trait_values IS 'Current resolved jbuild trait value per canonical contact/chat owner';
COMMENT ON COLUMN silver.contact_trait_values.resolved_value IS 'Current value only; unresolved means no row, explicit unknown means resolved unknown';
COMMENT ON COLUMN silver.contact_trait_values.resolution_source IS 'Canonical source: manual, imported, rule, or classifier';

-- Tenant Segments
CREATE TABLE IF NOT EXISTS public.tenant_segments (
  segment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),

  name TEXT NOT NULL,
  description TEXT,
  query_config JSONB NOT NULL, -- stores segment rules (filters, date ranges, stages)

  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(tenant_id, name)
);

-- Index for segments
CREATE INDEX IF NOT EXISTS idx_segments_tenant ON public.tenant_segments(tenant_id, is_active);

COMMENT ON TABLE public.tenant_segments IS 'Tenant-defined segments for analytics and CSV export';
COMMENT ON COLUMN public.tenant_segments.query_config IS 'JSONB containing filter rules (journey_stage, days_active, etc.)';

-- =====================================================================
-- AUDIT SCHEMA TABLES
-- =====================================================================

-- Contact Merges Audit
CREATE TABLE IF NOT EXISTS audit.contact_merges (
  merge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL,

  source_contact_id UUID NOT NULL, -- the duplicate (merged away)
  target_contact_id UUID NOT NULL, -- the canonical (kept)

  reason TEXT DEFAULT 'duplicate_phone',

  -- What changed
  messages_reassigned INTEGER,
  fields_merged JSONB, -- {name: 'old' -> 'new'}

  merged_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for contact merges
CREATE INDEX IF NOT EXISTS idx_contact_merges_tenant ON audit.contact_merges(tenant_id, merged_at DESC);
CREATE INDEX IF NOT EXISTS idx_contact_merges_source ON audit.contact_merges(source_contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_merges_target ON audit.contact_merges(target_contact_id);

COMMENT ON TABLE audit.contact_merges IS 'Full audit trail of all contact merges - enables reversal if needed';

-- Message Reassignments Audit
CREATE TABLE IF NOT EXISTS audit.message_reassignments (
  reassignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  merge_id UUID REFERENCES audit.contact_merges(merge_id),

  message_id UUID,
  old_contact_id UUID,
  new_contact_id UUID,

  reassigned_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for message reassignments
CREATE INDEX IF NOT EXISTS idx_message_reassignments_merge ON audit.message_reassignments(merge_id);
CREATE INDEX IF NOT EXISTS idx_message_reassignments_message ON audit.message_reassignments(message_id);

COMMENT ON TABLE audit.message_reassignments IS 'Tracks which messages moved during contact merges';
