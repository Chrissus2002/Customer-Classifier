<!-- molds
id: dialo-5
stage: closed
resume_stage: 
parent: 
deps: 
priority: P2
created_at: 2026-04-15T10:04:36Z
updated_at: 2026-04-15T14:28:05Z
closed_at: 2026-04-15T14:28:05Z
defer_until: 
code_branch: mold/dialo-5
-->







# Canonical multi-country phone identity and Wati lookup separation

## TL;DR

- `phone_normalized` currently does triple duty: it is the dedupe key, the value passed to Wati `/getMessages/{phone}`, and the phone shown across the app. `wati_contact_id` also does double duty as the only provider identity on a deduped contact row. That coupling is the real design problem.
- The current DB normalizer in `database/05_functions.sql` is fine for Filippa because the live duplicates are overwhelmingly Mexico `52...` vs `521...`, but it is not a global phone-identity strategy.
- `dialo-5` should choose an app-authoritative parser in Python using `phonenumbers`, store canonical outputs in the DB, and explicitly separate Dialo contact identity from Wati lookup keys.
- The hard part is mixed mode: webhooks still create contacts through a DB trigger today, while batch imports, drift, analytics, and campaign exports all read `phone_normalized`. Until webhook cutover exists, the new identity model needs a background reconciliation path and must stay shadow-first.
- This should be phased. Phase 1 adds shadow identity fields, Wati-key mapping, and a reconciliation task. Phase 2 cuts batch/drift/analytics over once shadow coverage is complete. Phase 3 removes the last DB-trigger-specific normalization path for webhooks and retires legacy columns.

## Problem

Dialo currently treats phone normalization as a single DB function plus a single contact column:

- `bronze.normalize_phone(phone TEXT)` strips non-digits and applies one Mexico-specific rewrite: `52XXXXXXXXXX -> 521XXXXXXXXXX` in [database/05_functions.sql](/home/dev/repos/manuelschipper/dialo-cx/database/05_functions.sql:88)
- webhook ingestion uses it in `bronze.transform_webhook_to_silver()` in [database/05_functions.sql](/home/dev/repos/manuelschipper/dialo-cx/database/05_functions.sql:222)
- full contact import uses it in `bronze.process_contacts_to_silver()` in [database/05_functions.sql](/home/dev/repos/manuelschipper/dialo-cx/database/05_functions.sql:416)
- exact drift now depends on the same rule through `count_distinct_normalized_phones()` in [app/database.py](/home/dev/repos/manuelschipper/dialo-cx/app/database.py:111)

That is good for consistency, but the normalization quality is intentionally narrow.

Evidence from the live tenant (`310131` / Filippa):

- `silver.contacts` is overwhelmingly Mexico-format: `8761 / 8885` contacts start with `521`
- `557 / 558` duplicate groups in the raw Wati contact import are exactly the Mexico `52...` vs `521...` variant
- exact drift after comparing distinct normalized Wati phones to `silver.contacts` is only `1`, which shows the current rule is working well enough for this tenant

The more important issue is that the current schema collapses several distinct concepts into one row:

- `silver.contacts.phone_normalized` is currently both the dedupe key and the Wati lookup phone used by [scripts/batch_messages_import.py](/home/dev/repos/manuelschipper/dialo-cx/scripts/batch_messages_import.py:250)
- `silver.contacts.wati_contact_id` is currently the only stored provider identity, but `bronze.process_contacts_to_silver()` picks just one row per normalized phone via `DISTINCT ON (...)` and discards the rest of the duplicate Wati contact IDs during contact upsert in [database/05_functions.sql](/home/dev/repos/manuelschipper/dialo-cx/database/05_functions.sql:437)
- `bronze.process_messages_to_silver()` then joins messages back to contacts on `silver.contacts.wati_contact_id = bronze.wati_messages.wati_contact_id` in [database/05_functions.sql](/home/dev/repos/manuelschipper/dialo-cx/database/05_functions.sql:383), which means a future dedupe rule that collapses more contacts can silently orphan messages if the retained contact row carries only one provider ID
- `gold.contact_activity` and downstream analytics still expose `phone_normalized` as the contact phone in [database/07_gold_layer.sql](/home/dev/repos/manuelschipper/dialo-cx/database/07_gold_layer.sql:29)
- campaign CSV export still writes `phone_normalized` into the `phone_number` column for Wati uploads in [app/Home.py](/home/dev/repos/manuelschipper/dialo-cx/app/Home.py:118)
- duplicate-health detection still groups by `phone_normalized` in [database/06_webhook_logging.sql](/home/dev/repos/manuelschipper/dialo-cx/database/06_webhook_logging.sql:214)
- webhooks still create or update contacts entirely inside Postgres triggers, so a Python-authoritative parser cannot become the live source of truth immediately without some shadow reconciliation step

