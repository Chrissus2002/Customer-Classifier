<!-- molds
id: dialo-10
stage: build
resume_stage: 
parent: dialo-7
deps: dialo-9,dialo-14
priority: P2
created_at: 2026-04-16T10:01:47Z
updated_at: 2026-04-18T13:43:36Z
closed_at: 
defer_until: 
code_branch: 
cast_until: inherit
-->







# jbuild - Routing and enrollments

## TL;DR

- Build deterministic routing from resolved trait values into stable journeys,
  but keep the `jbuild` core storage-agnostic.
- `jbuild.core.routing` owns the pure engine over a `RoutingStore` contract;
  adapter details stay outside core.
- V1 routes each canonical owner into exactly one current journey using ordered
  rules plus one fallback.
- Preview is side-effect-free; apply persists through the active adapter.
- Rules use stable trait identities; labels and keys are explanatory snapshots.

## Problem

`dialo-9` gave `jbuild` reusable trait definitions, current trait values, Trait
Classifiers, and a headless CLI/API skeleton. `dialo-14` then corrected that
slice so Supabase is the first adapter, not the product boundary.

`dialo-10` was already promoted to Build before that correction. Its previous
spec mixed product architecture with the current Supabase physical mapping: it
described adapter tables and DB RPCs as though they were the routing model
itself. That is wrong for the new headless contract.

The product still needs routing and enrollments:

- stable journeys that routing can target
- ordered routing rules
- draft, validate, preview, activate, and apply flows
- durable current enrollment state
- explanation of which rule matched a canonical owner
- stale/reroute detection when traits, routing configs, or merges change

But the boundary must be:

- `jbuild` core consumes a canonical owner/trait/enrollment contract
- adapters provide storage and query mechanics
- Wati-to-Supabase is one producer of canonical conversation data
- Supabase is the first persistence/runtime adapter, not the definition of
  `jbuild`

Non-goals:

- trait definition or trait resolution work already handled by `dialo-9`
- journey-stage prompt editing and stage classification, reserved for
  `dialo-11`
- broad analytics or audience work, reserved for `dialo-12`
- a generic workflow graph engine
- a physical legacy schema rename, which belongs to connector/schema cleanup
  work

## Solution

Add routing and enrollment as a storage-agnostic `jbuild` product slice.

### Core contract

Create `journey-builder/jbuild/core/routing.py` with:

- pure value shapes for journeys, routing configs, routing rules, conditions,
  trait-value snapshots, enrollment snapshots, and routing results
- a `RoutingStore` protocol that supplies journeys, routing configs, trait
  values, current enrollments, reroute candidates, activation, and enrollment
  persistence
- pure condition helpers and `evaluate_contact_routing(...)`
- a `RoutingService` that coordinates validation, preview, activation, apply,
  and enrollment reads by calling the store contract

Core rules:

- no Supabase imports
- no `scripts.supabase_client`
- no runtime schema calls
- no direct table names such as `tenant_routing_configs` or
  `journey_enrollments`
- no FastAPI, Click, Streamlit, React, or Vite imports

The core model should use product names:

- `canonical_owner_id` or `contact_id` for the current canonical owner supplied
  by the adapter
- `journey_id`
- `routing_config_id`
- `routing_rule_id`
- `trait_id`
- `resolved_value`
- `enrollment`

The current adapter can map `canonical_owner_id` to its physical owner key, but
that mapping must not leak into the core routing engine.

### Supabase adapter

Extend `journey-builder/jbuild/adapters/supabase.py` with:

- `SupabaseRoutingStore`
- `create_routing_service(...)`
- Supabase table/RPC reads and writes needed by routing
- current physical mapping to repo schema files

The adapter owns the current database details:

- journey catalog storage
- routing config/rule storage
- active/draft activation RPC
- enrollment upsert RPC
- current trait-value reads from the existing Supabase trait mapping
- current enrollment reads
- reroute candidate queries
- merge invalidation support through the schema/functions files

This is allowed because it is the adapter. It should not be copied into
`jbuild.core`.

### Headless surfaces

