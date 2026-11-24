<!-- molds
id: dialo-2
stage: build
resume_stage: 
parent: 
deps: 
priority: P1
created_at: 2026-04-15T05:50:21Z
updated_at: 2026-04-15T05:57:19Z
closed_at: 
defer_until: 
code_branch: 
-->


# Deploy mold-5/6/v2-1 to schipperinc and run first classification

## TL;DR

schipperinc is 25 commits behind main. The live DB is missing 4 tables, 1 view, 1 function, and 6 columns. Apply schema, pull code, seed classifier config, restart Streamlit, run the classifier on a sample, then full run. End state: 8,884 contacts classified, UI fully functional.

## Problem

The code in git (main at `2b79651`) has landed mold-5 (backfill UI + resume), mold-6 (classifier config editor), v2-1 (QA fixes), plus 4 more bug-fix commits. But schipperinc is stuck at `7d2226f` from April 8. The live Supabase DB is missing the schema objects these features need. The classifier has never run against clean data — `silver.journey_intent_results` has 0 rows.

**Live DB state (tenant 310131 "Filippa dev"):**
- bronze: 9,224 contacts, 153,539 messages — complete
- silver: 8,884 contacts, 153,362 messages — complete
- silver.journey_intent_results: **0 rows** — cleared after direction fix on Apr 8, never re-run
- gold.contact_activity: 8,884 rows — working but no journey stages

**Missing schema objects:**
- `public.tenant_classifier_configs` — mold-6 table
- `public.tenant_journey_stages` — mold-6 table
- `bronze.sync_progress` — mold-5 table
- `silver.unique_contact_ids` — v2-1 view
- `public.activate_classifier_config()` — mold-6 function
- `public.import_jobs` columns: `subprocess_pid INTEGER`, `log_path TEXT`
- `public.tenants` columns: `first_login BOOLEAN`, `batch_import_contacts_done BOOLEAN`, `batch_import_messages_done BOOLEAN`, `classify_since_date DATE`

**Old table to drop:** `public.tenant_journey_configs` (replaced by the new pair, 0 rows in live DB).

## Solution

A sequential deploy with 7 phases. No rollback needed — every step is additive (new tables/columns/views) or idempotent (CREATE IF NOT EXISTS, CREATE OR REPLACE). Total time: ~30 min for deploy + ~2 hours for full classification.

### Phase 1 — Apply schema changes to live DB

Run via psql against the live Postgres (inside the Docker container or via the connection string). Apply in this exact order (dependency chain):

```sql
-- 1a. ALTER public.tenants (add 4 columns)
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS first_login BOOLEAN DEFAULT TRUE;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS batch_import_contacts_done BOOLEAN DEFAULT FALSE;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS batch_import_messages_done BOOLEAN DEFAULT FALSE;
ALTER TABLE public.tenants ADD COLUMN IF NOT EXISTS classify_since_date DATE;

-- 1b. ALTER public.import_jobs (add 2 columns)
ALTER TABLE public.import_jobs ADD COLUMN IF NOT EXISTS subprocess_pid INTEGER;
ALTER TABLE public.import_jobs ADD COLUMN IF NOT EXISTS log_path TEXT;

-- 1c. Partial unique index for one running job per tenant
CREATE UNIQUE INDEX IF NOT EXISTS idx_import_jobs_one_running_per_tenant
  ON public.import_jobs(tenant_id) WHERE status = 'running';

-- 1d. CREATE bronze.sync_progress
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
  ON bronze.sync_progress(tenant_id, messages_synced) WHERE messages_synced = FALSE;
GRANT ALL ON bronze.sync_progress TO authenticated, service_role;

-- 1e. CREATE public.tenant_classifier_configs (BEFORE stages — FK target)
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
CREATE UNIQUE INDEX IF NOT EXISTS tenant_classifier_configs_one_active_per_tenant
  ON public.tenant_classifier_configs(tenant_id) WHERE is_active;
ALTER TABLE public.tenant_classifier_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_classifier_configs_tenant_isolation
  ON public.tenant_classifier_configs FOR ALL
  USING (tenant_id = current_setting('app.tenant_id', true)::BIGINT)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::BIGINT);

-- 1f. CREATE public.tenant_journey_stages (depends on 1e)
CREATE TABLE IF NOT EXISTS public.tenant_journey_stages (
  stage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  config_id UUID NOT NULL REFERENCES public.tenant_classifier_configs(config_id) ON DELETE CASCADE,
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  stage_name TEXT NOT NULL,
  stage_description TEXT NOT NULL,
  display_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(config_id, stage_name)
);
CREATE INDEX IF NOT EXISTS idx_journey_stages_config
  ON public.tenant_journey_stages(config_id, display_order);
ALTER TABLE public.tenant_journey_stages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_journey_stages_tenant_isolation
  ON public.tenant_journey_stages FOR ALL
  USING (tenant_id = current_setting('app.tenant_id', true)::BIGINT)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::BIGINT);

-- 1g. CREATE VIEW silver.unique_contact_ids
DROP VIEW IF EXISTS silver.unique_contact_ids CASCADE;
CREATE VIEW silver.unique_contact_ids AS
SELECT contact_id, tenant_id, MAX(timestamp) AS timestamp
FROM silver.messages
GROUP BY contact_id, tenant_id;

-- 1h. CREATE FUNCTION public.activate_classifier_config
CREATE OR REPLACE FUNCTION public.activate_classifier_config(
  p_tenant_id BIGINT, p_config_id UUID
) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE public.tenant_classifier_configs
    SET is_active = false, activated_at = NULL
    WHERE tenant_id = p_tenant_id AND is_active = true;
  UPDATE public.tenant_classifier_configs
    SET is_active = true, activated_at = NOW()
    WHERE config_id = p_config_id AND tenant_id = p_tenant_id;
END;
$$;

-- 1i. GRANTs for new public tables
GRANT ALL ON public.tenant_classifier_configs TO authenticated, service_role;
GRANT ALL ON public.tenant_journey_stages TO authenticated, service_role;

-- 1j. DROP old table (verify empty first)
-- SELECT COUNT(*) FROM public.tenant_journey_configs;  -- should be 0
DROP TABLE IF EXISTS public.tenant_journey_configs CASCADE;

-- 1k. Set first_login=FALSE for existing tenant (already onboarded)
UPDATE public.tenants SET first_login = FALSE, batch_import_contacts_done = TRUE, batch_import_messages_done = TRUE WHERE tenant_id = 310131;
```