So the real problem is not just "the SQL normalizer is too dumb." The real problem is:

- stripping to digits is not enough to canonicalize numbers across countries
- country/region cannot be inferred reliably from raw digits alone
- local-format numbers, trunk prefixes, and ambiguous country codes can produce false merges or false splits
- `phone_normalized` currently means both canonical identity and provider lookup phone
- `wati_contact_id` is not modeled as a many-to-one provider key mapping
- campaign export and analytics still depend on a Wati-compatible phone value
- the webhook ingestion path cannot call the new Python parser directly today
- literal shared code across SQL, Python, and the Edge Function does not exist today, and a naive “mirror the logic everywhere” approach will drift

So the problem is not "the current normalizer is broken for Filippa." The problem is that Dialo needs a canonical phone identity model that remains correct when tenants and contacts are not predominantly Mexican mobile numbers, without breaking Wati message lookup or losing messages during dedupe.

## Solution

Design a proper canonical phone identity model and choose one real source of truth.

### 1. Choose one parser authority: Python, not Postgres

`dialo-5` should stop treating `bronze.normalize_phone()` as the long-term authority.

Recommended decision:

- add a new Python module, for example `scripts/phone_identity.py`
- use `phonenumbers` as the only real parser
- have Python return a structured result object, not just a string

Suggested return shape:

```python
{
  "raw_input": "...",
  "digits_only": "...",
  "phone_e164": "+14155550100" | None,
  "phone_identity_key": "e164:+14155550100" | "wati:abc123" | "raw:4155550100",
  "normalization_status": "e164" | "assumed_region" | "wati_fallback" | "raw_fallback" | "invalid" | "missing",
  "region_used": "US" | "MX" | None,
  "provider_lookup_phone": "14155550100" | "5218123456789" | None
}
```

Reasoning:

- world-class phone parsing belongs in a real library, not hand-written SQL
- Python is already the dominant runtime for batch imports, drift checks, and daemon work
- literal shared code across SQL, Python, and TypeScript is not realistic in this repo without introducing a new service boundary
- the DB should store canonical outputs and enforce uniqueness, not invent canonical form from raw strings

What “shared” means after this decision:

- one Python parser implementation used by batch imports, drift checks, and future backfills
- a golden fixture set in `tests/fixtures/` that any non-Python caller must satisfy if it needs to normalize too
- SQL functions reduced to storage/upsert helpers and aggregate helpers over stored canonical fields

### 2. Split canonical contact identity from provider lookup behavior

Do not redefine `phone_normalized` in place and hope downstream code keeps working.

Instead, introduce explicit fields on `silver.contacts`:

- `phone_identity_key TEXT NOT NULL`
  - Dialo dedupe key
  - unique per tenant
  - examples: `e164:+14155550100`, `wati:abc123`, `raw:4155550100`
- `phone_e164 TEXT`
  - nullable best canonical phone when parsing succeeded
- `normalization_status TEXT NOT NULL`
  - examples: `e164`, `assumed_region`, `wati_fallback`, `raw_fallback`, `invalid`, `missing`
- `normalization_region TEXT`
  - the tenant default region or explicit country context used during parsing
