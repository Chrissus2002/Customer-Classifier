<!-- molds
id: mold-6
stage: closed
resume_stage:
parent:
deps:
priority: P2
created_at: 2026-04-08T19:45:01Z
updated_at: 2026-04-11T00:00:00Z
closed_at: 2026-04-11T00:00:00Z
defer_until:
code_branch:
-->

# Editable classifier prompts and journey stages per tenant

## Problem

Today the classifier prompt and journey stages are half-hardcoded, half-wired-up, and the half that's in the database is ignored. Changing how a tenant's customers get classified means editing Python, opening a PR, deploying, and restarting Streamlit. That's fine for one tenant in R&D mode. It is not fine for a multi-tenant product where each brand wants its own journey definitions (a wholesale-first apparel brand and a subscription-box brand should not share "product_evaluation" semantics).

**What is actually hardcoded:**

| Layer | Where | Status |
|---|---|---|
| Master classifier prompt | `scripts/classifiers/orchestrator.py:9-63` — the `_PROMPT_CORE` constant + the double-prompt wrapper at `:69-76` | Hardcoded Python module constant. Not per-tenant. Not in DB. |
| Journey stages list | `public.tenant_journey_configs` table already exists with `stage_name`, `stage_description`, `prompt_template`, `display_order`, `version`, `is_active` (see `database/03_silver_layer.sql:127-145`). Orchestrator reads names at `orchestrator.py:104-129` | Table exists but `stage_description` and `prompt_template` columns are NEVER read. Only stage names are used. |
| Per-stage descriptions | Inlined into the `_PROMPT_CORE` string as bullet points ("browsing: Cliente explora catálogo…", etc.) | Hardcoded inside the master prompt, even though the DB column `stage_description` exists to hold them. |
| Default stages fallback | `orchestrator.py:121-126` | Hardcoded list, used only when the DB table is empty. |

**What already exists and is wasted:**

- `public.tenant_journey_configs.prompt_template` — column exists, never read.
- `public.tenant_journey_configs.stage_description` — column exists, never read.
- `public.tenant_journey_configs.version` — column exists, schema comment at `database/03_silver_layer.sql:152` says "Incremented when stages are modified - tracks classifier changes", but nothing ever bumps it.
- `silver.journey_intent_results.classifier_version` — column exists, populated at `orchestrator.py:179` via `self.classifier.build_classifier_version(version)`. The audit trail is already wired — we just never produce new versions to audit.
- `public.tenants.default_journey_stages TEXT[]` — column exists at `database/01_tenants.sql:19`, never populated.

**Why this blocks the product:**

