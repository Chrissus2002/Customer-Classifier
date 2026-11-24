<!-- molds
id: dialo-1
stage: design
resume_stage:
parent: 
deps: 
priority: P1
created_at: 2026-04-11T08:53:02Z
updated_at: 2026-04-11T08:53:02Z
closed_at:
defer_until:
code_branch:
-->

# QA fixes for mold-5 and mold-6 implementations

## Problem

Mold-5 (Streamlit backfill UI + resume) and mold-6 (DB-driven classifier configs + editor) were implemented and archived across commits `2cf5ac9..09ea47f` (20 commits, 27 files, +2477/-2821 lines). The architecture is sound and matches the specs well, but a QA pass (manual code review + Codex second opinion + schema cross-checks) found **3 hard runtime bugs, 6 significant issues, and 8 minor issues**. None of this was caught because neither mold went through the formal `build -> qa -> merge -> closed` workflow — both were implemented and archived directly from `design`.

This mold collects all findings into a single remediation pass.

## Findings

### P0 — Hard runtime bugs (will crash or produce wrong results)

#### P0-1. Missing `silver.unique_contact_ids` view — crashes every classification run
`scripts/classifiers/orchestrator.py:228` queries `self.client.schema("silver").table("unique_contact_ids")` — this view does not exist in any schema file (`database/00` through `database/08`). Every call to `get_unclassified_contacts()` will crash with `relation "silver.unique_contact_ids" does not exist`. This blocks:
- The classifier worker (`scripts/classify_worker.py`)
- The "Reclassify stale contacts" button in Settings (`app/pages/2_Settings.py:170`)

**Fix**: Create the view in `database/03_silver_layer.sql`:
```sql
CREATE OR REPLACE VIEW silver.unique_contact_ids AS
SELECT contact_id, tenant_id, MAX(timestamp) AS timestamp
FROM silver.messages
GROUP BY contact_id, tenant_id;
```
Apply to live DB. Verify the orchestrator query returns results.

#### P0-2. `get_sync_progress_stats()` silently truncated at 1000 rows
`app/database.py:647-652` does a single `.execute()` with no pagination. Supabase's default row limit is 1000. For tenant YOUR_TENANT_ID with 8,668 contacts, the Home page progress bar will max out at ~11.5% even when fully synced. Compare with `get_synced_contact_ids()` at `:614-631` which correctly paginates.

**Fix**: Add the same pagination loop used in `get_synced_contact_ids()`. Or use a SQL `COUNT(*)` aggregate (which returns 1 row, no pagination needed):
```python
def get_sync_progress_stats(tenant_id):
    client = get_supabase_client()
    try:
        synced_resp = (
            client.schema("bronze").table("sync_progress")
            .select("wati_contact_id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("messages_synced", True)
            .limit(0)
            .execute()
        )
        total_resp = (
            client.schema("bronze").table("sync_progress")
            .select("wati_contact_id", count="exact")
            .eq("tenant_id", tenant_id)
            .limit(0)
            .execute()
        )
        synced = synced_resp.count or 0
        total = total_resp.count or 0
        return {"total_synced": synced, "total_failed": total - synced, "total": total}
    except Exception as e:
        return {"total_synced": 0, "total_failed": 0, "total": 0, "error": str(e)}
```

#### P0-3. Auth logout doesn't clear first-login session state
`app/auth.py:123-128` — the logout handler clears `authenticated`, `username`, `tenant_data`, `tenant_id` but does NOT clear `first_login`, `batch_import_contacts`, `batch_import_messages`, or `batch_imports_contacts_done` (set at `Home.py:90`). If a second user logs into the same Streamlit server session, they inherit the previous user's import-gate state — potentially skipping the first-login flow or re-triggering it incorrectly.

**Fix**: Clear all session state keys on logout, or at minimum add the missing keys:
```python
for key in ["first_login", "batch_import_contacts", "batch_import_messages", "batch_imports_contacts_done"]:
    st.session_state.pop(key, None)
```

### P1 — Significant issues (fix before GA)

#### P1-1. `create_import_job` creates in `running` state before subprocess launches
`app/database.py:292-294` creates the job with `status: "running"` immediately. If `subprocess.Popen` fails (wrong Python path, permission error, disk full), the job is stuck in `running` with no subprocess. The partial unique index `idx_import_jobs_one_running_per_tenant` then blocks ALL future job starts for that tenant.

**Fix**: Create with `status: "pending"`. Transition to `running` after `subprocess.Popen` succeeds and the PID is confirmed. Or catch Popen failures in `Home.py` and mark the job `failed` in the except branch.

