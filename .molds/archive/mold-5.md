<!-- molds
id: mold-5
stage: closed
resume_stage:
parent:
deps:
priority: P2
created_at: 2026-04-08T08:02:11Z
updated_at: 2026-04-11T00:00:00Z
closed_at: 2026-04-11T00:00:00Z
defer_until:
code_branch:
-->

# Streamlit-launched batch imports with resumable progress

## Problem

The CLI batch import path works today (mold-4 landed on main 2026-04-08) but is unusable for anyone who isn't already SSH'd into the hosting box. Running a real backfill means:
- `ssh schipperinc@187.124.84.204`
- `cd ~/dialo-cx && PYTHONUNBUFFERED=1 .venv/bin/python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID`
- Babysit a 2.4-hour log tail
- If it crashes, restart from scratch (the bronze upsert is idempotent, but we still re-hit the Wati API for every already-completed contact — pure waste)

The multi-tenant product promise is that a tenant admin logs into `https://dialo.filippashop.com`, sees their data, and can operate their own brand. Backfill is the most common ops operation (every new tenant needs one, every "catch up after downtime" needs one). It shouldn't require server access.

Filippa's production ops almost certainly has the same pain point — filippa's legacy Streamlit app doesn't expose backfill either.

## Solution

**Architecture: Streamlit launches the existing CLI tool as a detached subprocess, polls Postgres for status.** (Option D from the pre-implementation design discussion with the user.)

Streamlit is a synchronous request/response framework with an aggressive rerun model — any long-running callback blocks the entire user's session. But Streamlit can cleanly *fire and forget* via `subprocess.Popen(..., start_new_session=True)`. That gives us:
- Instant feedback from the button click (subprocess launched in ~50ms)
- The subprocess runs under the same schipperinc user and inherits the same systemd slice caps (12 GiB RAM, 6 CPU, 4096 tasks)
- Subprocess survives Streamlit restart, browser close, or Streamlit crash
- Multiple users visiting the admin page see the same state (`public.import_jobs` is the shared source of truth)
- No new services, no job queue, no message broker

**Resume is the critical companion.** Once users can click a button, they will click it, walk away, close their laptop, come back, and expect things to have progressed. A 2.4-hour run without resume is a footgun — any network blip means starting over. Mold-4 deferred the resume table (`bronze.sync_progress`) to Phase 2; this mold brings Phase 2 in-scope and ships it together.

## Scope — four sub-deliverables

### 1. `bronze.sync_progress` resume table
Mirror `filippa/wati/local/local_sync.py:174-187`:
```sql
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
CREATE INDEX ON bronze.sync_progress(tenant_id, messages_synced) WHERE messages_synced = FALSE;
```
Add to `database/02_bronze_layer.sql`.

**Grants note:** `database/08_grants.sql`'s `ALTER DEFAULT PRIVILEGES` only covers tables created by the same role at grant-execution time. Add an explicit grant in `02_bronze_layer.sql` directly after the table definition:
```sql
GRANT ALL ON bronze.sync_progress TO authenticated, service_role;
```
This avoids needing to re-run `08_grants.sql` after every schema change.

### 2. `scripts/batch_messages_import.py` — resume + cancellation
- On startup, query `bronze.sync_progress` for the tenant, build a set of already-synced `wati_contact_id`s.
- Filter the `contacts_list` to exclude those already synced.
- After each contact's messages land in bronze **and** `process_messages_bronze_to_silver` completes, UPSERT a `sync_progress` row with `messages_synced=TRUE` and `message_count`. This ordering prevents the bronze-silver gap: a contact is only marked done once silver rows exist.
- On per-contact failure, upsert with `messages_synced=FALSE` and `error_message=<truncated>`. Continue to next contact.
- **Accumulating progress counter**: maintain a running total `contacts_done` in the main loop and call `update_import_job(job_id, processed_messages=contacts_done)` after each contact. Do NOT rely on the count returned by `insert_bronze_messages` — it overwrites with the current contact's batch size, not the cumulative total.
- New `--no-resume` flag (resume is on by default). Use `--no-resume` to force re-fetch from scratch.
- Cancellation: poll a file at `/tmp/dialo-cancel-{job_id}` every 5 contacts inside the main `for` loop. If present, mark the `import_jobs` row `cancelled` and exit 0. The existing `KeyboardInterrupt` handler marks the job `failed` — leave it as-is for CLI use.
- Write PID into `public.import_jobs.subprocess_pid` at startup so Streamlit can verify liveness via `os.kill(pid, 0)`.
- Use `sys.executable` instead of a hardcoded `.venv/bin/python` path in the subprocess launcher — this works regardless of deployment location.

### 3. Streamlit backfill section — `app/Home.py`
The message backfill UI lives on `Home.py` (below the contact import section), not in a separate page. Layout section to add after the first-login contact import block:

- **Current job** panel:
  - If an `import_jobs` row with `status IN ('running', 'pending')` exists for this tenant:
    - Show started_at, processed_messages, estimated time remaining
    - "Stop" button that writes the cancel flag
    - Auto-refresh every 5 seconds
  - Else:
    - "Start message backfill" button
    - Optional "Test run (5 contacts)" button
- **Progress stats** (always visible, shown as metrics):
  - Total contacts in silver
  - Contacts with messages already backfilled (from `sync_progress WHERE messages_synced`)
  - % complete
- **Job history**: last 5 `import_jobs` rows with status and processed_messages in a collapsible expander

Subprocess launcher:
```python
import subprocess
import sys
from pathlib import Path

def start_backfill(tenant_id: int, job_id: str, limit: int | None = None, dry_run: bool = False):
    log_dir = Path.home() / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"backfill-{tenant_id}-{job_id}.log"

    cmd = [
        sys.executable,  # use current venv's python — works regardless of deployment path
        str(Path(__file__).parent.parent / "scripts" / "batch_messages_import.py"),
        "--tenant-id", str(tenant_id),
    ]
    if limit: cmd += ["--limit", str(limit)]
    if dry_run: cmd += ["--dry-run"]

    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid, str(log_path)
```

Auto-refresh: use `streamlit-autorefresh` package or `st.empty()` + `time.sleep()` + `st.rerun()` loop. streamlit-autorefresh is cleaner.

### 4. Observability
- Log files: `~/logs/backfill-{tenant_id}-{job_id}.log` — using `job_id` (UUID) makes log files directly linkable from the `import_jobs` DB row via `log_path`.
- `import_jobs` gets a new column `log_path TEXT` so the UI can link to the right file.
- `import_jobs` gets a new column `subprocess_pid INTEGER` for liveness checks.
- Log rotation: NOT in scope for this mold — accept that `~/logs/` grows linearly with runs. Could add a cron later.
- Streamlit shows the tail of the current log in an expander using `Path.read_text()[-8000:]` or similar.

## Files to Modify
| File | Action | Purpose | Done |
|------|--------|---------|------|
| `database/02_bronze_layer.sql` | edit | Add `bronze.sync_progress` table + index. Add `subprocess_pid` + `log_path` columns to `public.import_jobs`. Add partial unique index on `import_jobs(tenant_id) WHERE status='running'`. Add explicit GRANT on `bronze.sync_progress` to cover grants gap. | yes |
| `scripts/batch_messages_import.py` | edit | Resume logic, cancellation polling, PID write, `--no-resume` flag, accumulating `processed_messages` counter written per-contact | yes |
| `app/database.py` | edit | Helpers: `get_sync_progress_stats(tenant_id)`, `upsert_sync_progress(tenant_id, wati_contact_id, ...)`, `read_cancel_flag(job_id)`, `get_active_job(tenant_id)`, `get_import_jobs_by_tenant(tenant_id)` | yes |
| `app/Home.py` | edit | Remove blocking `on_click=run_imports` button. Add subprocess-based backfill section with progress stats, Start/Stop buttons, and job history expander. | yes |
| `requirements.txt` | edit | Add `streamlit-autorefresh` (~20 KB) | yes |

### Concurrency guard — `public.import_jobs`
Add a partial unique index to prevent two running jobs for the same tenant:
```sql
CREATE UNIQUE INDEX idx_import_jobs_one_running_per_tenant
  ON public.import_jobs (tenant_id)
  WHERE status = 'running';
```
`create_import_job()` will raise a unique violation if a running job already exists. The Streamlit page catches this and shows "A job is already running for this tenant." If a job is stuck in `running` due to a crash, the admin must mark it `failed` from the UI before starting a new one — this is intentional and visible recovery.