Expose the same `RoutingService` through thin interfaces:

- `journey-builder/jbuild/api/routing.py`
- `journey-builder/jbuild/api/main.py`
- `journey-builder/jbuild/cli/main.py`
- optional worker helpers only if apply/preview batching needs them

Example CLI shape:

```bash
jbuild journeys list --tenant 310131
jbuild journeys upsert --tenant 310131 --key wholesale_buyers --label "Wholesale Buyers"
jbuild routing draft --tenant 310131 --from routing.yaml
jbuild routing validate --tenant 310131 --config <config-id>
jbuild routing preview --tenant 310131 --config <config-id> --sample 50
jbuild routing activate --tenant 310131 --config <config-id>
jbuild routing apply --tenant 310131
jbuild enrollments list --tenant 310131 --journey wholesale_buyers
```

Example API shape:

```http
GET  /journeys
POST /journeys
POST /routing/drafts
POST /routing/drafts/{config_id}/validate
POST /routing/drafts/{config_id}/preview
POST /routing/drafts/{config_id}/activate
POST /routing/apply
GET  /enrollments
```

### V1 routing semantics

- evaluate rules in ascending `display_order`
- first matching rule wins
- exactly one fallback rule is required
- fallback rule must have empty conditions
- non-fallback rules must have at least one condition
- conditions use AND semantics inside a rule
- supported operators:
  - `eq`
  - `neq`
  - `in`
  - `not_in`
  - `exists`
  - `not_exists`
- routing reads resolved trait values only
- routing must not inspect raw messages, raw provider payloads, or Wati fields
- rules evaluate by stable `trait_id`; trait key/label fields are snapshots
  for explanation only

### V1 enrollment semantics

- exactly one current enrollment per `(tenant_id, canonical_owner_id)`
- current-state table first, not a history/event log
- persist:
  - canonical owner id
  - journey id
  - routing config id/version
  - matched rule id
  - routing reason
  - `needs_reroute`
  - routed/updated timestamps
- enrollment changes are the downstream stale boundary for `dialo-11`
- if journey assignment changes, later journey-stage results should be treated
  as stale or out of scope until refreshed

### Preview and apply

Preview:

- side-effect-free
- can evaluate active config, draft config, or explicit candidate config
- returns current journey, candidate journey, matched rule, changed flag, and
  explanation per owner
- uses the same pure engine as apply

Apply:

- evaluates the active config by default
- can limit to specific owners or reroute candidates
- writes through the adapter's enrollment persistence contract
- updates enrollment metadata even when journey membership is unchanged if
  rule, reason, config version, or reroute state changed
- clears `needs_reroute` after successful persistence

### Reroute candidacy

An owner should be considered for reroute when:

- no current enrollment exists
- current enrollment belongs to an older active routing config version
- current enrollment references a config that is no longer active
- one or more resolved trait values changed after `routed_at`
- `needs_reroute = true`

The core service should ask the store for reroute candidates rather than
assuming any particular SQL query.

### Supabase physical v1 mapping

The first adapter can persist routing in the current Supabase schema-as-code.
These names are implementation details of `SupabaseRoutingStore`, not the
`jbuild` core contract.

Recommended physical additions:

1. `public.tenant_journeys`
   - stable journey catalog per tenant
   - `journey_id`, `tenant_id`, `journey_key`, `display_label`,
     `description`, `is_active`, timestamps
   - unique `(tenant_id, journey_key)`
   - unique `(tenant_id, journey_id)` for tenant-consistent references

2. `public.tenant_routing_configs`
   - versioned tenant-wide routing rule set
   - one active config per tenant
   - one never-activated draft per tenant
   - `activated_at` is history, not a mutable draft marker after activation

3. `public.tenant_routing_rules`
   - ordered child rules under a config
   - target journey reference
   - `conditions JSONB`
   - `is_fallback`
   - snapshots for journey/trait keys where useful for explanation

4. current enrollment table or a later canonical/adapter equivalent
   - current enrollment per canonical owner in the existing Supabase mapping
   - one row per `(tenant_id, contact_id)` while the current adapter maps
     canonical owner to legacy contact
   - `needs_reroute` and routing metadata

