<!-- molds
id: mold-4
stage: closed
resume_stage: 
parent: 
deps: 
priority: P2
created_at: 2026-04-08T05:21:43Z
updated_at: 2026-04-08T07:26:53Z
closed_at: 2026-04-08T07:26:53Z
defer_until: 
code_branch: 
-->














# Fix batch_messages_import: rate limiting, retry, dedup, CLI args

## Problem

The historical message backfill (`scripts/batch_messages_import.py` + `scripts/wati_client.py:get_messages_per_contact`) is half-built and unsafe to run as-is. Discovered while QA'ing the self-hosted Supabase deployment on schipperinc VPS (2026-04-08). Four concrete defects, **but the headline finding from the filippa comparison is that two of them target features the Wati API doesn't actually support**, so the fix shape is different from what we initially thought.

### Defect 1 — `?from=` URL construction is broken AND the underlying feature doesn't exist
`scripts/wati_client.py:46` builds:
```python
url = self.base_url + "/api/v1/getMessages/" + contact_phone_number + "?pageSize=1000"
if from_date:
    url = url + "?from=" + from_date
```
This produces `.../getMessages/PHONE?pageSize=1000?from=2026-01-01` — malformed (`?` should be `&`). **But filippa explicitly abandoned date-filtered backfill** because the Wati API has no working date filter on `/getMessages`. See filippa git log:
- `3d024ab` "fixed Wati API message fetching - now properly fetches all messages u..."
- `65d9613` "simplified message sync - fetch ALL messages like old smart_sync.py"
- `a58de07` "added pageSize=1000 parameter to get_messages - fixes API returning 0..."

Filippa's current `WatiClient.get_messages` (`filippa/wati/shared/wati_client.py:185-242`) declares a `since` argument in its signature but **never sends it to the API** (the function body never references `since` again). It is dead code, kept for compatibility. Filippa fetches everything every run and dedupes in Postgres via `ON CONFLICT (message_id)`.

**Implication**: the right fix is not "fix the typo" — it is "delete the entire `from_date` branch and adopt filippa's strategy of fetch-all + dedupe."

### Defect 2 — No per-contact `pageNumber` loop, BUT filippa doesn't have one either
`scripts/wati_client.py:get_messages_per_contact` does a single `session.get(url)` for `pageSize=1000` and returns. No `pageNumber` increment.

Filippa's `get_messages` (`filippa/wati/shared/wati_client.py:199-242`) has the **same shape** — single fetch with `pageSize=1000`, defensive log if `total > received`, no loop. Comment in filippa source (line 199): *"API supports up to at least 500, we'll use 1000 to be safe"*. So this is not a regression dialo-cx introduced; it's a pattern dialo-cx inherited.

**Implication**: dialo-cx can either (a) match filippa exactly and accept the >1000-message-per-contact data loss risk, or (b) actually do better and add a real `pageNumber` loop. Option (b) is genuinely worth doing because filippa-dev has multi-year customer service histories where some contacts likely exceed 1000 messages. The Wati API does support `pageNumber` on getMessages — filippa just chose not to use it. Cost is ~10 lines of code.