### Phase 2 — Reload PostgREST schema cache

PostgREST caches the DB schema. After adding tables/views, the cache must be refreshed or API calls will return `PGRST205 table not found`.

```bash
# Send SIGUSR1 to the PostgREST container to reload schema
sudo -u schipperinc bash -lc 'docker kill --signal=SIGUSR1 $(docker ps -qf "name=rest")'
```

If that doesn't work (rootless Docker), restart the rest container:
```bash
sudo -u schipperinc bash -lc 'cd ~/supabase-live && docker compose restart rest'
```

### Phase 3 — Pull code + install deps on schipperinc

```bash
sudo -u schipperinc bash -lc '
  cd ~/dialo-cx &&
  git pull &&
  .venv/bin/pip install -q streamlit-autorefresh &&
  echo "Done — $(git log --oneline -1)"
'
```

### Phase 4 — Seed classifier config v1

```bash
sudo -u schipperinc bash -lc '
  cd ~/dialo-cx &&
  .venv/bin/python scripts/seed_classifier_configs.py
'
```

This inserts a `tenant_classifier_configs` row (v1, is_active=TRUE) and 8 `tenant_journey_stages` rows for tenant 310131. The master prompt is the same `_PROMPT_CORE` text we wrote on April 8, now inlined in the seed script as `SEED_MASTER_PROMPT`. Idempotent — skips if config already exists.

### Phase 5 — Restart Streamlit

```bash
sudo -u schipperinc bash -lc 'systemctl --user restart dialo-streamlit.service' 2>/dev/null ||
  sudo -u schipperinc bash -lc 'kill $(pgrep -u schipperinc streamlit) && cd ~/dialo-cx && nohup .venv/bin/streamlit run app/Home.py --server.port 58501 --server.address 127.0.0.1 > ~/logs/streamlit.log 2>&1 &'
```

### Phase 6 — Classify a sample (20 contacts)

```bash
sudo -u schipperinc bash -lc '
  cd ~/dialo-cx &&
  PYTHONUNBUFFERED=1 .venv/bin/python scripts/classify_worker.py --tenant-id 310131 --limit 20
'
```

Review the output — check:
- No crashes (the `unique_contact_ids` view works)
- Stage distribution looks reasonable (not all `browsing`)
- Confidence values are in 0.0-1.0 range
- `classifier_version` includes `v1`

### Phase 7 — Full classification run (background)

```bash
sudo -u schipperinc bash -lc '
  cd ~/dialo-cx &&
  PYTHONUNBUFFERED=1 nohup .venv/bin/python scripts/classify_worker.py --tenant-id 310131 > ~/logs/classify-310131-$(date +%s).log 2>&1 &
  echo "PID: $!"
'
```

Expected: ~8,884 contacts, ~2 hours, ~$3-5 in DeepSeek API costs. After completion, `silver.journey_intent_results` has 8,884 rows and `gold.contact_activity` shows `current_journey_stage` populated.

## Files to Modify

No code changes needed — this is a deployment mold. All changes are infrastructure/DB operations.

