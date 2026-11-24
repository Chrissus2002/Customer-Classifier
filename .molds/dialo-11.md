<!-- molds
id: dialo-11
stage: design
resume_stage: 
parent: dialo-7
deps: dialo-9,dialo-10,dialo-14
priority: P2
created_at: 2026-04-16T10:01:48Z
updated_at: 2026-04-18T13:43:36Z
closed_at: 
defer_until: 
code_branch: 
cast_until: inherit
-->


# jbuild - Journey stage classifier lifecycle

## TL;DR

- Build journey-stage classification on top of current enrollments from
  `dialo-10`, using the adapter boundary corrected in `dialo-14`.
- Replace tenant-global classifier behavior with journey-scoped versions,
  version-scoped stages, and current stage results.
- `jbuild.core.classification` owns the lifecycle over a
  `ClassificationStore`; adapter details stay outside core.
- Preserve `draft -> test -> activate` through core, CLI, and API.
- V1 stores current results only, with explicit stale-state rules.

## Problem

The current product direction has traits and routing/enrollments. The next
missing piece is per-journey stage classification.

The old implementation shape was tenant-global:

- one active classifier config for the tenant
- one stage taxonomy for the tenant
- one latest stage result per canonical owner
- one stale-contact computation based on global classifier version drift
- one admin screen that edits a single prompt and stage list

That is incompatible with `jbuild`. A contact first gets routed into a current
journey. Stage classification should then run only in the context of that
current journey and that journey's active version.

The build must also avoid repeating the earlier mistake from `dialo-9`: the
core classifier lifecycle cannot be a Supabase-shaped service. Supabase is the
first adapter. Core classification should be expressed in product terms.

Non-goals:

- trait definition or trait resolution
- routing rule design or enrollment writes
- analytics/audience reads
- provider-specific export workflows
- a full ground-truth labeling platform
- historical result/event replay

## Solution

Add a storage-agnostic journey-stage classification layer.

### Core Contract

Create `journey-builder/jbuild/core/classification.py` or a small
`journey-builder/jbuild/core/classification/` package with:

- value shapes for journey versions, stages, current enrollments, messages,
  stage results, stale candidates, and eval results
- a `ClassificationStore` protocol that supplies:
  - journey version reads/writes
  - stage reads/writes
  - current enrollment reads
  - canonical message reads
  - current stage result reads/writes
  - stale candidate queries
  - activation persistence
- prompt composition helpers
- `ClassificationService` for draft, preview prompt, eval/test, activation,
  stale detection, and classification runs
- provider adapter usage behind the existing classifier provider factory

Core rules:

- no Supabase imports
- no `scripts.supabase_client`
- no physical schema/table names
- no direct connector assumptions
- no FastAPI, Click, Streamlit, React, or Vite imports

### Product Model

Logical objects:

- `journey_version`
- `journey_stage`
- `stage_result`
- `classification_eval_run`
- `stale_classification_candidate`

V1 semantics:

- one active version per journey
- one mutable draft per journey
- stages belong to a journey version
- stage identity is `stage_key`; display label and description are editable
- one current result per `(tenant_id, canonical_owner_id, journey_id)`
- classification only runs for the owner's current enrollment
- no silent fallback to a global stage list

### Adapter Mapping

Extend the current Supabase adapter with `SupabaseClassificationStore` and
`create_classification_service(...)`.

The adapter may map logical objects to database schema files and RPCs. That is
adapter work. The core lifecycle should not know those names.

Recommended physical additions for the first Supabase adapter:

1. `public.tenant_journey_versions`
   - versioned classifier config per journey
   - one active version per `(tenant_id, journey_id)`
   - one never-activated draft per journey

2. `public.tenant_journey_version_stages`
   - stage rows for one version
   - `stage_key`, display label, description, display order

3. current stage result mapping
   - one current result per canonical owner plus journey
   - stores journey version, stage key, confidence, reasoning, provider
     classifier version, classified timestamp, and last inbound message
     timestamp

4. activation function
   - atomically activate one journey version
   - do not run classification inside activation

5. merge/stale invalidation support
   - owner merges or routing changes should make downstream results stale
   - SQL/functions should set invalidation flags or allow stale queries to see
     the change; SQL should not call the Python classifier

### Headless Surfaces

Expose the lifecycle through:

- `journey-builder/jbuild/api/classification.py`
- `journey-builder/jbuild/api/main.py`
- `journey-builder/jbuild/cli/main.py`
- optional `journey-builder/jbuild/workers/classification.py`

Example CLI:

```bash
jbuild versions draft --tenant 310131 --journey retail_buyers --from journey.yaml
jbuild versions preview-prompt --tenant 310131 --journey retail_buyers --draft
jbuild eval run --tenant 310131 --journey retail_buyers --draft --sample 20
jbuild versions activate --tenant 310131 --journey retail_buyers --config <version-id>
jbuild classify stale --tenant 310131 --journey retail_buyers
jbuild classify run --tenant 310131 --journey retail_buyers --batch-size 50
```

Example API:

```http
POST /journeys/{journey_id}/versions/drafts
GET  /journeys/{journey_id}/versions
POST /journeys/{journey_id}/versions/{version_id}/eval-runs
POST /journeys/{journey_id}/versions/{version_id}/activate
GET  /classifications/stale
POST /classifications/runs
```

### Build Surface Alignment