### Defect 3 — `batch_messages_import.py` argparse is broken
```python
parser.add_argument(
    "--limit",
    action="store_const",
    help="Limit the number of contacts that can be processed",
    const=10
)
```
- `--limit` is a `store_const` flag (no value accepted; toggles a hardcoded `10`).
- No `--tenant-id` flag — tenant is read from `os.getenv('WATI_TENANT_ID')`, which contradicts the multi-tenant model where each tenant's id should be selectable per-run.
- No `--from-file` for replaying specific phone numbers (filippa's `targeted_sync.py:204` has this for support-ticket replay; useful pattern).

### Defect 4 — Hardcoded `time.sleep(1)` per call in the client; no rate-limit awareness; no 429 retry
`scripts/wati_client.py` has `time.sleep(1)` per contact and **zero retry logic**. For filippa-dev's 8,668 contacts that's ~2.4 hours of pure idle time per full backfill, plus zero resilience to Wati hiccups (a single 429 or transient 5xx kills the whole run).

Filippa solved this years ago. `filippa/wati/shared/wati_client.py:58-80` is a **sliding-window per-minute counter** (15 lines):
```python
self.requests_per_minute = int(os.getenv('WATI_RATE_LIMIT', '10'))
self.request_times = []

def _rate_limit(self):
    now = time.time()
    minute_ago = now - 60
    self.request_times = [t for t in self.request_times if t > minute_ago]
    if len(self.request_times) >= self.requests_per_minute:
        sleep_time = 60 - (now - self.request_times[0]) + 1
        if sleep_time > 0:
            time.sleep(sleep_time)
            self.request_times = []
    self.request_times.append(now)
```
And `filippa/wati/shared/wati_client.py:97-137` is a **429-with-Retry-After + exponential backoff** retry loop:
```python
if response.status_code == 429:
    retry_after = response.headers.get('Retry-After',
                                       self.retry_base_delay * (2 ** attempt))
    retry_after = float(retry_after)
    time.sleep(retry_after)
    continue
```
Filippa's default `WATI_RATE_LIMIT=10` (per minute) is **6× more conservative** than the actual Wati limit, which per `filippa/resources/wati/api_errors_rate_limits.json:69-83` is **10 requests per 10 seconds** (~60/min). dialo-cx can safely default to 60/min and still be under the limit.

### Defect 5 (Phase 2 territory, NOT a bug today) — No resume on partial runs
**Important correction from the second design pass**: dialo-cx's `insert_bronze_messages` (`app/database.py:368-410`) **already has** the equivalent of `ON CONFLICT` via Supabase upsert:
```python
.upsert(records, on_conflict="tenant_id,wati_message_id", ignore_duplicates=True)
```
The bronze unique constraint is **composite** `(tenant_id, wati_message_id)` (`database/02_bronze_layer.sql`), and the existing upsert call references both columns correctly. **Idempotency on bronze inserts is already in place.** This was a false defect in the first design pass.

What dialo-cx is genuinely missing (compared to filippa) is **resume on partial runs** via a `bronze.sync_progress`-style table. Without that, a 2.5-hour backfill that hits a Wati timeout in hour 2 has to restart from scratch. The bronze inserts themselves would dedupe correctly on re-run, but the script has no way to skip already-completed contacts — it'd re-fetch everything from the API. That's wasteful but not data-corrupting.

**Recommendation**: Phase 2 territory. Filippa's `bronze.sync_progress` (`filippa/wati/local/local_sync.py:174-187`) is the right pattern but warrants its own mold because it's a schema change + state machine.

### Why this matters now
- The contact backfill (`batch_contact_imports.py`) was just verified working end-to-end against filippa-dev: pulled 8,668 contacts in ~2 minutes, deduped cleanly into silver.
- The next obvious step is the message backfill — and it can't be run safely in its current state.
- Filippa has a working reference implementation we can copy verbatim for most of the fix, with minor improvements where filippa is also weak.

## Solution

**Core principle: copy filippa's working patterns where dialo-cx has gaps, do NOT touch parts of dialo-cx that are already correct.** Phase 1 is intentionally narrow. Phase 2 (resume table) is a separate mold.

### What is ALREADY correct in dialo-cx (do not touch)

These are intentional design choices that the first design pass mistakenly proposed to "fix":

| Component | State | File:Line |
|---|---|---|
| Bronze upsert uses composite-key `ON CONFLICT` | ✓ correct, idempotent | `app/database.py:402-407` |
| Trigger filters batch imports out via `WHEN (NEW.batch_id IS NULL)` | ✓ correct, deliberate | `database/05_functions.sql:248` |
| Batch script calls `bronze.process_messages_to_silver(p_batch_id)` explicitly | ✓ correct (trigger doesn't fire on batch) | `app/database.py:454-485` + `database/05_functions.sql:256-322` |
| `bronze.process_messages_to_silver` is idempotent (`ON CONFLICT (tenant_id, wati_message_id) DO NOTHING`) | ✓ correct | `database/05_functions.sql:300-305` |
| Bronze stores `wati_contact_id` from the silver contact (passed via script param), not from message body | ✓ correct, makes the silver JOIN deterministic | `app/database.py:395` (`"wati_contact_id": contact_id`) |

### Phase 1 — make backfill safe and runnable (this mold)

1. **Delete the `from_date` parameter and the `?from=` branch entirely** from `scripts/wati_client.py:get_messages_per_contact`. The Wati API doesn't support it; filippa abandoned it; dialo-cx's version is broken anyway.
2. **Add a real `pageNumber` loop** in `get_messages_per_contact`. Filippa skipped this; dialo-cx can do better. Cost is ~10 lines and saves data on >1000-message contacts.
3. **Copy filippa's sliding-window rate limiter verbatim** from `filippa/wati/shared/wati_client.py:58-80`. Default `WATI_RATE_LIMIT=60` (per minute), which is at the practical Wati limit but well below the documented `10 per 10 sec` cap from `filippa/resources/wati/api_errors_rate_limits.json:69-83`.
4. **Copy filippa's 429+Retry-After+backoff retry loop** from `filippa/wati/shared/wati_client.py:97-137`. **Bug-fix while copying**: filippa's non-429 HTTPError branch (lines 120-127) does not sleep between retries; dialo-cx should add a sleep so flapping servers don't spin retries instantly.
5. **Fix the CLI** in `scripts/batch_messages_import.py`:
   - `--limit <N>` as `type=int` (replace the broken `store_const`)
   - `--tenant-id <ID>` as `type=int`, required (replace the silent `os.getenv('WATI_TENANT_ID')` read so multi-tenant works)
   - `--from-file <path>` for replaying specific phone numbers, mirror `filippa/wati/local/targeted_sync.py:204` — useful for support-ticket replays and as a unit-of-work for dev testing
   - `--dry-run` flag that lists which contacts WOULD be fetched (and their counts) without actually calling the API — cheap to add and saves the user from kicking off a 2.5-hour run that's misconfigured
   - **Do NOT add `--from-date` / `--to-date`.** Cannot be honored at the API layer. If date-bounded views are needed, do it as a Postgres query against `silver.messages.timestamp`, not as an API arg.
6. **Add a precondition check at the top of `run_imports`**: query `silver.contacts WHERE tenant_id = ?` and assert it returns >0 rows. If 0, fail loudly with: *"No contacts found for tenant X. Run batch_contact_imports.py first; message backfill requires contacts to exist in silver because `bronze.process_messages_to_silver` JOINs against `silver.contacts`."* This catches the most common foot-gun (running message backfill before contact backfill) before the user wastes any API calls.

### What Phase 1 is NOT
- Not adding a `bronze.sync_progress` resume table → **Phase 2, separate mold**
- Not parallelizing for higher throughput → out of scope; the Wati 1 RPS limit caps us at sequential anyway
- Not changing the bronze→silver function or the trigger → both are already correct

### Honest throughput estimate
- Wati's documented `/getMessages` rate limit: **10 requests per 10 seconds** = **1 request per second average**
- dialo-cx's new rate limiter (60/min) is at this limit, same as the broken `time.sleep(1)` it replaces
- For 8,668 contacts: **~2.4 hours minimum**, regardless of which approach
- **Phase 1 wins are reliability and correctness, NOT speed.** Same wall-clock time, but the run will actually complete instead of crashing on a 429 or losing data on a >1000-msg contact.
- To go faster you'd need parallel workers sharing a single rate limiter (filippa has the pattern in `concurrent_processor.py` but uses it only for the LLM classifier). **Out of scope for this mold.** File a follow-up if needed.

### Phase 2 — resumable runs (separate mold, recommended split)
Filippa's `bronze.sync_progress` table (`filippa/wati/local/local_sync.py:174-187`) lets a partial run resume from the last completed contact instead of restarting from scratch. For a 2.4-hour run, this matters.

**Why this should be a SEPARATE mold**:
- It's a schema change (new `bronze.sync_progress` table + index)
- It's a state machine (`messages_synced`, `error_message`, `synced_at` columns)
- It changes the iteration model (instead of "for contact in contacts: fetch", it becomes "for contact in unsynced_contacts: fetch; mark synced")
- Reviewers might want to ship Phase 1 first to see if the wins from rate-limit + retry alone are enough, before adding state-table complexity

**Recommend splitting at `/ready-mold`** so Phase 1 can be approved independently. Phase 2 estimated effort: ~3-4 hours of design + ~4-6 hours of build + ~1-2 hours QA.

### Concrete corrected snippet for `wati_client.get_messages_per_contact`
Modeled on filippa, with the optional pageNumber improvement:

```python
def get_messages_per_contact(self, phone: str, page_size: int = 1000) -> tuple[list[dict], bool]:
    """Fetch ALL messages for a contact, paginating until exhausted.

    Note: Wati's /getMessages does NOT support a working date filter.
    Filippa abandoned that path in commit 65d9613. Idempotency is
    handled at the bronze layer via ON CONFLICT (message_id).
    """
    all_messages: list[dict] = []
    page_number = 1
    while True:
        endpoint = f"/api/v1/getMessages/{phone}?pageSize={page_size}&pageNumber={page_number}"
        url = self.base_url.rstrip("/") + endpoint  # tenant baked into base_url
        try:
            response = self._request_with_retries("GET", url)
        except WatiAPIError as e:
            print(f" - Error fetching messages for {phone}: {e}")
            return [], False
        msg_block = response.get("messages") or {}
        items = msg_block.get("items", []) if isinstance(msg_block, dict) else (msg_block or [])
        if not items:
            break
        all_messages.extend(items)
        total = msg_block.get("total") if isinstance(msg_block, dict) else None
        if total is not None and len(all_messages) >= total:
            break
        if len(items) < page_size:
            break
        page_number += 1
    return all_messages, True
```

`_request_with_retries` is a near-copy of `filippa/wati/shared/wati_client.py:_make_request:82-137`, with the bugfix that non-429 HTTPErrors also sleep between retries.

## Files to Modify
| File | Action | Purpose |
|------|--------|---------|
| `scripts/wati_client.py` | edit | Delete `from_date` arg + branch; add sliding-window `_rate_limit()` from filippa; add `_request_with_retries()` (filippa's `_make_request` + sleep bugfix); add real `pageNumber` loop in `get_messages_per_contact`; constructor reads `WATI_RATE_LIMIT` env (default 60/min) |
| `scripts/batch_messages_import.py` | edit | Real `--limit <N>`; add `--tenant-id`, `--from-file`, `--dry-run`; remove env-var tenant read; add precondition check that `silver.contacts` for tenant has >0 rows |
| `.env.example` | edit | Document the new `WATI_RATE_LIMIT` env var (default 60) |

**Files NOT to modify** (already correct):
- `app/database.py:insert_bronze_messages` — already does upsert with composite key, do not touch
- `database/05_functions.sql` — bronze→silver function and trigger are well-designed, do not touch
- `database/02_bronze_layer.sql` — schema and constraints are correct

## Filippa bugs to NOT copy

The Explore pass surfaced several bugs in filippa's working code that we should avoid inheriting:
1. **Dead `since` parameter** (`filippa/wati/shared/wati_client.py:187`) — declared but never used. Don't copy the parameter at all in dialo-cx.
2. **HTTPError retry doesn't sleep** (`filippa/wati/shared/wati_client.py:120-127`) — flapping servers cause instant retry loops. Add a sleep in dialo-cx's version.
3. **`targeted_sync.py:121` double-sleeps** — has its own `time.sleep(1)` per contact on top of the WatiClient internal limiter. Don't replicate that pattern.
4. **`targeted_sync.py:169-172` per-row `SELECT 1` dedup** instead of `ON CONFLICT`. Slow. Always use `ON CONFLICT`.
5. **Trigger-vs-function confusion** between `local_sync.py` (calls `bronze.process_batch_to_silver` explicitly, line 529) and `targeted_sync.py:196-198` (comment says triggers handle it). Filippa commit `5fb582a` was a fix for this. dialo-cx should pick ONE strategy and stick to it. Currently dialo-cx's bronze→silver is trigger-driven for messages (verified via the live webhook stream landing in silver automatically), so the batch script should NOT also call a process function explicitly — just `INSERT` to bronze and let the trigger fire.

## Verification

After Phase 1 patches, run these in order. Each step builds on the previous.

### V1. Static checks (no DB, no API)
```
python scripts/batch_messages_import.py --help
```
Must show `--limit <N>`, `--tenant-id <ID>` (required), `--from-file <path>`, `--dry-run`. The old `store_const` form is gone.

```
python -c "from scripts.wati_client import WatiAPIClient; \
  c = WatiAPIClient('YOUR_TENANT_ID', 'fake-token'); \
  print(c._build_messages_url('5215512345678', page_number=2))"
```
Must print exactly `https://live-mt-server.wati.io/YOUR_TENANT_ID/api/v1/getMessages/5215512345678?pageSize=1000&pageNumber=2` — single `?`, `&`-joined params, no `from=`.

### V2. Rate limiter (mocked, no API)
Set `WATI_RATE_LIMIT=10`. In a Python REPL:
```
import time
from scripts.wati_client import WatiAPIClient
c = WatiAPIClient('YOUR_TENANT_ID', 'token')
start = time.time()
for _ in range(11): c._rate_limit()
print(f"11 ticks: {time.time()-start:.1f}s")
```
Expect ~60 seconds (the 11th tick blocks until the 60-second window slides). Confirms the limiter is wired.

### V3. 429 handling (mocked, no API)
Use `unittest.mock` to patch `session.get` to return a 429 with `Retry-After: 2`, then a 200. Call `_request_with_retries`. Assert it sleeps ~2 seconds and returns the 200 body without raising. (~10-line pytest.)

### V4. Precondition check works
Create a fresh test tenant with NO contacts in silver:
```sql
INSERT INTO public.tenants (tenant_id, name, slug, password, wati_api_token, status)
VALUES (88888, 'V4 Test', 'v4-test', '$2b$12$dummy', 'fake-token', 'active');
```
Run: `... --tenant-id 88888 --limit 5`
Expect immediate failure with the precondition error message about contacts. Zero Wati API calls made. Cleanup: `DELETE FROM public.tenants WHERE tenant_id = 88888`.

### V5. Dry-run against real tenant (no writes)
```
sudo -u schipperinc ~/dialo-cx/.venv/bin/python \
  ~/dialo-cx/scripts/batch_messages_import.py \
  --tenant-id YOUR_TENANT_ID --limit 5 --dry-run
```
Expect: prints "Would fetch messages for 5 contacts: [phone1, phone2, ...]" and exits. No `bronze.wati_messages` rows added. No `import_jobs` row created (or row immediately marked as `dry-run` not `running`).

### V6. End-to-end smoke against schipperinc VPS tenant YOUR_TENANT_ID
```
sudo -u schipperinc ~/dialo-cx/.venv/bin/python \
  ~/dialo-cx/scripts/batch_messages_import.py \
  --tenant-id YOUR_TENANT_ID --limit 5
```
Snapshot DB state before. Run. Check after:
- `public.import_jobs` has a new row for YOUR_TENANT_ID with status `running` → `completed`, error_message NULL
- `bronze.wati_messages` count for tenant YOUR_TENANT_ID increased by N (whatever the 5 contacts had)
- `silver.messages` count for tenant YOUR_TENANT_ID increased by approximately the same N (some may be skipped if `bronze.process_messages_to_silver` couldn't match a contact, but most should land)
- Run took roughly 5-10 seconds (5 contacts × ~1 sec/contact rate limit + processing time)

### V7. Idempotent re-run
Immediately re-run the exact same command. Check after:
- A NEW `import_jobs` row appears (different `job_id`)
- `bronze.wati_messages` count is **identical** to before (the upsert ignored duplicates)
- `silver.messages` count is **identical** to before (the `ON CONFLICT (tenant_id, wati_message_id) DO NOTHING` ignored duplicates)
- No PostgreSQL unique-constraint errors in logs
- The new job's `processed_messages` may show 0 because everything was a dupe

### V8. `--from-file` replay
```
echo "5215529668386" > /tmp/test-phones.txt   # use a real contact phone from silver.contacts
sudo -u schipperinc ~/dialo-cx/.venv/bin/python \
  ~/dialo-cx/scripts/batch_messages_import.py \
  --tenant-id YOUR_TENANT_ID --from-file /tmp/test-phones.txt
```
Expect: only that one contact's messages fetched. Other contacts untouched.

### V9. Pagination loop (only meaningful if a real >1000-msg contact exists)
Find a contact likely to have many messages (long-tenured customer). Use `--from-file` with just that phone. Watch the run log for `pageNumber=2` and `pageNumber=3` URLs. Verify final `bronze.wati_messages` count for that contact's `wati_contact_id` exceeds 1000.

If no such contact exists in filippa-dev, skip V9 and document it as "tested in mock only" (V2/V3 already cover the loop logic with mocked responses).

## Operator Walkthrough — what `batch_messages_import.py` does, in plain English

This section is for the human running the script and the human reviewing the spec. No jargon. Imagine running:

```
python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --limit 5
```

Step by step:

1. **Connect.** Script opens a connection to dialo-cx's Supabase.
2. **Look up the tenant.** Reads `public.tenants` for `tenant_id=YOUR_TENANT_ID`. Pulls out the Wati API token. If the tenant doesn't exist or has no token, fails immediately with a clear error.
3. **Precondition check.** Counts rows in `silver.contacts` for tenant YOUR_TENANT_ID. If zero, fails immediately with: *"No contacts in silver. Run batch_contact_imports.py first."* This catches the most common foot-gun before we waste a single API call.
4. **Create an import job.** Inserts a row into `public.import_jobs` with `tenant_id=YOUR_TENANT_ID`, `status='running'`, `started_at=now()`. The job's `job_id` UUID becomes the `batch_id` we tag every bronze row with.
5. **Pick contacts to process.** Reads up to 5 contacts from `silver.contacts WHERE tenant_id=YOUR_TENANT_ID` (ordered by created_at descending — newest first by default). For `--from-file`, instead reads phone numbers from the file and looks each one up in `silver.contacts`.
6. **For each of the 5 contacts:**
   - **Rate limit gate.** Before calling the Wati API, the client checks: have I made fewer than 60 requests in the last 60 seconds? If yes, proceed. If no, sleep until the oldest request ages out.
   - **API call.** GET `https://live-mt-server.wati.io/YOUR_TENANT_ID/api/v1/getMessages/<phone>?pageSize=1000&pageNumber=1`
   - **Response handling**:
     - **HTTP 200**: parse the JSON response, extract the messages list (under `messages.items`).
     - **HTTP 429** (rate-limited): read the `Retry-After` header, sleep that many seconds, retry. If no header, use exponential backoff (5 → 10 → 20 → 40 → 80 seconds, max 5 attempts).
     - **HTTP 5xx / network error**: same backoff schedule, max 5 retries, then mark this contact as failed in the script log and move on to the next.
   - **Pagination**: if the response has 1000 messages AND `total > 1000`, fetch `pageNumber=2`, `pageNumber=3`, ... until a partial page or empty page comes back. Filippa skips this; dialo-cx will do it properly.
   - **Bronze insert.** Take all the messages for this contact and bulk-upsert them into `bronze.wati_messages`. Each row gets `tenant_id=YOUR_TENANT_ID`, `batch_id=<job_id>`, `wati_contact_id=<from silver>`, the full Wati JSON in `raw_data`. The upsert is idempotent: messages we've seen before (by composite key `tenant_id,wati_message_id`) are silently ignored.
   - **Trigger does NOT fire.** Because `batch_id` is set on the row, the bronze→silver trigger's `WHEN (NEW.batch_id IS NULL)` clause skips it. Silver does not yet have these messages.
7. **After all 5 contacts are done in bronze**, the script calls one SQL function:
   ```
   SELECT bronze.process_messages_to_silver('<job_id>');
   ```
   This single call:
   - JOINs every bronze row tagged with this `batch_id` to `silver.contacts` on `(tenant_id, wati_contact_id)`
   - For each successful join, extracts the message text, direction (inbound/outbound based on `owner` field), timestamp, and inserts a row into `silver.messages`
   - Uses `ON CONFLICT (tenant_id, wati_message_id) DO NOTHING` so re-runs are idempotent
   - Returns a JSON summary: `{batch_id, tenant_id, messages_created, messages_skipped}`
8. **Mark the job complete.** Updates `public.import_jobs` row with `status='completed'`, `completed_at=now()`, `processed_messages=N`.
9. **Print summary.** Console output: tenant name, job ID, total messages processed, duration, anything skipped.

### What you see in the database after a clean run

- **`public.import_jobs`**: 1 new row, status `completed`
- **`bronze.wati_messages`**: ~5 contacts × ~50-1000 messages each = somewhere between 250 and 5000 new rows, all tagged with the same `batch_id`
- **`silver.messages`**: same count (or slightly less, if any contact lookups failed)
- **`silver.contacts`**: unchanged — this script only touches messages, not contacts. The contacts must already exist (precondition check).
- **`public.webhook_logs`**: unchanged — webhooks and batch imports use entirely separate code paths

### What happens if it dies mid-run (Phase 1 — no resume)

Say it dies after processing contacts 1-3 of 5. Then:
- The `import_jobs` row stays in `status='running'` forever (or you manually mark it `failed`)
- The first 3 contacts' messages are sitting in bronze AND silver, fully ingested
- Contacts 4 and 5 are not processed
- Re-running the same command starts over from the top — but contacts 1-3's messages will be silently skipped by the bronze upsert (`ignore_duplicates=True`) and the silver function (`ON CONFLICT DO NOTHING`)
- Net effect: re-running is **safe**, just **wasteful** (re-fetches contacts 1-3 from the Wati API for nothing)

Phase 2 (separate mold) would add a `bronze.sync_progress` table so the re-run skips contacts 1-3 entirely without hitting the API.

### Wall-clock time estimate
- 5 contacts × ~1 sec rate limit + ~0.5 sec processing each ≈ **8-10 seconds**
- Full backfill of all 8,668 filippa-dev contacts ≈ **2.4-2.6 hours** — bottlenecked by the Wati API rate limit, not our code
- Same wall-clock as the broken `time.sleep(1)` version. Phase 1 wins are reliability and correctness, not speed.

## Risks and rollback

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Real Wati API rate limit is lower than 60/min in practice | Low | Many 429s during run | Retry loop handles them; if persistent, lower `WATI_RATE_LIMIT` env var; no DB damage |
| Wati API returns unexpected JSON shape | Medium | Some messages stored as raw JSON but trigger drops them | Defensive `.get()` calls in client; failed transforms log to `webhook_processing_log` without halting |
| Script crashes mid-run | Medium (it's a 2.5h run) | Wasted API calls, no data corruption | Re-run is idempotent; Phase 2 (resume) addresses the waste |
| Patching `wati_client.py` breaks the contact backfill which uses the same client | Low | Contact import broken | The contact backfill works fine today; touch only the `get_messages_per_contact` method, leave `get_contacts` alone; smoke-test contact backfill after patches |
| `WATI_RATE_LIMIT=60` is too aggressive | Low | 429 storms | Default could be lower (30/min); env var lets ops tune without code change |
| Schema-side changes accidentally introduced | Should be zero | Could break webhook ingestion | This mold explicitly does NOT modify any SQL files; reviewers should reject any patch touching `database/*.sql` |

**Rollback plan**: All changes are to two Python files (`scripts/wati_client.py`, `scripts/batch_messages_import.py`) and one .env example. `git revert <commit>` cleanly undoes everything. No DB migrations to roll back. Webhook ingestion is unaffected by this work — it uses a different code path.

## Implementation Notes

- **Test environment**: the schipperinc VPS now has a self-hosted Supabase with tenant YOUR_TENANT_ID already configured, the real Wati API token attached, and 8,668 contacts + ~166 webhook-derived messages already in silver. It is the natural test bed for this fix. SSH as `schipperinc` and run from `~/dialo-cx`.
- **Exact filippa references** (read these before coding):
  - Sliding-window rate limiter: `filippa/wati/shared/wati_client.py:58-80`
  - 429 + Retry-After + exponential backoff: `filippa/wati/shared/wati_client.py:97-137`
  - URL builder pattern (no urljoin): `filippa/wati/shared/wati_client.py:94-95`
  - `get_messages` (single fetch + ON CONFLICT strategy): `filippa/wati/shared/wati_client.py:185-242`
  - `get_all_contacts` (proper pageNumber loop): `filippa/wati/shared/wati_client.py:244-288` — model the new dialo-cx message pagination on this
  - Bronze ON CONFLICT insert: `filippa/wati/local/local_sync.py:471-487`
  - `local_sync.py` argparse (`--reset` only): `filippa/wati/local/local_sync.py:640-659`
  - `targeted_sync.py` argparse (`--from-file`): `filippa/wati/local/targeted_sync.py:202-206`
  - Wati real rate limits reference: `filippa/resources/wati/api_errors_rate_limits.json:69-85`
- **Working reference inside dialo-cx**: `batch_contact_imports.py` is the right structural template — tenant lookup → import job creation → API client → bronze insert → mark job complete. Mirror its structure.
- **Schema-side changes**: none needed for Phase 1. Bronze table already has `wati_message_id` UNIQUE constraint (verified on schipperinc), so `ON CONFLICT (wati_message_id)` will work — note dialo-cx's column name is `wati_message_id`, not filippa's `message_id`. The bronze→silver trigger is battle-tested by the live webhook stream.
- **Suggest split**: Phase 2 (`bronze.sync_progress` resume table + state machine) deserves its own mold. Flag during `/ready-mold` review.

## Maturity notes

### Pass 1 (initial): early → mid
Initial draft based only on a quick read of dialo-cx. Identified four defects but suggested generic fixes.

### Pass 2: mid → late, after filippa Explore
Compared with filippa via a focused Explore pass. Major findings:
1. Date filtering is **not a fix-the-typo** issue — the entire feature should be deleted because the Wati API doesn't support it. Filippa's own `since` arg is dead code.
2. The "missing pagination" issue is shared with filippa, which chose to skip it. dialo-cx can do better with ~10 extra lines.
3. The highest-leverage fixes are the **rate limiter + 429 retry pattern** (filippa has both, working, copy verbatim).

### Pass 3 (current): late → tightened, after re-reading dialo-cx schema and functions
**Three claims from Pass 2 were wrong** and have been corrected:

1. **Pass 2 said dialo-cx lacks `ON CONFLICT` on bronze inserts.** False. `app/database.py:402-407` already does `upsert(records, on_conflict="tenant_id,wati_message_id", ignore_duplicates=True)`. The constraint is composite. Existing code is correct. Removed the false defect from the mold and added a "what is already correct" table.

2. **Pass 2 said the bronze→silver trigger fires automatically on batch imports.** False. `database/05_functions.sql:248` has `WHEN (NEW.batch_id IS NULL)` on the trigger. Webhooks fire it; batch imports don't. The script must (and already does) call `bronze.process_messages_to_silver(p_batch_id)` separately. The architecture is well-designed.

3. **Pass 2 missed the silver-contacts dependency.** `bronze.process_messages_to_silver` does an INNER JOIN to `silver.contacts` on `(tenant_id, wati_contact_id)`. **Messages with no matching silver contact get silently dropped** (counted as `messages_skipped`). This means the message backfill strictly requires a prior successful contact backfill. Added a precondition check (`V4` in verification) and a step to the operator walkthrough explaining this dependency.

Pass 3 also added:
- The "Files NOT to modify" anti-list to prevent reviewers/builders from breaking what's already correct.
- A 9-step Verification plan with mockable steps (V1-V4) before any real API calls (V5+).
- An "Operator Walkthrough" section in plain English that walks through `--limit 5` end to end, including the rate limiter, the trigger NOT firing, the explicit silver function call, and what the database looks like before and after.
- A "Risks and rollback" table.
- An honest throughput estimate: Phase 1 is the same wall-clock time as the broken version (~2.4h for 8668 contacts). The wins are reliability and correctness, not speed.

**Mold is now ready for `/ready-mold` review.**

Recommended for the human reviewer at `/ready-mold` time:
- Approve Phase 1 as written.
- Decide whether to **split Phase 2** (`bronze.sync_progress` resume table) into a sibling mold (`mold-5`) before approval, or carry it as a footnote. Splitting is cleaner.
- Phase 1 effort: ~2-3 hours focused implementation + ~1-2 hours testing.


## Notes

- [2026-04-08T05:36:30Z] design pass: compared with filippa/wati/shared/wati_client.py — key finding is that date filtering is not a typo fix but a feature to delete (Wati API doesn't support it; filippa abandoned in 65d9613). Pagination loop is also missing in filippa. High-leverage fixes are sliding-window rate limiter, 429+Retry-After backoff, and ON CONFLICT (wati_message_id) dedup — all copy verbatim from filippa. Phase 2 (bronze.sync_progress resume) suggested as separate split mold.

- [2026-04-08T06:01:09Z] design pass 3: corrected three false claims from pass 2 by reading dialo-cx schema/functions directly. (1) bronze upsert with composite ON CONFLICT already exists in app/database.py:402-407. (2) trigger has WHEN (NEW.batch_id IS NULL) so batch imports correctly bypass it; the script's explicit bronze.process_messages_to_silver() call is correct, not redundant. (3) bronze.process_messages_to_silver does an INNER JOIN to silver.contacts so message backfill REQUIRES prior contact backfill — added precondition check to the spec. Added operator walkthrough section, V1-V9 verification plan with mock-first steps, risks/rollback table, and 'files NOT to modify' anti-list. Mold is now late maturity, ready for /ready-mold.

- [2026-04-08T07:01:44Z] build pass complete: V1-V7 all pass against live schipperinc VPS tenant YOUR_TENANT_ID. V6 end-to-end smoke inserted 229 new bronze rows and 229 silver rows from 2/3 test contacts (1 fake test contact correctly failed). V7 idempotent re-run returned 0 new rows and marked the job as completed (not failed). Found and fixed one design gap during build: counter was tracking fetched messages instead of actually-inserted bronze rows, which caused the skip-RPC-on-empty-batch logic to never trigger; now tracks bronze_inserted from insert_bronze_messages return value. Files changed: scripts/wati_client.py (+190 -48), scripts/batch_messages_import.py (+237 -38), .env.example (+5 -0). Committed as f9f74c2 on branch mold/mold-4.

- [2026-04-08T07:24:04Z] QA review complete. Found 5 issues (2 high, 3 medium) during adversarial code re-read that V1-V7 missed: URL construction duplicated between helper and real code (V1b would pass while real code drifted), session-per-call anti-pattern (8.6k handshakes vs reused pool), --limit 0/negative silently ignored, dead WatiAPIError class, bronze→silver RPC counters not surfaced. All fixed inline in operator mode. Q1-Q8 re-verification all pass. Also added tenant wati_api_token pre-check (nit). Mold -> merge.