**Files NOT to modify** (per mold-4's lessons):
- `app/database.py:insert_bronze_messages` is already correct, just add NEW functions alongside it
- `database/05_functions.sql` — no changes to the bronze→silver functions
- `database/03_silver_layer.sql` — no silver schema changes
- `scripts/batch_messages_import.py:run_imports` — this function exists and is called directly from `Home.py` today. Do NOT modify it or call it from the new UI. The subprocess launcher calls the script via its CLI entry point (`if __name__ == "__main__"`), which is a separate path.

## Verification

### V1. bronze.sync_progress schema is correct
```
\d bronze.sync_progress
```
shows the 7 columns + PK + the partial index on unsynced rows.

### V2. `--no-resume` flag still runs from scratch
Run the backfill with `--no-resume --limit 3` twice against tenant YOUR_TENANT_ID. Both runs should process the same 3 contacts and hit the Wati API both times. `sync_progress` should still get updated.

### V3. Resume happens by default
Run the backfill with `--limit 3` once (no `--no-resume`). Then run again with `--limit 5`. The second run should SKIP the first 3 contacts and process only the next 2.

### V4. Streamlit button launches a subprocess that outlives Streamlit
1. Click "Start backfill" in the admin UI
2. Verify a new `import_jobs` row appears with `status='running'` and `subprocess_pid` populated
3. Kill Streamlit: `systemctl --user restart dialo-streamlit.service`
4. Wait 30 seconds
5. Check that the subprocess is still alive: `ps -p <pid>` shows it running
6. Check that `import_jobs.processed_messages` is still incrementing by querying Postgres directly
7. When Streamlit comes back up, the admin page should reflect the current live state

### V5. Cancellation works
1. Click "Start backfill" (no limit, full run)
2. Wait for `processed_messages` to reach 50+
3. Click "Stop"
4. Verify a file exists at `/tmp/dialo-cancel-{job_id}`
5. Within ~30 seconds the subprocess should exit with code 0
6. `import_jobs.status` should be `cancelled`
7. Re-clicking "Start" should resume from where we left off (thanks to sync_progress)

### V6. Live multi-user state
Open the admin page in two separate browser windows while a backfill is running. Both should show the same current state and update on their respective refresh intervals.

### V7. End-to-end full backfill via UI
1. Reset sync_progress for tenant YOUR_TENANT_ID: `DELETE FROM bronze.sync_progress WHERE tenant_id = YOUR_TENANT_ID`
2. Click "Start message backfill" (no limit) in the Streamlit UI
3. Walk away for 2.5 hours
4. Return — the job should be `completed`, with ~8668 sync_progress rows all `messages_synced=TRUE`, and hundreds of thousands of new bronze/silver messages for tenant YOUR_TENANT_ID
5. Click "Start" again — should immediately finish (all contacts already synced)

## Implementation Notes

- **Start with the schema change** — add `bronze.sync_progress` + the `import_jobs.subprocess_pid/log_path` columns first. Apply to live DB via `ALTER TABLE`. Schema-as-code contract: update the `.sql` file, then apply via `docker exec psql`.
- **Build the resume logic in `batch_messages_import.py` next** — it's the foundation. Test via CLI (no UI involved) before touching Streamlit.
- **Build the Streamlit section last** — add the backfill section to `Home.py` below the existing contact import block. Reuse patterns from the existing `Home.py` metric containers for layout consistency.
- **`get_import_jobs_by_tenant(tenant_id)`** is missing from `app/database.py` — there is no existing function to query job status by tenant, only create/update/complete/fail. Add it alongside the other new helpers. The Streamlit page needs it to poll the active job on every refresh cycle.
- **For streamlit-autorefresh**: the package is tiny (~20 KB). If the review wants to avoid a new dep, fall back to `time.sleep(5); st.rerun()` in a conditional loop — uglier but zero dependencies.
- **Cancellation flag location**: `/tmp/dialo-cancel-{job_id}` is deliberately ephemeral (cleared on reboot). Could also use a column in `import_jobs`, which survives restarts — slightly more work. Prefer the file approach for simplicity.
- **PID liveness check**: `os.kill(pid, 0)` raises `ProcessLookupError` if the process is dead. Simple way for Streamlit to tell a stale `running` state from a live one.
- **Test environment**: schipperinc VPS. Tenant YOUR_TENANT_ID (filippa-dev) with its 8,668 contacts is the natural test bed. By the time this mold enters build, tenant YOUR_TENANT_ID should also have ~500k-1M bronze messages from today's CLI backfill (mold-4 work), which is ideal: resume functionality can be tested against a realistic "some contacts already done, more to do" state.
- **Phase 2 of mold-4 is folded into this mold** — originally mold-4 suggested splitting resume into a separate mold-5. This mold IS that split, done at the same time as the UI work because they're tightly coupled.
- **Parent relationship**: semantically depends on mold-4 (the CLI is the engine this mold drives). Consider setting `parent: mold-4` in the header if the molds backend supports it.

## Design Decisions (resolved)

1. **Admin page visibility**: visible to all logged-in users — the current auth model has one login per tenant with no roles. Revisit when roles are introduced.
2. **Cancellation mechanism**: soft cancel via flag file (`/tmp/dialo-cancel-{job_id}`) polled every 5 contacts. Subprocess exits cleanly and marks job `cancelled`. Hard kill (`SIGTERM`) avoided — leaves job in ambiguous `running` state.
3. **Scope of sync_progress view**: logged-in tenant's data only. Cross-tenant god view requires separate auth — out of scope.
4. **Log file layout**: flat directory `~/logs/` with filenames prefixed `backfill-{tenant_id}-{unix_ts}.log`. Simpler for v1.
5. **Pre-check contact count in UI**: show "X/Y contacts already backfilled, will process Z" on the Start panel — pull from `sync_progress` count before launching. Nice UX, low cost since the query is already needed for the progress panel.
