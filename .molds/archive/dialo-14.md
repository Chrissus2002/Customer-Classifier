<!-- molds
id: dialo-14
stage: closed
resume_stage: 
parent: dialo-7
deps: 
priority: P1
created_at: 2026-04-18T12:49:35Z
updated_at: 2026-04-18T12:56:26Z
closed_at: 2026-04-18T12:56:26Z
defer_until: 
code_branch: 
cast_until: inherit
-->









# Unmix jbuild trait adapter boundary

## TL;DR

Fix the `dialo-9` trait implementation so `jbuild` core is storage-agnostic.
Supabase remains the first runtime adapter, but `silver.*` tables and Supabase
RPC calls must not be the product boundary.

## Problem

The landed `dialo-9` implementation is mixed:

- `journey-builder/jbuild/core/traits.py` describes itself as a
  Supabase-backed trait service.
- the core service imports `scripts.supabase_client` through its default client
  path.
- core methods call Supabase tables/RPCs directly, including the current
  physical `silver.messages` and `silver.contact_trait_values` mapping.
- product docs still say `jbuild` depends on canonical data "in Supabase" and
  mention "Supabase-backed values" as a trait source.

That conflicts with the product split already documented in `dialo-7`,
`docs/PRODUCT_MAP.md`, `wati-to-supabase/contracts/canonical-contract.md`, and
`journey-builder/contracts/classifier-input-contract.md`: `jbuild` consumes a
canonical conversation contract; the Wati-to-Supabase connector is one producer
of that contract.

## Solution

Introduce an explicit adapter boundary:

- keep domain validation, source precedence, and Trait Classifier behavior in
  `jbuild.core`
- define a trait store interface for trait definitions, current trait values,
  classifier configs, and canonical message reads
- move Supabase client/table/RPC access into a `jbuild.adapters.supabase`
  implementation
- make CLI/API defaults instantiate the Supabase adapter for today
- keep tests proving core logic can run against fake stores without importing
  Supabase or knowing about `silver.*`
- update product docs so Supabase is described as the current adapter, not the
  architecture

## Files to Modify
| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/jbuild/core/traits.py` | refactor | Make trait core depend on a store contract instead of a Supabase client |
| `journey-builder/jbuild/adapters/` | create | First adapter home; add Supabase implementation |
| `journey-builder/jbuild/cli/main.py` | refactor | Instantiate the current adapter explicitly |
| `journey-builder/jbuild/api/traits.py` | refactor | Instantiate the current adapter explicitly |
| `journey-builder/jbuild/core/trait_classifier.py` | refine | Require an explicit trait service so core classifier logic stays storage-agnostic |
| `journey-builder/jbuild/workers/trait_classifiers.py` | refactor | Instantiate the current adapter at the worker boundary |
| `journey-builder/contracts/trait-inference-model.md` | refine | Remove Supabase-as-source/product-boundary language |
| `journey-builder/docs/product-scope.md` | refine | State canonical contract dependency and current Supabase adapter separately |
| `journey-builder/README.md` | refine | Same product boundary clarification |
| `journey-builder/app/src/data/traits.ts` | refine | Remove Supabase-shaped product copy from sample trait data |
| `journey-builder/app/src/data/inspector.ts` | refine | Remove Supabase-shaped product copy from sample inspector data |
| `tests/unit/test_jbuild_traits.py` | refactor | Cover fake-store core behavior and adapter-boundary assertions |
| `tests/unit/test_jbuild_cli.py` | refactor | Keep CLI smoke tests green after explicit adapter creation |
| `tests/unit/test_jbuild_api.py` | refactor | Keep API smoke tests green after explicit adapter creation |

## Verification

- focused jbuild unit tests pass
- full pytest suite passes
- CLI help still works through both module and root wrapper
- API imports still work without UI runtime
- source search confirms `jbuild.core.traits` has no Supabase import and no
  `silver` table names

## Implementation Notes

- This is not a physical schema rename.
- This is not a new connector abstraction for Wati.
- Keep the existing Supabase behavior operational through the adapter so the
  landed `dialo-9` runtime remains usable.


## Notes

- [2026-04-18T12:50:14Z] gate: action=design_approved kind=approval from=design to=build actor="dev"

- [2026-04-18T12:55:25Z] Build implemented adapter boundary: jbuild core now depends on TraitStore, Supabase table/RPC access moved into jbuild.adapters.supabase, CLI/API/workers instantiate the current Supabase adapter explicitly, and product docs/fixture copy now describe Supabase as an adapter rather than the product boundary. Verification passed: focused jbuild tests 15/15, .venv full pytest 82/82, ./jbuild --help, API import/health, git diff --check, and app npm run typecheck.

- [2026-04-18T12:55:34Z] QA review: scope matches product-boundary correction. Core no longer imports scripts.supabase_client, contains no tenant_trait_* table names, and contains no silver schema/table calls; those are isolated to the Supabase adapter. Existing runtime behavior preserved through explicit default adapter wiring.

- [2026-04-18T12:56:26Z] gate: action=land_accepted kind=approval from=land to=closed actor="dev"
