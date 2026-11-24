-- =====================================================================
-- File: database/02_bronze_layer.sql
-- Purpose: Bronze Layer - Raw Data Storage
-- Store all raw data forever. Keep duplicate records across batch syncs.
-- Never delete from bronze.
-- =====================================================================

-- Create bronze schema
CREATE SCHEMA IF NOT EXISTS bronze;

-- =====================================================================
-- BRONZE TABLES
-- =====================================================================

-- Bronze: Wati Contacts
CREATE TABLE IF NOT EXISTS bronze.wati_contacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),

  wati_contact_id TEXT,
  raw_data JSONB NOT NULL, -- full API response

  batch_id UUID, -- if from batch import
  synced_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: one contact per tenant (allows upsert on duplicate imports)
  CONSTRAINT wati_contacts_tenant_contact_key UNIQUE(tenant_id, wati_contact_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bronze_wati_contacts_tenant ON bronze.wati_contacts(tenant_id, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_bronze_wati_contacts_batch ON bronze.wati_contacts(batch_id) WHERE batch_id IS NOT NULL;

COMMENT ON TABLE bronze.wati_contacts IS 'Raw contact data from Wati API. Stores duplicates across syncs.';
COMMENT ON COLUMN bronze.wati_contacts.raw_data IS 'Full API response payload from Wati';
COMMENT ON COLUMN bronze.wati_contacts.batch_id IS 'Links to import_jobs table if from batch import';

-- Bronze: Wati Messages
CREATE TABLE IF NOT EXISTS bronze.wati_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),

  wati_contact_id TEXT,
  wati_message_id TEXT NOT NULL,
  -- Wati's /getMessages API doesn't always include conversationId (~4% of
  -- messages in production data omit it). The webhook trigger already
  -- coalesces to 'Conversation had no ID'; the DEFAULT here matches that
  -- behavior so batch imports and direct inserts don't hit the NOT NULL.
  conversation_id TEXT NOT NULL DEFAULT 'Conversation had no ID',
  raw_data JSONB NOT NULL, -- full webhook/API payload

  batch_id UUID, -- if from batch import
  synced_at TIMESTAMPTZ DEFAULT NOW(),

  -- Unique constraint: one message per tenant (prevents duplicate message processing)
  CONSTRAINT wati_messages_unique UNIQUE(tenant_id, wati_message_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_bronze_wati_messages_tenant ON bronze.wati_messages(tenant_id, synced_at DESC);
CREATE INDEX IF NOT EXISTS idx_bronze_wati_messages_batch ON bronze.wati_messages(batch_id) WHERE batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bronze_wati_messages_contact ON bronze.wati_messages(tenant_id, wati_contact_id);
CREATE INDEX IF NOT EXISTS idx_bronze_wati_messages_conversation ON bronze.wati_messages(tenant_id, conversation_id);

COMMENT ON TABLE bronze.wati_messages IS 'Raw message data from Wati webhooks and API. Stores duplicates across syncs.';
COMMENT ON COLUMN bronze.wati_messages.raw_data IS 'Full webhook/API payload from Wati';
COMMENT ON COLUMN bronze.wati_messages.batch_id IS 'Links to import_jobs table if from batch import';

-- =====================================================================
-- IMPORT JOBS TABLE
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.import_jobs (
  job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),

  -- Job status
  status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'running', 'paused', 'failed', 'completed'

  -- Progress tracking
  total_messages INTEGER DEFAULT 0,
  processed_messages INTEGER DEFAULT 0,
  last_cursor TEXT, -- API pagination cursor for resumability

  -- Configuration
  start_date DATE,
  end_date DATE,

  -- Error tracking
  error_message TEXT,
  error_details JSONB,

  -- Timestamps
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_import_jobs_tenant ON public.import_jobs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON public.import_jobs(status) WHERE status IN ('running', 'paused');

-- Subprocess tracking (mold-5: Streamlit-launched backfill)
ALTER TABLE public.import_jobs ADD COLUMN IF NOT EXISTS subprocess_pid INTEGER;
ALTER TABLE public.import_jobs ADD COLUMN IF NOT EXISTS log_path TEXT;

-- Concurrency guard: at most one running job per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_import_jobs_one_running_per_tenant
  ON public.import_jobs (tenant_id)
  WHERE status = 'running';

COMMENT ON TABLE public.import_jobs IS 'Tracks batch import progress for resumability';
COMMENT ON COLUMN public.import_jobs.last_cursor IS 'API pagination cursor - allows resuming from failure point';
COMMENT ON COLUMN public.import_jobs.status IS 'Job status: pending, running, paused, failed, completed, cancelled';
COMMENT ON COLUMN public.import_jobs.subprocess_pid IS 'PID of the background subprocess (if launched by Streamlit)';
COMMENT ON COLUMN public.import_jobs.log_path IS 'Path to the log file for this job run';

-- =====================================================================
-- DAEMON TASK RUNS TABLE
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.daemon_task_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  task_name TEXT NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'daemon', -- daemon, manual
  status TEXT NOT NULL,                   -- running, success, error, skipped
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  duration_ms INTEGER,
  result JSONB,
  error_message TEXT,
  notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_daemon_task_runs_tenant_task_started
  ON public.daemon_task_runs(tenant_id, task_name, started_at DESC);

COMMENT ON TABLE public.daemon_task_runs IS 'Execution history for resident daemon tasks and manual task runs';
COMMENT ON COLUMN public.daemon_task_runs.trigger IS 'Execution source: daemon loop or manual run-once invocation';
COMMENT ON COLUMN public.daemon_task_runs.status IS 'Task outcome: running, success, error, or skipped';
COMMENT ON COLUMN public.daemon_task_runs.result IS 'JSON payload written by the task implementation';

-- =====================================================================
-- SYNC PROGRESS TABLE (mold-5: resumable per-contact backfill)
-- =====================================================================

CREATE TABLE IF NOT EXISTS bronze.sync_progress (
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  wati_contact_id TEXT NOT NULL,
  messages_synced BOOLEAN NOT NULL DEFAULT FALSE,
  message_count INTEGER DEFAULT 0,
  error_message TEXT,
  synced_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (tenant_id, wati_contact_id)
);

CREATE INDEX IF NOT EXISTS idx_sync_progress_unsynced
  ON bronze.sync_progress(tenant_id, messages_synced)
  WHERE messages_synced = FALSE;

GRANT ALL ON bronze.sync_progress TO authenticated, service_role;

COMMENT ON TABLE bronze.sync_progress IS 'Per-contact resume tracker for batch message backfill. One row per (tenant, contact). Upserted after each contact completes.';