- `phone_raw_primary TEXT`
  - preferred raw display value; not the dedupe key

Transition rule:

- keep legacy `phone_normalized` during migration for compatibility
- treat legacy `phone_normalized` as a provider-facing compatibility value until Wati lookup and CSV export are both moved
- do not let new code depend on it once `phone_identity_key` exists
- retire it only after all batch, drift, and UI consumers are moved off it

### 3. Add a provider-key mapping table for Wati identities

The current one-column `wati_contact_id` field is too weak for a deduped contact model.

Add a new table, for example `silver.contact_wati_keys`:

```sql
tenant_id BIGINT NOT NULL
contact_id UUID NOT NULL REFERENCES silver.contacts(contact_id)
wati_contact_id TEXT NOT NULL
wati_lookup_phone TEXT
is_primary BOOLEAN NOT NULL DEFAULT FALSE
first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()

UNIQUE (tenant_id, wati_contact_id)
```

Why this is necessary:

- `scripts/batch_messages_import.py` should call Wati using `wati_lookup_phone`, not `phone_normalized`
- `app/Home.py` campaign CSV export should use an explicitly chosen Wati-compatible value, not implicitly whatever the dedupe key happens to be
- `bronze.process_messages_to_silver()` should join through `silver.contact_wati_keys`, not `silver.contacts.wati_contact_id`
- one canonical Dialo contact may legitimately accumulate multiple Wati contact IDs over time

### 4. Add tenant-level region context and safe fallback rules

Add `public.tenants.default_phone_region TEXT`, stored as uppercase ISO 3166-1 alpha-2 like `MX`, `US`, `GB`.

Parsing rules:

1. If the input is already a valid international number, preserve its E.164 form.
2. If the input is not international but a tenant default region exists, parse using that region.
3. If parsing still fails or remains ambiguous, do not guess and do not merge on a guessed global number.
4. In ambiguous/failure cases, fall back to a safe identity key:
   - prefer `wati:<wati_contact_id>` when a provider ID exists
   - otherwise use `raw:<digits_only>`

This is the key quality rule for multi-country behavior:

- false splits are annoying
- false merges are dangerous
- when the parser is unsure, store the contact but keep the identity conservative

### 5. Phase the rollout instead of pretending this is a one-line replacement

This mold should not build as a single “edit the SQL function and ship it” change.

Recommended phases:

#### Phase 1: identity model + parser + reporting

- add the Python parser module and `phonenumbers`
- add `default_phone_region`
- add the new canonical identity fields on `silver.contacts` as nullable shadow columns
- add `silver.contact_wati_keys`
- backfill existing contacts into the new fields
- add a daemon/backfill path, for example `contact_identity_refresh`, that fills or repairs shadow identity fields for contacts created by the existing webhook trigger path
- generate a collision/ambiguity report on the live tenant before making the new key authoritative
- do not add `UNIQUE (tenant_id, phone_identity_key)` yet

#### Phase 2: batch + drift cutover

- change contact imports to write the new identity fields directly
- change message backfill to use `wati_lookup_phone`
- change drift checks to compute distinct `phone_identity_key` values in Python, not via `bronze.count_distinct_normalized_phones()`
- change gold views and campaign CSV export to read explicit canonical/display/provider-facing fields rather than `phone_normalized`
- verify that the reconciliation task keeps shadow coverage near 100% for contacts still arriving via webhooks
- keep the Admin UI reading stored daemon results only
- only after coverage and collision review passes, enforce uniqueness on `phone_identity_key`

#### Phase 3: webhook cutover and legacy removal

- remove the last DB-trigger-specific normalization path for webhook contact creation
- update `bronze.transform_webhook_to_silver()` or replace that path with a processor that consumes already-normalized outputs
- remove the temporary reconciliation path once webhooks write the authoritative identity directly
- retire `bronze.normalize_phone()` and legacy `phone_normalized` once no active path depends on them

### 6. Plan an explicit migration and collision workflow

Changing the identity key changes dedupe behavior.

The build plan must cover:

- backfilling existing `silver.contacts` rows with `phone_e164`, `phone_identity_key`, status, and region
- creating `silver.contact_wati_keys` rows from existing `silver.contacts.wati_contact_id` plus current lookup phone behavior
- deciding which explicit field feeds Wati campaign CSV export during mixed mode
- keeping new webhook-created rows reconciled until the webhook cutover lands
- detecting collisions before enforcing `UNIQUE (tenant_id, phone_identity_key)`
- merging only after review when two current contacts collapse to one identity key
- using `silver.merge_contacts()` plus audit logging for accepted merges, rather than silent overwrites
- preserving `silver.messages.contact_id` references during merges

### 7. Keep the daemon and UI architecture aligned

Exact drift should stay in background tasks and stored task results. This mold must remain compatible with `dialo-4`.

That means:

- the daemon should eventually compare distinct Wati `phone_identity_key` values to DB contact identity keys
- the daemon is also the natural home for temporary shadow reconciliation while webhooks remain DB-trigger-based
- the Admin UI should keep reading stored drift output only
- no phone parsing belongs in the Streamlit render path

## Files to Modify
| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | edit | Add `phonenumbers` for authoritative parsing |
| `scripts/phone_identity.py` | **new** | Canonical parser and identity-key builder used by imports, daemon, and backfills |
| `scripts/daemon_tasks/` | edit | Add a shadow reconciliation task while webhooks still create contacts via DB triggers |
| `database/01_tenants.sql` | edit | Add `default_phone_region` and document region semantics |
| `database/03_silver_layer.sql` | edit | Add `phone_identity_key`, `phone_e164`, normalization metadata, and `silver.contact_wati_keys` |
| `database/05_functions.sql` | edit | Stop relying on `bronze.normalize_phone()` as the long-term dedupe authority; join messages via Wati key mapping |
| `database/06_webhook_logging.sql` | edit | Update duplicate-contact health checks off legacy `phone_normalized` assumptions |
| `database/07_gold_layer.sql` | edit | Point downstream views at the new canonical contact identity fields |
| `app/database.py` | edit | Expose helpers for new contact identity fields and Wati key mappings |
| `app/Home.py` | edit | Export Wati campaign CSVs from an explicit provider-facing phone field |
| `scripts/batch_contact_imports.py` | edit | Feed imported contacts through the Python parser and persist the new identity model |
| `scripts/batch_messages_import.py` | edit | Use `wati_lookup_phone` and stop assuming `phone_normalized` is the API lookup key |
| `scripts/daemon_tasks/exact_contact_drift.py` | edit | Compare distinct Python-built `phone_identity_key` values against DB contact identity counts |
| `supabase/functions/wati-webhook/index.ts` | review | Decide whether webhook normalization remains deferred to DB temporarily or needs a later contract-tested caller |
| `tests/fixtures/phone_identity_cases.json` | **new** | Golden fixtures for cross-country normalization and fallback behavior |
| `tests/unit/test_phone_identity.py` | **new** | Unit tests for parser behavior and identity-key safety |
| `tests/unit/test_exact_contact_drift_task.py` | edit | Update drift tests to the new identity key model |

## Verification

1. Create a golden fixture set covering at least:
   - Mexico `52...` vs `521...`
   - NANP/US-Canada formatted vs unformatted numbers
   - one additional non-NANP country such as UK
   - ambiguous local-format numbers that should not merge
2. Verify that the Python parser produces the same `phone_identity_key` for equivalent numbers across formatting variants.
3. Verify that ambiguous or invalid numbers do not collapse to the same identity key unless they share a provider fallback key intentionally.
4. Run a shadow backfill on tenant `310131` and produce:
   - count of contacts that keep the same identity
   - count of contacts that would merge
   - count of contacts that fall back to `wati:*` or `raw:*`
