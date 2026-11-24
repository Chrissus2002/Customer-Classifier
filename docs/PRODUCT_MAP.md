# Product Map

This repo is being centered around two related products plus one shared layer.

## Products

### `wati-to-supabase/`

Owns the Wati-specific connector:

- Wati API and webhook behavior
- connector runtime and daemon tasks
- connector-facing data contracts
- connector docs and operational guidance

### `journey-builder/`

Owns the conversation intelligence product:

- trait inference and routing
- classifier workflow and prompts
- journey analytics and segmentation
- product UX and app-facing docs
- audience generation and product semantics

### `shared/`

Neutral home for code and contracts that should not belong to either product's
UI/runtime boundary.

Near-term intended use:

- shared Supabase/runtime helpers
- shared canonical-contract helpers
- shared types/utilities that both products import

## Layer Language

Use this vocabulary consistently:

- `staging`: connector-owned raw ingress
- `canonical`: normalized conversation contract
- `analytics`: derived reporting layer
- `ops`: runtime state, jobs, logs, and observability

## Current Practical Reality

The repo is not fully moved yet.

Today, important code still lives in legacy locations:

- `app/`
- `scripts/`
- `database/`
- `supabase/functions/`

That is fine for now. The new directories are rails for the product split, not a
claim that the migration is complete.

## Current Workstreams

- `dialo-6`: connector Phase A boundary cleanup
- `dialo-8`: connector Phase B rename/cutover
- `dialo-7`: Journey Builder / classifier work

## How To Use This Scaffold

If you are working on connector architecture:

- start in `wati-to-supabase/`
- put product docs in `wati-to-supabase/docs/`
- put contract notes in `wati-to-supabase/contracts/`
- put runtime-boundary notes in `wati-to-supabase/runtime/`
- put CLI/admin UX notes in `wati-to-supabase/cli/`
- start from the seeded files:
  - `wati-to-supabase/contracts/canonical-contract.md`
  - `wati-to-supabase/contracts/staging-semantics.md`
  - `wati-to-supabase/contracts/tenant-connectors-model.md`
  - `wati-to-supabase/runtime/phase-a-boundary-cleanup.md`
  - `wati-to-supabase/runtime/phase-b-rename-cutover.md`
  - `wati-to-supabase/cli/README.md`

If you are working on Journey Builder:

- start in `journey-builder/`
- the first frontend rail lives in `journey-builder/app/`
- put product docs in `journey-builder/docs/`
- put contract notes in `journey-builder/contracts/`
- put runtime/app-boundary notes in `journey-builder/runtime/`
- put product UI boundary notes in `journey-builder/ui/`
- start from the seeded files:
  - `journey-builder/app/README.md`
  - `journey-builder/contracts/classifier-input-contract.md`
  - `journey-builder/contracts/trait-inference-model.md`
  - `journey-builder/contracts/journey-routing-model.md`
  - `journey-builder/docs/product-scope.md`
  - `journey-builder/ui/README.md`

If something should be shared and neutral:

- put it under `shared/`
- use `shared/runtime/` for non-UI shared runtime code as Phase A extracts it

Default rule:

- if code is connector-specific, it does not belong to Journey Builder
- if code is journey/classifier-specific, it does not belong to the connector
- if both products need it, it probably belongs in `shared/`
