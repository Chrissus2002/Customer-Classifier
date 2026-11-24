<!-- molds
id: dialo-12
stage: design
resume_stage: 
parent: dialo-7
deps: dialo-9,dialo-10,dialo-11,dialo-14
priority: P2
created_at: 2026-04-16T10:01:48Z
updated_at: 2026-04-18T13:43:36Z
closed_at: 
defer_until: 
code_branch: 
cast_until: inherit
-->


# jbuild - Inspector, analytics, and audiences

## TL;DR

- Build the read side of `jbuild` after traits, routing/enrollments, and
  journey-stage classification exist.
- Reads are current-state-first: owner, traits, matched rule, current journey,
  current stage, and stale state.
- Core read/audience services use store contracts; adapter details stay outside
  core.
- Audience generation is a product filter concern; provider-shaped campaign
  exports stay outside this mold.
- React remains a client of the API.

## Problem

Once write-side molds land, operators need to trust and inspect the result:

- what traits were resolved?
- which routing rule matched?
- which journey is current?
- which stage result is current, stale, or missing?
- which owners belong in an audience?

The old read side was shaped around a single global funnel. `jbuild` needs a
read model that follows the new product stack:

- canonical owner and recent messages
- current trait values
- current enrollment
- current journey-stage result for that enrollment
- stale/missing status
- audience filters over that current state

This mold must not drag the old physical analytics layer into the product
contract. SQL views are fine as adapter implementation, but the core read API
should be expressed in product terms.

Non-goals:

- creating trait values
- editing routing rules
- editing journey prompts or stages
- connector operations and health views
- provider-specific campaign export formatting
- full historical event explorer
- replacing the whole BI layer

## Solution

Add headless current-state read services with adapter-backed persistence.

### Core Contract

Create:

- `journey-builder/jbuild/core/read_models.py`
- `journey-builder/jbuild/core/audiences.py`

Define store protocols such as:

- `ReadStore`
- `AudienceStore`

Core services should provide:

- `get_owner_current_state(...)`
- `get_owner_inspector(...)`
- `get_journey_enrollment_distribution(...)`
- `get_journey_stage_distribution(...)`
- `query_audience(...)`
- `export_audience_shape(...)`
- `get_recent_messages_for_owner(...)`

Core rules:

- no Supabase imports
- no runtime client imports
- no physical schema/view/table names
- no provider-specific export assumptions
- no FastAPI, Click, Streamlit, React, or Vite imports

### Current-State Model

The inspector should explain one canonical owner:

- identity and last activity
- recent message excerpt
- current resolved traits with source, confidence, reasoning, and provenance
- routing explanation:
  - matched rule
  - reason
  - routing config version
- current enrollment:
  - journey key/label
  - enrollment timestamps
  - reroute invalidation
- current stage:
  - journey version
  - stage key/label
  - confidence
  - stale, missing, or current state

V1 explicitly defers:

- full timeline/history view
- past enrollment history
- past stage result history
- provider campaign execution

### Stage State Rules

Read-side stage state should be:

- `current`
- `stale`
- `missing`

A stage result is stale when:

- current enrollment was updated after the result was classified
- current enrollment is marked for reroute
- active journey version differs from the result's journey version
- newer customer messages exist than the result's last message timestamp

### Analytics

Keep v1 analytics intentionally small:

- count owners by current journey
- count owners by current journey plus current stage state
- count owners by current journey plus stage key
- count recent/engaged owners by current journey
- expose missing/stale stage counts instead of hiding them

Do not recreate every legacy chart. The goal is a small, trustworthy read
contract.

### Audiences

Audience filtering belongs here when it filters over current-state product
fields:

- journey
- stage
- stale/missing/current status
- traits
- engagement recency
- last message timestamp

Audience export should return a neutral export shape. Provider-specific CSV
column names, upload instructions, and campaign delivery belong to adapters or
connector-owned surfaces.

### Supabase Adapter Mapping

Extend `journey-builder/jbuild/adapters/supabase.py` with read/audience store
implementations.

The first Supabase adapter may use SQL views, direct queries, or a small number
of helper functions. Those are implementation details.

Recommended physical adapter read shapes:

1. `contact_current_state`
   - one row per current canonical owner
   - identity, activity, enrollment, stage, stale state, and key product fields

2. `journey_enrollment_distribution`
   - counts by current journey

3. `journey_stage_distribution`
   - counts by current journey, stage, and stale/missing/current state

4. audience query helpers
   - read/filter over current state
   - return neutral owner/contact rows, not provider-specific campaign files

These may be implemented in the existing database schema files, but core
services must only call the adapter contract.

### Build Surface Alignment

Core reads live in `journey-builder/jbuild/core/read_models.py` and
`journey-builder/jbuild/core/audiences.py`. Runtime mappings live in
`journey-builder/jbuild/adapters/supabase.py`. HTTP routes live in
`journey-builder/jbuild/api/inspector.py`,
`journey-builder/jbuild/api/analytics.py`, and
`journey-builder/jbuild/api/audiences.py`, with registration in
`journey-builder/jbuild/api/main.py`. Commands live in
`journey-builder/jbuild/cli/main.py`.