| Action | Target | Purpose |
|--------|--------|---------|
| SQL apply | Live Supabase DB | Phase 1: add 4 tables, 1 view, 1 function, 8 columns, drop 1 old table |
| PostgREST reload | `rest` container | Phase 2: refresh schema cache |
| `git pull` | `/home/schipperinc/dialo-cx` | Phase 3: bring code to main HEAD |
| `pip install` | schipperinc `.venv` | Phase 3: add `streamlit-autorefresh` |
| Script run | `seed_classifier_configs.py` | Phase 4: create v1 config for tenant 310131 |
| Service restart | Streamlit process | Phase 5: load new code |
| Script run | `classify_worker.py --limit 20` | Phase 6: sample validation |
| Script run | `classify_worker.py` (full) | Phase 7: background full run |

## Verification

### V1. Schema objects exist after Phase 1
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name IN ('tenant_classifier_configs', 'tenant_journey_stages');
-- Should return 2 rows

SELECT table_name FROM information_schema.tables
WHERE table_schema = 'bronze' AND table_name = 'sync_progress';
-- Should return 1 row

SELECT viewname FROM pg_views WHERE schemaname = 'silver' AND viewname = 'unique_contact_ids';
-- Should return 1 row

SELECT proname FROM pg_proc WHERE proname = 'activate_classifier_config';
-- Should return 1 row
```

### V2. PostgREST can see new tables
```bash
curl -s http://127.0.0.1:58000/rest/v1/tenant_classifier_configs?select=config_id&limit=0 \
  -H "apikey: $SUPABASE_ANON_KEY" | head
# Should return [] (empty array), NOT a PGRST205 error
```

### V3. Seed script wrote config v1
```sql
SELECT tenant_id, version, is_active, length(master_prompt) AS prompt_len
FROM public.tenant_classifier_configs WHERE tenant_id = 310131;
-- Should return: 310131, 1, true, ~2500

SELECT stage_name, display_order FROM public.tenant_journey_stages
WHERE config_id = (SELECT config_id FROM tenant_classifier_configs WHERE tenant_id = 310131 AND is_active)
ORDER BY display_order;
-- Should return 8 stages
```

### V4. Streamlit loads without errors
Open `https://dialo.filippashop.com` in a browser. Verify:
- Login works for tenant 310131
- Home page shows contacts synced count
- Settings page shows "Active: v1" banner
- No Python tracebacks in the UI

### V5. Sample classification produces sane results
After Phase 6 (20 contacts):
```sql
SELECT journey_stage, COUNT(*), ROUND(AVG(confidence)::numeric, 2)
FROM silver.journey_intent_results
WHERE tenant_id = 310131
GROUP BY journey_stage ORDER BY count DESC;
```
- At least 2-3 different stages should appear
- Average confidence should be > 0.5
- `classifier_version` should contain `v1`
- No stage should be outside the valid 8 labels

### V6. Full run completes
After Phase 7:
```sql
SELECT COUNT(*) FROM silver.journey_intent_results WHERE tenant_id = 310131;
-- Should be close to 8884

SELECT journey_stage, COUNT(*) FROM silver.journey_intent_results
WHERE tenant_id = 310131 GROUP BY journey_stage ORDER BY count DESC;
-- Distribution should show no_customer_activity as largest bucket (broadcasts)
```

### V7. UI reflects classified data
After the full run, refresh Journey Analytics:
- Pie chart shows stage distribution
- Contact counts per stage are non-zero
- Campaign CSV export buttons produce CSVs with real data
- Settings page "stale contacts" count is 0

## Implementation Notes

- **Phase 1 is one atomic SQL script.** Combine all statements into a single file, pipe to psql. If any statement fails, the rest still run because each uses `IF NOT EXISTS` / `IF EXISTS`. No transaction wrapper needed.
- **Phase 2 is easy to forget** and causes confusing "table not found" errors from PostgREST. Do it immediately after the SQL apply. If in doubt, restart the entire `rest` container.
- **Phase 4 ordering matters.** The seed script must run AFTER Phase 1 (tables exist) and AFTER Phase 3 (code is pulled — the seed script uses the latest `SEED_MASTER_PROMPT` constant).
- **Phase 6 before Phase 7.** Never run the full 8,884-contact classification without validating on 20 first. A prompt bug at scale costs $5+ in wasted API calls and 2 hours.
- **`classify_since_date`** is not in `01_tenants.sql` — this is a schema drift Christian introduced. The ALTER TABLE in Phase 1 covers the live DB. Someone should also update `01_tenants.sql` to include the column, but that's a code fix, not a deploy step.
- **`first_login = FALSE` for tenant 310131** (step 1k) is critical. Without it, the Home page will force a contact re-import on next login — unnecessary since contacts are already loaded.
- **Rollback is trivial.** Drop the new tables, drop the view, drop the function, drop the columns. Nothing in the existing data is modified. But we won't need to roll back — every step is additive.
- **Webhook is unaffected.** The wati-webhook edge function runs independently and doesn't touch any of the new tables. Existing webhook message flow continues throughout the deploy.