#### P1-2. Double progress-counter overwrite in `insert_bronze_messages`
`app/database.py:446` — `insert_bronze_messages` calls `update_import_job(batch_id, {"processed_messages": inserted_count})` internally, writing the raw bronze row count. Meanwhile `batch_messages_import.py:299` calls `update_import_job(job_id, processed_messages=contacts_done)` tracking contacts-done count. These two writes race and stomp each other — the Home page progress metric jumps erratically.

**Fix**: Remove the `update_import_job` call inside `insert_bronze_messages`. Progress tracking belongs in the script's outer loop only. The same issue exists in `insert_bronze_contacts` at `:392`.

#### P1-3. `save_classifier_draft` allows saving zero stages
`app/database.py:848-861` — the function deletes all existing child stages, then only inserts new ones `if stages:`. An accidental save with an empty stage list silently wipes all stage definitions. The next classification run would use `_FALLBACK_STAGES` or crash.

**Fix**: Guard at the top: `if not stages: return "Cannot save with zero stages", False`.

#### P1-4. Seed script has no transaction wrapping
`scripts/seed_classifier_configs.py` inserts a `tenant_classifier_configs` row, then inserts child `tenant_journey_stages` rows as two separate DB calls. If the second insert fails (network blip, constraint violation), the tenant ends up with a config row but zero stages — classification runs in degraded fallback mode with no warning.

**Fix**: Wrap both inserts in a single SQL transaction via an RPC, or at minimum catch the second failure and delete the orphan config row.

#### P1-5. `get_contact_messages` ignores its `limit` parameter
`scripts/classifiers/orchestrator.py:63-72` — the `limit` parameter is declared but never passed to the query chain (no `.limit(limit)` call). Every classification loads ALL messages for a contact, which wastes tokens for contacts with 1000+ message histories.

**Fix**: Add `.limit(limit)` to the query chain.

#### P1-6. `get_stale_contact_count` does full Python-side table scan
`app/database.py:908-934` — fetches ALL `classifier_version` strings for the tenant into Python, then loops to parse and count. For 10k+ classified contacts this is slow and wasteful. Should be a SQL query with a LIKE filter or a view.

**Fix**: Use Supabase's `.not_.like("classifier_version", f"%/v{active_version}")` filter with `count="exact"` and `.limit(0)`.

### P2 — Minor issues

#### P2-1. README says `cd V2_wati_filippa` (line 62) — wrong repo name
Should be `cd dialo-cx`.

#### P2-2. Typos in README docs table (lines 285-296)
`"campign imports"`, `"estblish connection"`, `"batch_contacts_importer.py"` / `"batch_mesages_importer.py"` — filenames don't match actual scripts.

#### P2-3. Typo in Home.py UI text (line 111)
`"coupld of minutes"` → `"couple of minutes"`.

#### P2-4. Cancel flag files in `/tmp` never cleaned up after cancellation
`Home.py:75` creates `/tmp/dialo-cancel-{job_id}`. The subprocess deletes it on detection (`batch_messages_import.py:245`) — but if the subprocess dies before detecting the flag, the file persists forever. Low priority but worth a periodic cleanup or a `finally` block.

#### P2-5. `allowBroadcast: True` hardcoded in campaign CSV export
`app/pages/1_Journey_Analytics.py` — `build_campaign_csv()` always sets `allowBroadcast: True` and `allowSMS: True`. If a contact opted out in Wati, this CSV overrides the opt-out when re-imported. Compliance risk.

#### P2-6. Both mold-5 and mold-6 archived without formal closure
`.molds/archive/mold-5.md` and `.molds/archive/mold-6.md` both have `stage: design` and empty `closed_at:`. They were moved to `archive/` without going through `qa -> merge -> closed`. Not a code bug, but a workflow gap.

#### P2-7. AGENTS.md references deleted `plans/` files
`AGENTS.md` still references `plans/INDEX.md` and `v1_technical_design.md` in multiple places. Those files were deleted. Dead references for future agent sessions.

#### P2-8. `iterrows()` in Journey Analytics for activity counting
`app/pages/1_Journey_Analytics.py` — uses `iterrows()` for 7d/30d/90d cutoff counting. Should be vectorized pandas.

## Solution

Fix all P0 and P1 issues. Fix P2-1, P2-2, P2-3, P2-6, P2-7 (quick text fixes). Defer P2-4, P2-5, P2-8 as noted improvements.

## Files to Modify