The first adapter's read models can update `database/07_gold_layer.sql` and
`database/00_reset_database.sql`. Legacy compatibility can touch `app/Home.py`
and `app/database.py`, but only as adapter/delegation work. React work under
`journey-builder/app/src/` remains client-only, and
`journey-builder/ui/README.md` should keep that boundary clear. Verification
belongs in `tests/unit/test_jbuild_reads.py`,
`tests/unit/test_jbuild_audiences.py`, `tests/unit/test_jbuild_cli.py`,
`tests/unit/test_jbuild_api.py`, and `tests/unit/test_sql_contracts.py`.

### Headless Surfaces

Expose reads through:

- `journey-builder/jbuild/api/inspector.py`
- `journey-builder/jbuild/api/analytics.py`
- `journey-builder/jbuild/api/audiences.py`
- `journey-builder/jbuild/api/main.py`
- `journey-builder/jbuild/cli/main.py`

Example CLI:

```bash
jbuild inspect owner --tenant 310131 --owner <owner-id>
jbuild analytics journeys --tenant 310131
jbuild analytics stages --tenant 310131 --journey retail_buyers
jbuild audiences query --tenant 310131 --journey retail_buyers --stage ready_to_buy
jbuild audiences export --tenant 310131 --journey retail_buyers --stage ready_to_buy --format csv
```

Example API:

```http
GET  /owners/{owner_id}/current-state
GET  /owners/{owner_id}/inspector
GET  /analytics/journeys
GET  /analytics/stages
POST /audiences/query
POST /audiences/export
```

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/jbuild/core/read_models.py` | create | Storage-agnostic current-state and inspector services |
| `journey-builder/jbuild/core/audiences.py` | create | Storage-agnostic audience query/export-shape services |
| `journey-builder/jbuild/adapters/supabase.py` | refactor | Add Supabase read/audience store implementations |
| `journey-builder/jbuild/api/inspector.py` | create | Owner current-state and inspector routes |
| `journey-builder/jbuild/api/analytics.py` | create | Journey and stage distribution routes |
| `journey-builder/jbuild/api/audiences.py` | create | Audience query and export routes |
| `journey-builder/jbuild/api/main.py` | refactor | Register read-side routes |
| `journey-builder/jbuild/cli/main.py` | refactor | Add `jbuild inspect`, `jbuild analytics`, and `jbuild audiences` commands |
| `database/07_gold_layer.sql` | refactor | First Supabase adapter read models/views |
| `database/00_reset_database.sql` | refactor | Reset support for read-side views |
| `app/Home.py` | adapter/legacy | Retire, isolate, or delegate old global-funnel reads |
| `app/database.py` | adapter only | Keep legacy read wrappers only if needed |
| `journey-builder/app/src/` | client only | Contact Inspector and analytics screens consume API |
| `journey-builder/ui/README.md` | refine | Keep UI boundary honest: React is a client |
| `tests/unit/test_jbuild_reads.py` | create | Current-state, stale-state, inspector, and distribution tests with fake stores |
| `tests/unit/test_jbuild_audiences.py` | create | Audience filter/export-shape tests with fake stores |
| `tests/unit/test_jbuild_cli.py` | refactor | Read-side command wiring |
| `tests/unit/test_jbuild_api.py` | refactor | Read-side route wiring |
| `tests/unit/test_sql_contracts.py` | refactor | Supabase adapter read-view contract checks |

## Verification

- Core read/audience modules have no Supabase import, runtime client import, or
  physical schema/view/table names.
- Inspector explains traits, matched rule, current journey, current stage, and
  stale/missing/current state for one owner.
- Analytics no longer assume one global stage set for the tenant.
- Read-side truth is current enrollment plus current result for that journey.
- Missing and stale stage results are visible in inspector and distributions.
- Audience query works from current-state product fields without provider
  campaign assumptions.
- CLI and API can inspect an owner, return journey/stage distributions, query
  audiences, and return neutral export shapes.
- React, if touched, consumes the API and does not duplicate current-state
  joins, stale-state, or audience filtering.
- Full `.venv/bin/pytest tests` passes after implementation.
- `./jbuild --help` shows the new command groups.

## Implementation Notes

- This mold was cleaned up after `dialo-14`, `dialo-10`, and `dialo-11`
  established the adapter boundary.
- Keep read services current-state-first. Do not build a history explorer yet.
- Keep provider-specific campaign mechanics out of the core product read model.
- A small set of trustworthy read models is better than recreating every legacy
  chart.
- worktree: yes


## Notes

- [2026-04-18T13:43:36Z] Cleanup pass: aligned active jbuild mold language to the adapter-boundary model. Removed legacy medallion/schema vocabulary from user-facing/core contract text, kept product terms and store/adapter boundaries, and verified the design gate passes cleanly.