5. Verify that the temporary reconciliation task brings shadow identity coverage for active contacts to an explicit threshold, for example `>= 99.9%`, before any downstream cutover.
6. Verify that `scripts/batch_messages_import.py` succeeds when using `wati_lookup_phone` instead of legacy `phone_normalized`.
7. Verify that Wati campaign CSV export still produces a format accepted by Wati after moving off implicit `phone_normalized`.
8. Verify that `bronze.process_messages_to_silver()` no longer drops messages when multiple Wati contact IDs map to one canonical contact.
9. Recompute exact Wati-vs-DB drift using the new `phone_identity_key` rule and confirm the metric remains stable for tenant `310131`.
10. Add contract tests that prevent drift between the Python parser and any non-Python caller that participates in normalization.

## Implementation Notes

- The current DB normalizer is good for the present tenant but not globally:
  - Mexico-specific `52 -> 521` handling explains almost all real duplicate groups in Filippa data.
  - It should be treated as a tenant-shaped heuristic, not a universal algorithm.
- The hidden migration risk is not just the phone parser. It is the contact model:
  - `phone_normalized` is overloaded
  - `wati_contact_id` is modeled as one value on a deduped contact row
  - batch message lookup and message-to-contact joins currently depend on those overloaded fields
- The mixed-mode risk is operational:
  - until the webhook path is cut over, new contacts created by DB triggers will not automatically have Python-authoritative identity fields
  - that means shadow columns must stay nullable at first, and a repair/reconciliation path is required before downstream consumers rely on them
- Wati-facing semantics need to stay explicit:
  - campaign CSV export is for Wati uploads, not just human display
  - `wati_lookup_phone` or another provider-facing field must remain valid for Wati even if the canonical Dialo identity key changes
- Be careful not to design a "smart" normalizer that silently guesses wrong. Storing an explicit fallback key is safer than falsely merging two different people.
- Exact drift should eventually stop using `bronze.count_distinct_normalized_phones()` because that helper only receives phone strings, not the provider IDs needed for safe fallback identity keys.
- Split note:
  this work is still probably too broad for one build slice if the webhook path must end on the same parser authority.
  the cleanest shape is likely to split `dialo-5` into:
  1. schema + parser + batch/drift cutover
  2. webhook cutover + legacy SQL normalizer removal

## Build Notes

- Implemented the shadow-first slice: Python `phone_identity` parser, shadow contact fields, `silver.contact_wati_keys`, `contact_identity_refresh`, and batch/drift/UI cutover onto explicit Wati lookup phones.
- Kept the webhook DB trigger on legacy `phone_normalized` for immediate contact creation, but it now also writes `wati_lookup_phone` and `silver.contact_wati_keys` so the mapping model stays current until webhook cutover exists.
- `bronze.process_messages_to_silver()` now joins through `silver.contact_wati_keys`, which removes the old single-`wati_contact_id` assumption on deduped contacts.
- Read-only live verification on tenant `310131` with the new parser produced:
  - shadow coverage `100.0%` (`8886 / 8886`)
  - contacts that would merge under the new key: `0`
  - fallback identities: `4 wati:*`, `0 raw:*`
  - exact drift on the new identity rule: raw Wati `9444`, distinct Wati `8887`, DB `8886`, drift `+1`
- Rebuild after QA finding:
  - `contact_identity_refresh` now derives the desired `wati_lookup_phone` from the parser result instead of preserving a stale stored legacy value
  - added a regression test for the US local-number repro (`4155550100` -> canonical `e164:+14155550100`, provider lookup `14155550100`)


## Notes

- [2026-04-15T13:27:45Z] QA finding: contact_identity_refresh preserves an already-populated legacy wati_lookup_phone instead of upgrading it to the parser-derived provider phone. Repro: with default_phone_region=US and a contact carrying phone_raw=4155550100 plus legacy wati_lookup_phone=4155550100, build_contact_identity_refresh_plan produces phone_identity_key=e164:+14155550100 but still writes wati_lookup_phone=4155550100. This breaks batch_messages_import and campaign export for non-MX tenants while the coverage metric still reports 100%, because coverage is counted from derived identities rather than persisted shadow fields.