Core lifecycle work belongs in `journey-builder/jbuild/core/classification.py`.
The current runtime mapping belongs in
`journey-builder/jbuild/adapters/supabase.py`. HTTP routes belong in
`journey-builder/jbuild/api/classification.py` and are registered from
`journey-builder/jbuild/api/main.py`; commands belong in
`journey-builder/jbuild/cli/main.py`; optional batch execution belongs in
`journey-builder/jbuild/workers/classification.py`.

The first adapter's schema-as-code changes live in
`database/00_reset_database.sql`, `database/03_silver_layer.sql`,
`database/04_rls_policies.sql`, and `database/05_functions.sql`. Legacy
compatibility can touch `scripts/classify_worker.py`, `scripts/classifiers/`,
`app/database.py`, and `app/pages/2_Admin.py`, but only as adapters or
reference material. Studio work under `journey-builder/app/src/` remains a
client. Verification belongs in `tests/unit/test_jbuild_classification.py`,
`tests/unit/test_jbuild_cli.py`, `tests/unit/test_jbuild_api.py`, and
`tests/unit/test_sql_contracts.py`.

### Draft, Test, Activate

Draft:

- one mutable draft per journey
- editing a draft replaces that draft's stage snapshot

Test/eval:

- scope samples to owners currently enrolled in the journey
- compare draft output with current stored stage result for the same journey
- return stored stage, draft stage, confidence, reasoning, changed flag, and
  summary counts
- this is regression-style testing, not ground-truth scoring

Activate:

- atomically activate the selected journey version
- keep historical activated rows immutable
- do not reclassify inside the activation transaction
- stale detection drives follow-up classification jobs

### Stale Detection

An owner is stale for a journey when:

- it is currently enrolled in that journey and has no result
- its result was produced by an older version than the active journey version
- newer customer messages exist than the result's last message timestamp
- the current enrollment changed after the result was classified
- the current enrollment is marked for reroute

The service should ask the store for candidates rather than hardcoding SQL.

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/jbuild/core/classification.py` | create | Storage-agnostic journey-stage classifier lifecycle |
| `journey-builder/jbuild/adapters/supabase.py` | refactor | Add Supabase classification store and service factory |
| `journey-builder/jbuild/api/classification.py` | create | Thin HTTP routes for versions, eval, stale, and classify runs |
| `journey-builder/jbuild/api/main.py` | refactor | Register classification routes |
| `journey-builder/jbuild/cli/main.py` | refactor | Add `jbuild versions`, `jbuild eval`, and `jbuild classify` commands |
| `journey-builder/jbuild/workers/classification.py` | create later | Batch classification and eval jobs |
| `database/00_reset_database.sql` | refactor | Reset support for classification tables/functions |
| `database/03_silver_layer.sql` | refactor | Add the first Supabase adapter physical mapping for versions, stages, and current results |
| `database/04_rls_policies.sql` | refactor | Tenant isolation for classification tables |
| `database/05_functions.sql` | refactor | Atomic journey-version activation and stale/merge support |
| `scripts/classify_worker.py` | adapter/refactor | Delegate legacy worker behavior to jbuild services if still needed |
| `scripts/classifiers/` | reuse/refine | Reuse provider factory behind classification service |
| `app/database.py` | adapter only | Legacy helpers delegate if needed |
| `app/pages/2_Admin.py` | reference/client only | Preserve workflow ideas without keeping it as product truth |
| `journey-builder/app/src/` | client only | Studio consumes API; no duplicated lifecycle semantics |
| `tests/unit/test_jbuild_classification.py` | create | Core lifecycle, prompt, stale, eval, and classification tests with fake stores |
| `tests/unit/test_jbuild_cli.py` | refactor | Command wiring for versions/eval/classify |
| `tests/unit/test_jbuild_api.py` | refactor | Route wiring without UI/runtime dependencies |
| `tests/unit/test_sql_contracts.py` | refactor | Schema/function contract checks for the Supabase adapter |

## Verification

- Core classification module has no Supabase import, runtime client import, or
  physical table names.
- Multiple journeys can exist per tenant, each with its own active classifier
  version.
- One active version exists per journey, not per tenant.
- Stage results are scoped to canonical owner plus journey.
- Stage identity uses `stage_key`, not mutable display labels.
- Draft, eval/test, and activate work through core, CLI, and API.
- Stale detection accounts for active version drift, newer messages, enrollment
  updates, and reroute invalidation.
- The system reports "no active journey version" instead of silently using a
  global fallback taxonomy.
- Full `.venv/bin/pytest tests` passes after implementation.
- `./jbuild --help` shows the new command groups.
- API route imports do not require Streamlit, React, Vite, or a running
  Supabase instance.

## Implementation Notes

- This mold was cleaned up after `dialo-14` and `dialo-10` established the
  adapter boundary. Do not regress to schema-native core services.
- Preserve the existing classifier workflow ideas, not the old tenant-global
  data model.
- Keep v1 current-result-first. Do not add a result history engine yet.
- Keep Studio as a client experience. The lifecycle must work headlessly first.
- worktree: yes


## Notes

- [2026-04-18T13:43:36Z] Cleanup pass: aligned active jbuild mold language to the adapter-boundary model. Removed legacy medallion/schema vocabulary from user-facing/core contract text, kept product terms and store/adapter boundaries, and verified the design gate passes cleanly.
