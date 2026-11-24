<!-- molds
id: dialo-4
stage: closed
resume_stage: 
parent: 
deps: 
priority: P2
created_at: 2026-04-15T07:55:34Z
updated_at: 2026-04-15T12:22:23Z
closed_at: 2026-04-15T12:22:23Z
defer_until: 
code_branch: mold/dialo-4
-->




# Task daemon — scheduled exact drift checks and future ops tasks

## TL;DR

- The Admin page currently computes exact drift by crawling all Wati contacts and counting distinct normalized phones in Postgres. For tenant `310131`, the live numbers are `9443` raw Wati contacts, `8886` distinct normalized Wati contacts, `8885` DB contacts, and real drift `1` — but the crawl takes about 2 minutes and must leave the UI hot path.
- `dialo-4` should no longer be a one-off drift script. It should become a small resident task daemon with a code-defined task registry. V1 registers only `exact_contact_drift`; future tasks can be added without inventing a second scheduler.
- Persist generic execution history in `public.daemon_task_runs` and make the UI read the latest stored `exact_contact_drift` result only. No live Wati crawl in Streamlit.
- Keep the current DB normalization authority for this mold (`bronze.normalize_phone()` + `bronze.count_distinct_normalized_phones()`). Multi-country normalization is a separate design in `dialo-5`.

## Problem

The current Admin UI now computes *exact* contact drift in-process:

- `app/pages/2_Admin.py` calls `_get_wati_normalized_contact_count()`
- that function uses `WatiAPIClient.get_contacts()` to crawl the full Wati contact list
- it then sends the raw Wati phone list back into Postgres via `count_distinct_normalized_phones()`
- the result is cached in Streamlit, but only for 30 minutes and only inside the app process

That solved the false `558` drift number caused by comparing raw Wati totals to deduped DB contacts, but it created a new operational problem:

- cold page loads can block on a full Wati crawl
- there is still no durable execution history
- there is still no background runner
- there is still no reusable execution surface for other recurring ops tasks

That last point matters now. Drift checking is only the first obvious background task. The repo already has other task-shaped work that does not belong in the Streamlit request cycle:

- exact contact drift checks
- future alert dispatch when drift crosses thresholds
- potential auto-import follow-up logic
- classifier batch runs (`scripts/classify_worker.py`)
- webhook health checks via the existing observability SQL in `database/06_webhook_logging.sql`

So the real problem is larger than “run drift check on a schedule.” Dialo needs a small, explicit background execution layer.

## Solution

### 1. Introduce a real daemon runtime, not another one-off script

Add a resident Python process that owns recurring operational tasks.

Suggested shape:

- `scripts/task_daemon.py`
- `scripts/daemon_tasks/` package for task implementations

Daemon responsibilities:

- load a code-defined task registry
- wake up on a fixed poll interval (for example every 60 seconds)
- decide which tasks are due
- run them serially
- isolate failures so one task failing does not kill the whole loop
- record every run to the database
- keep running under process supervision

CLI surface:

- `--tenant-id <id>` required in v1
- `--run-once` for manual testing and deploy verification
- `--task <name|all>` to run a single task for debugging
- `--poll-seconds <n>` optional, default `60`

Do **not** make task scheduling DB-configurable in v1. Keep the registry in code so the first implementation stays small and predictable.

### 2. Add a generic task-run history table

Instead of creating a drift-specific scheduler table first, add a generic append-only run log:

```sql
CREATE TABLE public.daemon_task_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id BIGINT NOT NULL REFERENCES public.tenants(tenant_id),
  task_name TEXT NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'daemon', -- daemon | manual
  status TEXT NOT NULL,                   -- running | success | error | skipped
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  duration_ms INTEGER,
  result JSONB,
  error_message TEXT,
  notes TEXT
);

CREATE INDEX idx_daemon_task_runs_tenant_task_started
  ON public.daemon_task_runs (tenant_id, task_name, started_at DESC);
```

This belongs in `database/02_bronze_layer.sql`, next to `public.import_jobs`, because it is operational execution state, not tenant metadata.

Important design choice:

- Do **not** add RLS for this table in `dialo-4`.
- Existing public operational tables such as `public.import_jobs`, `public.webhook_logs`, and `public.webhook_processing_log` do not use the `current_setting('app.tenant_id', ...)` pattern.
- If public-table hardening happens later, it should be done consistently across all such tables, not just `daemon_task_runs`.

### 3. Define a simple task contract

Each daemon task should expose:

- `name`
- `interval`
- `error_retry_interval`
- `run(tenant_id) -> TaskResult`

`TaskResult` should be structured, not stringly-typed. At minimum:

- `status`: `success` | `error` | `skipped`
- `result`: JSON-serializable dict
- `error_message`: optional
- `notes`: optional

The daemon should determine whether a task is due by looking at the latest run for `(tenant_id, task_name)`:

- after `success`, wait the normal `interval`
- after `error`, wait the shorter `error_retry_interval`
- if no run exists, run immediately at startup

This is enough for v1 and avoids adding a second “task state” table too early.

### 4. Implement the first task: `exact_contact_drift`

Add `scripts/daemon_tasks/exact_contact_drift.py`.

Flow:

1. fetch tenant credentials
2. call `WatiAPIClient.get_contact_count()` for the cheap raw total
3. call `WatiAPIClient.get_contacts()` for the full contact crawl
4. extract raw phone strings from the Wati contacts
5. call `count_distinct_normalized_phones()` so Postgres remains the normalization authority
6. call a new `get_contact_count_by_tenant()` helper for exact `silver.contacts` count
7. build a structured result payload and persist it through `daemon_task_runs`

Suggested result payload:

```json
{
  "wati_raw_contact_count": 9443,
  "wati_distinct_contact_count": 8886,
  "db_contact_count": 8885,
  "contact_drift": 1,
  "threshold": 50,
  "threshold_exceeded": false,
  "normalization_strategy": "bronze.normalize_phone"
}
```

Task config for v1:

- interval: every 4 hours
- error retry: every 15 minutes
- threshold stored in code/config passed to the task, not in a separate DB config table yet

Critical scope decision:

- Do **not** fold alert transport or auto-import into the first cut of this task.
- The task should detect and record threshold exceedance, and log it loudly.
- Actual external notification delivery can be the next task added to the daemon.
- If auto-import is ever added, make it a second task such as `contact_import_if_drifting`, not hidden behavior inside `exact_contact_drift`.

That separation matters because:

- exact drift and contact import are both full Wati crawls
- combining them would make one task do too much
- later tasks should be composable and independently testable

### 5. Add database helpers that match the daemon shape

Extend `app/database.py` with helpers the daemon and UI can both reuse:

- `get_contact_count_by_tenant(tenant_id)` — exact count using `count="exact"`, not by loading all rows
- `insert_daemon_task_run(...)`
- `update_daemon_task_run(...)` or `finish_daemon_task_run(...)`
- `get_latest_daemon_task_run(tenant_id, task_name)`
- `get_daemon_task_run_history(tenant_id, task_name, limit=10)`

Reuse the existing `count_distinct_normalized_phones()` helper. It is already the correct bridge into DB-authoritative normalization.

### 6. Make the Admin UI consume stored task output only

Update `app/pages/2_Admin.py` so the Operations tab no longer calls Wati.

Remove the live drift path:

- `_get_wati_normalized_contact_count()`
- `_refresh_drift_result()`
- `_drift_result_is_stale()`
- `_clear_drift_result()`
- the `st.session_state` drift cache

Replace it with:

- latest `exact_contact_drift` task result from `daemon_task_runs`
- optional history table / expander showing recent runs

UI behavior:

- keep the top drift area minimal
- show only stored values: `Wati distinct`, `DB`, `Delta`
- if there is no successful drift run yet, show a simple info state
- if the latest run failed, show the failure reason

Keep the interface aligned with the user’s earlier preference:

- no scan button
- no live “Checking Wati...” spinner on page load
- no border-heavy extra drift UI

One extra UX note:

- after a manual contact import completes, the UI should tell the user that drift updates on the daemon’s next run
- do **not** reintroduce a synchronous recrawl just to refresh the metric immediately

### 7. Deploy the daemon as a user-level systemd service on schipperinc

Now that `dialo-4` is a resident multi-task runner, `cron` is no longer the right abstraction.

Add a user service such as:

```ini
[Unit]
Description=Dialo CX task daemon
After=default.target

[Service]
Type=simple
WorkingDirectory=%h/dialo-cx
ExecStart=%h/dialo-cx/.venv/bin/python scripts/task_daemon.py --tenant-id 310131
Restart=always
RestartSec=5
StandardOutput=append:%h/logs/daemon.log
StandardError=append:%h/logs/daemon.log

[Install]
WantedBy=default.target
```

Operational notes:

- add a single-instance lock inside the daemon process (for example a file lock under `%h/.local/state/dialo-cx/daemon.lock`) so accidental double starts fail safely
- if user lingering is not enabled on `schipperinc`, enable it as part of deployment so the daemon survives logout/reboot properly
- keep Streamlit and the daemon as separate services

## Files to Modify

| File | Action | Purpose | Done |
|------|--------|---------|------|
| `database/00_reset_database.sql` | edit | Drop `public.daemon_task_runs` on full reset | yes |
| `database/02_bronze_layer.sql` | edit | Add `public.daemon_task_runs` beside existing operational job tables | yes |
| `app/database.py` | edit | Add task-run helpers and exact contact count helper | yes |
| `app/pages/2_Admin.py` | edit | Remove live Wati drift crawl and render stored daemon output only | yes |
| `scripts/task_daemon.py` | **new** | Resident daemon loop and CLI entry point | yes |
| `scripts/daemon_tasks/__init__.py` | **new** | Task registry | yes |
| `scripts/daemon_tasks/base.py` | **new** | Shared task contract / result type | yes |
| `scripts/daemon_tasks/exact_contact_drift.py` | **new** | First daemon task: exact drift check | yes |
| `tests/unit/test_task_daemon.py` | **new** | Verify scheduling, retry intervals, and failure isolation | yes |
| `tests/unit/test_exact_contact_drift_task.py` | **new** | Verify exact drift payload and DB-helper integration | yes |
| `~/.config/systemd/user/dialo-daemon.service` | deploy | Run the daemon continuously on `schipperinc` | yes |

## Verification

1. Run `python scripts/task_daemon.py --tenant-id 310131 --run-once --task exact_contact_drift` locally — it should insert one successful `daemon_task_runs` row with structured drift counts.
2. Confirm the stored drift result matches the known live numbers for tenant `310131`: raw Wati `9443`, distinct normalized Wati `8886`, DB `8885`, drift `1`.
3. Reload Admin → Operations and confirm the page no longer performs a Wati crawl on load. There should be no “Checking Wati...” spinner and no live `getContacts()` dependency in the render path.
4. Force a task failure (for example with a bad token in a test harness) and verify the daemon records a failed run, stays alive, and retries on the shorter error interval.
5. Install and start `dialo-daemon.service` on `schipperinc`, then verify the daemon log and a fresh `daemon_task_runs` row after one scheduled cycle.
6. Run `pytest tests/unit/test_task_daemon.py tests/unit/test_exact_contact_drift_task.py`.

## Implementation Notes

- This mold is intentionally the right order before `dialo-5`. The daemon skeleton and stored-result UI are useful regardless of how phone normalization changes later.
- `dialo-4` should continue using the current normalization authority:
  - `bronze.normalize_phone()`
  - `bronze.count_distinct_normalized_phones()`
- `dialo-5` can later replace that normalization strategy without requiring another scheduler rewrite.
- The repo already has background-task-shaped code:
  - `scripts/classify_worker.py`
  - Streamlit-launched message backfill subprocesses tracked via `public.import_jobs`
  - webhook health SQL in `database/06_webhook_logging.sql`
- Those are future candidates for the daemon registry, but they are not part of the first build slice.
- Do not overload `public.import_jobs` to represent daemon tasks. It already has message/contact import semantics; keep daemon execution history separate.
- Build progress:
  schema and DB helpers landed first so the daemon runtime and UI can share one storage/query surface.
  daemon runtime and the first exact-drift task are now implemented; remaining work is UI consumption, tests, and schipperinc service wiring.
  UI now reads stored daemon output only, and the targeted daemon/drift tests pass locally.
  schipperinc is now running `dialo-daemon.service`; both a manual run and a daemon-scheduled run persisted `exact_contact_drift` rows with drift `1`.