| File | Action | Purpose | Done |
|------|--------|---------|------|
| `database/03_silver_layer.sql` | edit | Add `silver.unique_contact_ids` view (P0-1) | yes |
| `database/00_reset_database.sql` | edit | Add `DROP VIEW IF EXISTS silver.unique_contact_ids` (P0-1) | yes |
| `app/database.py` | edit | Fix `get_sync_progress_stats` pagination (P0-2). Remove `update_import_job` from `insert_bronze_messages` and `insert_bronze_contacts` (P1-2). Guard zero stages in `save_classifier_draft` (P1-3). Optimize `get_stale_contact_count` (P1-6). Fix `create_import_job` to use `pending` status (P1-1). | yes |
| `app/auth.py` | edit | Clear first-login session state on logout (P0-3) | yes |
| `scripts/classifiers/orchestrator.py` | edit | Add `.limit(limit)` to `get_contact_messages` (P1-5) | yes |
| `scripts/seed_classifier_configs.py` | edit | Add transaction wrapping or orphan-config cleanup (P1-4) | yes |
| `app/Home.py` | edit | Handle `pending -> running` transition after Popen (P1-1). Fix typo "coupld" (P2-3). | yes |
| `README.md` | edit | Fix repo name `V2_wati_filippa` -> `dialo-cx` (P2-1). Fix docs table typos (P2-2). | yes |
| `AGENTS.md` | edit | Remove dead `plans/` references (P2-7). | yes |
| `.molds/archive/mold-5.md` | edit | Set `stage: closed`, `closed_at` timestamp (P2-6) | yes |
| `.molds/archive/mold-6.md` | edit | Set `stage: closed`, `closed_at` timestamp (P2-6) | yes |

## Verification

### V1. `unique_contact_ids` view works
```sql
SELECT COUNT(*) FROM silver.unique_contact_ids WHERE tenant_id = YOUR_TENANT_ID;
-- Should return ~8668 (one per contact with messages)
```
Then run: `python scripts/classify_worker.py --tenant-id YOUR_TENANT_ID --limit 1 --dry-run`
— should print candidate count without crashing.

### V2. Progress bar is correct for large tenants
Manually verify: `get_sync_progress_stats(YOUR_TENANT_ID)` returns `total_synced` > 1000 (matching the actual count in `bronze.sync_progress`). Compare with:
```sql
SELECT COUNT(*) FROM bronze.sync_progress WHERE tenant_id = YOUR_TENANT_ID AND messages_synced = TRUE;
```

### V3. Logout clears session state
1. Log in as tenant YOUR_TENANT_ID
2. Run contact import (sets `batch_imports_contacts_done = True`)
3. Log out
4. Log in as a different tenant (or same tenant)
5. Verify the first-login gate appears again (not bypassed by stale state)

### V4. Failed subprocess doesn't permanently block tenant
1. Temporarily break the Python path in `_start_backfill` (e.g., point to nonexistent file)
2. Click "Start message backfill"
3. Verify the job is NOT stuck in `running` — it should be `failed` or `pending`
4. Fix the path, click Start again — should work

### V5. Progress counter doesn't jump
1. Start a backfill with `--limit 20`
2. Watch the Home page progress counter (`processed_messages`)
3. Should increment monotonically by 1 per contact, not jump to bronze row counts

### V6. Zero-stage draft is rejected
1. Open Settings > Classifier Configuration
2. Create a draft, delete all stages, click "Save draft"
3. Should see an error, not a successful save

### V7. `get_contact_messages` respects limit
In a Python shell:
```python
orchestrator.get_contact_messages("<contact_id>", limit=5)
# Should return at most 5 messages
```

## Implementation Notes

- **P0-1 is the critical path.** Without the view, no classification run can work. Fix this first, apply to live DB, verify with V1.
- **P0-2 has two valid fixes**: pagination loop (consistent with existing patterns) or `count="exact"` aggregate (cleaner, zero pagination needed). Recommend the aggregate approach.
- **P1-1 has a subtlety**: if we create the job as `pending`, the partial unique index `idx_import_jobs_one_running_per_tenant` only blocks on `running` — so `pending` jobs won't block new starts. We need to either extend the index to include `pending`, or handle it in the application logic (check for `pending OR running` before inserting).
- **P1-2 is load-bearing for the Home page UX.** The progress counter is what the user stares at during a 2-hour backfill. If it jumps around, they lose trust in the system.
- **Ordering**: P0-1 (schema) -> P0-2 + P0-3 (quick fixes) -> P1-1 + P1-2 (backfill UX) -> P1-3..P1-6 -> P2 text fixes.
- **Testing on schipperinc**: After fixes, pull the updated repo on schipperinc, apply the schema change, and run the classifier worker against tenant YOUR_TENANT_ID to verify the full pipeline end-to-end.