5. Supabase RPCs/functions
   - `public.activate_routing_config(...)`
   - `public.upsert_journey_enrollments(...)`
   - merge invalidation in the current owner-merge function

Those schema changes belong in the numbered schema files because this repo uses
schema-as-code. The build must still keep direct reads/writes in the Supabase
adapter.

### Supabase function requirements

`activate_routing_config` should validate before activation:

- config exists and belongs to tenant
- exactly one fallback rule
- fallback has empty conditions
- non-fallback rules have conditions
- every target journey exists, is active, and belongs to tenant
- every JSON condition references an active trait definition for the same
  tenant
- every operator is supported

`upsert_journey_enrollments` should:

- reject wrong-tenant owners, journeys, configs, and rules
- reject non-canonical contacts in the current Supabase mapping
- insert missing rows
- update rows when journey, config, matched rule, reason, version, routed time,
  or reroute state changes
- clear `needs_reroute` on successful apply
- return inserted, updated, unchanged, and rejected counts

The current owner-merge function should:

- move source enrollment to target when target has no enrollment
- keep target enrollment and set `needs_reroute = true` when both have
  enrollments
- record move/invalidation counts in existing merge audit metadata
- not try to call the Python router from SQL

### Reuse vs new code

Reuse:

- `dialo-14` adapter pattern from `jbuild.core.traits` and
  `jbuild.adapters.supabase`
- current `jbuild` API/CLI package skeleton
- existing React routing mock surfaces only as clients
- existing SQL schema-as-code conventions

Do not reuse blindly:

- `tenant_segments.query_config`; segments are read-side audience filters, not
  the router
- tenant-global classifier helpers or `JourneyClassifier`; routing is a
  separate deterministic write-side decision
- Supabase client access inside core modules
- mutable trait keys as routing identities

### Build surface alignment

The contract update belongs in
`journey-builder/contracts/journey-routing-model.md`. Storage-agnostic routing
logic belongs in `journey-builder/jbuild/core/routing.py`; Supabase persistence
belongs in `journey-builder/jbuild/adapters/supabase.py`; HTTP exposure belongs
in `journey-builder/jbuild/api/routing.py` with registration in
`journey-builder/jbuild/api/main.py`; CLI exposure belongs in
`journey-builder/jbuild/cli/main.py`.

The current Supabase adapter mapping needs schema-as-code updates in
`database/00_reset_database.sql`, `database/03_silver_layer.sql`,
`database/04_rls_policies.sql`, and `database/05_functions.sql`. Legacy
Streamlit compatibility, if needed, belongs in `app/database.py` as delegation
only. React work under `journey-builder/app/src/` must remain client-side.