1. Non-technical users (the intended tenant admins) cannot change any classification behavior without a developer.
2. Every tenant classifies with the same Spanish-apparel-specific prompt, which will produce nonsense for any tenant that isn't a Spanish apparel brand.
3. A/B testing prompt iterations is impossible — there's no way to run two versions in parallel and compare outputs.
4. Historical analysis is broken-by-design: even though `classifier_version` exists, it never changes, so you cannot say "everyone classified before 2026-04-01 used a worse prompt".
5. Prompt improvements (like today's `no_customer_activity` addition) require a git commit, a deploy, and a full reclassification run, all triggered by SSH.

## Solution

**Replace the broken half-wired schema, wire up the orchestrator to DB, and put a UI on it.** Five parts:

### Part A — Schema: drop `tenant_journey_configs`, add clean replacement pair

Drop the existing `tenant_journey_configs` table entirely (it has no production rows, its `stage_description` and `prompt_template` columns were never read, and its per-row `version` semantics are broken). Replace with two tables:

```sql
-- 1. Master classifier config (per-tenant, per-version)
CREATE TABLE public.tenant_classifier_configs (
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
CREATE UNIQUE INDEX tenant_classifier_configs_one_active_per_tenant
  ON public.tenant_classifier_configs(tenant_id) WHERE is_active;

-- 2. Journey stages (child of a config version)
CREATE TABLE public.tenant_journey_stages (
  stage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  config_id UUID NOT NULL REFERENCES public.tenant_classifier_configs(config_id) ON DELETE CASCADE,
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  stage_name TEXT NOT NULL,
  stage_description TEXT NOT NULL,
  display_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(config_id, stage_name)
);
CREATE INDEX idx_journey_stages_config ON public.tenant_journey_stages(config_id, display_order);

-- RLS: both tables are tenant-scoped
ALTER TABLE public.tenant_classifier_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_journey_stages ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_classifier_configs_tenant_isolation ON public.tenant_classifier_configs
  USING (tenant_id = current_setting('app.tenant_id')::BIGINT);
CREATE POLICY tenant_journey_stages_tenant_isolation ON public.tenant_journey_stages
  USING (tenant_id = current_setting('app.tenant_id')::BIGINT);
```

The invariant: **one classifier version = one `tenant_classifier_configs` row + N `tenant_journey_stages` rows pointing at it**. Version is on the parent, shared by all child rows.

### Part B — Atomic activation RPC

Two sequential PostgREST calls (deactivate old → activate new) are not transactional. Add a Postgres function to `database/05_functions.sql`:

```sql
CREATE OR REPLACE FUNCTION activate_classifier_config(p_tenant_id BIGINT, p_config_id UUID)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  UPDATE public.tenant_classifier_configs
    SET is_active = false, activated_at = NULL
    WHERE tenant_id = p_tenant_id AND is_active = true;
  UPDATE public.tenant_classifier_configs
    SET is_active = true, activated_at = NOW()
    WHERE config_id = p_config_id AND tenant_id = p_tenant_id;
END;
$$;
```

Called via `client.rpc('activate_classifier_config', {...})` — same pattern as `process_messages_to_silver` at `app/database.py:471`.

### Part C — Orchestrator: compose prompt from DB + eliminate per-contact DB round trips

**Rewrite `get_tenant_stages()`** to return the full config needed for composition:

```python
def get_tenant_config(self, tenant_id: int) -> tuple[str, list[dict], int]:
    """
    Load the active classifier config for a tenant.
    Returns: (master_prompt, stages_list, version)
    stages_list = [{"stage_name": ..., "stage_description": ...}, ...]
    """
```

**Rewrite `classify_contact()` and `classify_and_store()`** to accept an optional pre-loaded `tenant_config` tuple:

```python
def classify_contact(self, tenant_id, contact_id, tenant_config=None, prompt=None):
    if tenant_config is None:
        tenant_config = self.get_tenant_config(tenant_id)
    master_prompt, stages, version = tenant_config
    # compose: master_prompt + stages bullets + labels + JSON format
    ...
```

**Fix `classify_worker.py`**: `classify_tenant()` already calls `get_tenant_stages()` at line 41 but discards the result. Change it to call `get_tenant_config()` once, then pass `tenant_config` into each `classify_contact_with_retry()` call. Eliminates N-1 DB round trips per batch — one query per tenant instead of one per contact.

**Prompt composition contract** (single place in orchestrator):
```
{master_prompt}

— — — (repeat separator) — — —

{master_prompt}

ETAPAS VÁLIDAS:
{for each stage: "• {stage_name}: {stage_description}"}

Valid labels: {comma-joined stage_names}
```

`_PROMPT_CORE` and `DEFAULT_PROMPT` are deleted from `orchestrator.py` — they become seed data in Part E.

**Version drift detection** in `get_unclassified_contacts()`: parse the `classifier_version` string (format `"provider/model/vN"`, confirmed from `tests/unit/test_classifiers.py:137`), extract the `vN` suffix, compare against current active config version. Add version-drift as a third staleness category alongside never-classified and new-inbound-messages.

### Part D — Streamlit editor UI (`app/pages/2_Settings.py`)

Add a "Classifier Configuration" section to the existing Settings page (below whatever is already there). Same auth pattern already in place. Layout:

- **Active version banner**: "Active: v1, activated 2026-04-09, N contacts classified with this version"
- **Draft editor** (shown if draft exists; otherwise "Create new draft from active" button):
  - `st.text_area` for master prompt (~30 rows, char counter, soft warning at 8 KB)
  - `st.data_editor` for stages: columns `display_order`, `stage_name` (read-only for existing stages), `stage_description`. Delete checkboxes and add-row support.
  - "Composed prompt preview" expander — renders exactly what the orchestrator will send
- **Actions row**:
  - "Save draft" — upserts draft `tenant_classifier_configs` row (`is_active=FALSE`)
  - "Test with 5 contacts" / "Test with 20 contacts" — calls `classify_contact()` directly with the draft prompt (no DB write). Uses stratified sampling across current stages; falls back to random. Shows new label + confidence + reasoning next to stored label. Shows estimated cost before running.
  - "Activate" — calls `activate_classifier_config` RPC. Enabled only after at least one test run.
  - "Discard draft" — hard-deletes the draft row (and child stages cascade).
- **Version history** table: last 10 versions, `version`, `created_at`, `activated_at`, `notes`, contact count classified, "Restore as new draft" button.
- **Stale contacts panel**: "N contacts classified with v1. Active is v2. [Reclassify all] — ~$X.XX estimated cost." Cost = `stale_count × 0.0003`. Clicking "Reclassify all" runs reclassification **in-process** (not a subprocess): iterate the stale contacts and call `classifier.classify_and_store(tenant_id, contact_id, tenant_config=active_config)` directly inside the Streamlit session with a `st.progress` bar. Reclassification volume is small (only contacts stale due to version drift, not a full backfill), so blocking the session is acceptable.

### Part E — Seed migration for existing tenants

Script `scripts/seed_classifier_configs.py`:

1. Import `_PROMPT_CORE` from `orchestrator.py` (run this **before** the orchestrator rewrite removes it).
2. For every active tenant in `public.tenants`:
   - If a `tenant_classifier_configs` row already exists, skip.
   - Insert v1 row with `master_prompt=_PROMPT_CORE`, `is_active=TRUE`.
   - Insert 8 child `tenant_journey_stages` rows with stage names and descriptions **hardcoded in the script** (copy-pasted from `_PROMPT_CORE` rather than parsed — parsing the Spanish free-text blob is fragile). The 8 stages and their descriptions are fixed at seed time:
     - `browsing`: "Cliente explora catálogo, saluda con interés genuino, hace preguntas generales"
     - `product_evaluation`: "Cliente pregunta sobre productos específicos (precio, talla, color, disponibilidad)"
     - `purchase_intent`: "Decisión de compra NUEVA — apartando, confirmando, discutiendo pago/envío"
     - `order_support`: "Pedido COMPLETADO — rastreo, tiempos de envío, devoluciones, quejas sobre pedidos"
     - `wholesale_inquiry`: "Cualquier mención de mayoreo/reventa"
     - `location_inquiry`: "Preguntas sobre tienda física"
     - `no_customer_activity`: "Conversación 100% outbound del negocio, cliente nunca ha respondido de forma significativa"
     - `spam_unrelated`: "Contenido del CLIENTE que es 100% no relacionado con el negocio"
3. Idempotent — second run is a no-op.

## Files to Modify
| File | Action | Purpose | Done |
|------|--------|---------|------|
| `database/03_silver_layer.sql` | edit | Drop `tenant_journey_configs`. Add `tenant_classifier_configs` + `tenant_journey_stages` tables, indexes, and RLS policies. | yes |
| `database/05_functions.sql` | edit | Add `activate_classifier_config(p_tenant_id, p_config_id)` RPC for atomic activation. | yes |
| `database/00_reset_database.sql` | edit | Add new tables to the DROP list; remove `tenant_journey_configs`. | yes |
| `scripts/classifiers/orchestrator.py` | edit | Delete `_PROMPT_CORE` + `DEFAULT_PROMPT`. Rename `get_tenant_stages()` → `get_tenant_config()` returning `(master_prompt, stages, version)`. Add optional `tenant_config` param to `classify_contact()` and `classify_and_store()`. Add version-drift staleness to `get_unclassified_contacts()`. | yes |
| `scripts/classify_worker.py` | edit | Call `get_tenant_config()` once per tenant run, pass result into each `classify_contact_with_retry()` call. | yes |
| `app/pages/2_Settings.py` | edit | Add "Classifier Configuration" section: draft editor, test/activate workflow, version history, stale contacts panel. | yes |
| `app/database.py` | edit | Helpers: `get_active_classifier_config(tenant_id)`, `get_draft_classifier_config(tenant_id)`, `save_classifier_draft(tenant_id, master_prompt, stages, notes)`, `activate_classifier_config(tenant_id, config_id)`, `get_classifier_version_history(tenant_id)`, `get_stale_contact_count(tenant_id)`. | yes |
| `scripts/seed_classifier_configs.py` | **new** | Seed v1 rows for existing tenants from the current hardcoded prompt. Run before orchestrator rewrite. | yes |
| `tests/unit/test_orchestrator_prompt_composition.py` | **new** | Unit tests: prompt composition from DB rows, version-drift detection. | yes |

**Files NOT to modify:**
- `scripts/classifiers/llm_apis.py` — LLM API wrappers are prompt-source-agnostic.
- `scripts/classifiers/base.py`, `scripts/classifiers/models.py` — no interface changes.

## Verification

### V1. Schema applies cleanly
```sql
\d public.tenant_classifier_configs   -- 9 cols, PK, unique active index
\d public.tenant_journey_stages       -- config_id FK, CASCADE delete
-- tenant_journey_configs must not exist
SELECT to_regclass('public.tenant_journey_configs');  -- returns NULL
```

### V2. Seed migration writes v1 correctly
```bash
python scripts/seed_classifier_configs.py
# For tenant YOUR_TENANT_ID:
# - 1 row in tenant_classifier_configs (version=1, is_active=TRUE)
# - 8 rows in tenant_journey_stages all with that config_id
# - master_prompt matches _PROMPT_CORE exactly
```
Run twice — second run is a no-op.

### V3. Orchestrator composes same prompt as before
Before deleting `_PROMPT_CORE`, capture its composed form. After rewrite, load v1 from DB and compose. The string sent to the LLM must be identical.

### V4. No per-contact DB round trips for tenant config
Add a counter to `get_tenant_config()`. Run `classify_tenant()` with 10 contacts for tenant YOUR_TENANT_ID. Counter should increment exactly once regardless of contact count.

### V5. Classifier labels are stable
Pick 20 contacts from tenant YOUR_TENANT_ID. Run through new DB-driven orchestrator (v1). Compare to stored `silver.journey_intent_results` labels — must match >95%.

### V6. Editor UI — save, test, activate flow
1. Open `/2_Settings`, scroll to "Classifier Configuration"
2. Create draft from active
3. Edit master prompt, add stage "refund_request"
4. Save draft → row in DB with `is_active=FALSE`
5. Test with 5 contacts → results render without writing to journey_intent_results
6. Activate → RPC flips is_active atomically; partial index does not fire
7. Refresh → banner shows new version

### V7. Version drift triggers reclassification
1. With v1 active, classify 3 contacts (`classifier_version = "…/v1"`)
2. Activate v2
3. `get_unclassified_contacts(YOUR_TENANT_ID)` → 3 contacts appear as stale-due-to-version-drift

### V8. Atomic activation enforced
```sql
-- Two running updates against the same tenant — must not leave two active rows:
UPDATE tenant_classifier_configs SET is_active=TRUE WHERE tenant_id=YOUR_TENANT_ID AND version=2;
-- Should fail: Key (tenant_id)=(YOUR_TENANT_ID) already exists in partial unique index
```

### V9. Historical classifier_version preserved
```sql
SELECT classifier_version, COUNT(*) FROM silver.journey_intent_results WHERE tenant_id=YOUR_TENANT_ID GROUP BY 1;
```
Old strings untouched. New classifications use `"provider/model/vN"` format.

## Implementation Notes

- **Deployment order is strict**: (1) run seed script (while `_PROMPT_CORE` still exists in orchestrator.py), (2) apply schema migration (DROP journey_configs, CREATE new tables, add RPC), (3) deploy orchestrator + worker rewrite. Wrong order = crash. The seed script should fail fast with a clear error if `_PROMPT_CORE` is already gone.
- **`tenant_journey_configs` has no production rows** (confirmed by exploration agents). The DROP is safe. If any rows exist on the live DB before migration, the seed script should detect and migrate them.
- **`classify_worker.py:41`** currently calls `get_tenant_stages()` and discards the result — this is the bug to fix. Thread `tenant_config` all the way through `classify_contact_with_retry()` into `classify_and_store()`.
- **Test-drive uses `classify_contact()` directly** — it already accepts an optional `prompt` param and returns `ClassificationResult` without writing. No separate dry-run mechanism needed.
- **Stage name immutability policy**: stage names are read-only for existing stages across version history. Rename = forbidden (breaks gold layer analytics). Enforce in UI: `stage_name` column in data_editor is `disabled=True` for pre-existing stages. New rows allow free text.
- **Reclassification cost estimate**: $0.0003 per contact (2k input + 200 output tokens at DeepSeek pricing). Show in stale-contacts panel.
- **Prompt size**: soft warning at 8 KB (`len(prompt.encode()) > 8192`), hard cap at 20 KB enforced at save time.
- **Multi-tenant isolation**: editor page filters by `st.session_state.tenant_id`. RLS on both new tables provides DB-level isolation.
- **Not in scope**: A/B testing (two active configs in parallel), per-stage custom prompts, prompt linting, i18n.
- **Resolved design decisions**:
  - Permissions: flat (any logged-in tenant user can edit) — revisit when roles land
  - Draft deletion: hard-delete (CASCADE removes child stages automatically)
  - Activation trigger: user-initiated "Reclassify stale" button, not auto
  - Test sampler: stratified across current stages, random fallback
  - "Reclassify all" mechanism: in-process (blocks Streamlit session with `st.progress`). Volume is small enough — only contacts stale due to version drift.
  - Seed script stage descriptions: hardcoded strings in the script (not parsed from `_PROMPT_CORE`)
  - Draft identification: convention — `get_draft_classifier_config(tenant_id)` returns the most recently created `is_active=FALSE` row. No `is_draft` column needed. Only one draft is meaningful at a time; older inactive rows are history.