Verification should cover pure routing behavior in
`tests/unit/test_jbuild_routing.py`, command wiring in
`tests/unit/test_jbuild_cli.py`, route wiring in
`tests/unit/test_jbuild_api.py`, and Supabase schema/function contracts in
`tests/unit/test_sql_contracts.py`.

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/contracts/journey-routing-model.md` | refine | Make the routing contract adapter-aware and concrete |
| `journey-builder/jbuild/core/routing.py` | create | Storage-agnostic routing engine, store protocol, service, validation, preview, and apply orchestration |
| `journey-builder/jbuild/adapters/supabase.py` | refactor | Add `SupabaseRoutingStore` and `create_routing_service` with all Supabase table/RPC access |
| `journey-builder/jbuild/api/routing.py` | create | Thin HTTP routes for journeys, routing, preview/apply, and enrollments |
| `journey-builder/jbuild/api/main.py` | refactor | Register routing routes beside trait routes |
| `journey-builder/jbuild/cli/main.py` | refactor | Add `jbuild journeys`, `jbuild routing`, and `jbuild enrollments` commands |
| `database/00_reset_database.sql` | refactor | Drop routing functions/tables for local reset support |
| `database/03_silver_layer.sql` | refactor | Add the Supabase adapter's physical routing/enrollment mapping |
| `database/04_rls_policies.sql` | refactor | Add tenant isolation for routing and enrollment tables |
| `database/05_functions.sql` | refactor | Add activation, enrollment upsert, and merge-aware enrollment handling |
| `app/database.py` | adapter only | Delegate only if legacy Streamlit compatibility needs routing reads |
| `journey-builder/app/src/` | client only | Keep React as API consumer; no duplicated routing engine |
| `tests/unit/test_jbuild_routing.py` | create | Cover pure routing semantics, validation, preview diffs, apply orchestration, and reroute detection with fake stores |
| `tests/unit/test_jbuild_cli.py` | refactor | Assert new command groups wire without requiring Supabase at import time |
| `tests/unit/test_jbuild_api.py` | refactor | Assert routing routes import without UI runtime dependencies |
| `tests/unit/test_sql_contracts.py` | refactor | Cover Supabase schema/function contracts for activation, upsert, RLS, and merge invalidation |

## Verification

- `jbuild.core.routing` has no Supabase import, no `scripts.supabase_client`,
  no runtime schema calls, and no physical table names.
- Pure routing tests prove first-match-wins, fallback behavior, AND conditions,
  supported operators, and stable trait-id evaluation.
- Service tests use fake stores to prove preview is side-effect-free and apply
  persists only through the store contract.
- Supabase adapter tests or SQL contract tests prove the current physical
  schema has journeys, routing configs, rules, enrollments, activation, upsert,
  RLS, reset support, and merge invalidation.
- CLI help shows `journeys`, `routing`, and `enrollments` command groups.
- API route import works without Streamlit, React, Vite, or a running Supabase
  instance.
- Full `.venv/bin/pytest tests` passes.
- `./jbuild --help` passes.
- `git diff --check` passes.
- If React files are touched, `npm run typecheck` in `journey-builder/app`
  passes.

## Implementation Notes

- This mold was returned from Build to Design after `dialo-14` corrected the
  `dialo-9` trait slice. The old version was too Supabase/schema-native.
- worktree: yes
- The corrected design still permits a Supabase-backed MVP. It just requires
  Supabase to sit behind the adapter boundary.
- Do not widen this mold into the connector schema rename. Physical legacy
  schema names can remain in the Supabase adapter until `dialo-8` or later
  cleanup.
- Keep routing narrowly deterministic. Do not build a graph engine, arbitrary
  SQL filter runner, or chained classifier workflow.
- The build should start with core tests against fake stores, then add the
  Supabase adapter mapping.
- If implementation pressure forces a smaller MVP, preserve the adapter
  boundary first and cut breadth from CLI/API commands before cutting the
  boundary.

## Notes

- [2026-04-18T11:12:58Z] Design pass after `dialo-9` landed: refreshed stale
  module paths to the real `journey-builder/jbuild/` package, tightened DB
  activation/enrollment contracts, added the DB-backed enrollment upsert
  requirement, clarified draft semantics, and aligned verification with the
  current CLI/API/test surfaces.

- [2026-04-18T11:17:05Z] gate: action=design_approved kind=approval from=design to=build actor="dev"

- [2026-04-18T13:17:00Z] Corrected after dialo-14: routing/enrollments are now specified as a storage-agnostic jbuild core plus RoutingStore contract, with Supabase as the first adapter mapping rather than the product boundary. Removed direct-core assumptions around physical schema tables and Supabase RPCs; those are now adapter/schema implementation details.

- [2026-04-18T13:17:27Z] Design hardening: added explicit build-surface alignment for routing contract, core, Supabase adapter, API, CLI, schema-as-code, React/client-only work, and verification files; added worktree note after gate warnings.

- [2026-04-18T13:17:31Z] gate: action=design_approved kind=approval from=design to=build actor="dev"

- [2026-04-18T13:43:36Z] Cleanup pass: aligned active jbuild mold language to the adapter-boundary model. Removed legacy medallion/schema vocabulary from user-facing/core contract text, kept product terms and store/adapter boundaries, and verified the design gate passes cleanly.
