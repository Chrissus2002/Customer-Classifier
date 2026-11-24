<!-- molds
id: dialo-7
stage: design
resume_stage: 
parent: 
deps: 
priority: P2
created_at: 2026-04-15T16:28:23Z
updated_at: 2026-04-18T13:43:36Z
closed_at: 
defer_until: 
code_branch: 
cast_until: inherit
-->


# Productize jbuild on canonical conversations

## TL;DR

- Define `jbuild` as the standalone headless product for conversation
  intelligence over canonical conversations.
- Keep provider and database details behind adapters; product contracts, CLI,
  API, and core code use only product vocabulary.
- The product stack is traits, routing, enrollments, journey-stage
  classification, inspector, analytics, and audiences.
- This umbrella coordinates `dialo-9`, `dialo-10`, `dialo-11`, `dialo-12`,
  `dialo-13`, and `dialo-14`.

## Reader Guide

Read these first:

1. `docs/PRODUCT_MAP.md`
2. `journey-builder/README.md`
3. `journey-builder/docs/product-scope.md`
4. `journey-builder/contracts/classifier-input-contract.md`
5. `journey-builder/contracts/trait-inference-model.md`
6. `journey-builder/contracts/journey-routing-model.md`

Then inspect implementation surfaces only through the current product split:

- `journey-builder/jbuild/core/`
- `journey-builder/jbuild/adapters/`
- `journey-builder/jbuild/api/`
- `journey-builder/jbuild/cli/`
- `journey-builder/app/src/`
- legacy Streamlit/scripts/database files as compatibility or adapter inputs,
  not as the product contract

## Problem

The original Dialo app mixed three concerns:

- connector behavior that gets data from a provider into a canonical form
- product behavior that reasons over canonical conversations
- dashboard and export behavior that exposed the old global-funnel model

The reusable part is the conversation intelligence product. It needs a stable
contract and headless runtime shape so it can be used with CSV uploads, API
imports, Wati-derived data, or another future connector.

The old product model was too flat:

- one tenant-global classifier config
- one tenant-global stage taxonomy
- one latest stage result per owner
- no first-class trait layer
- no deterministic routing layer
- no explicit current enrollment
- analytics that assumed one global funnel

That model cannot support multiple journeys cleanly. It also makes users think
the product is tied to one provider or one database layout when the real
contract is canonical conversations plus normalized product state.

## Product Contract

`jbuild` should expose these concepts to users and API/CLI clients:

- canonical owner
- message
- trait
- Trait Classifier
- journey
- routing rule
- enrollment
- journey version
- stage
- stage result
- inspector state
- audience
- import

`jbuild` should not expose these concepts as product language:

- provider webhook payloads
- provider credential state
- physical database layer names
- adapter table names
- connector runtime health
- provider-specific campaign import instructions

The canonical input contract requires:

- stable owner identity
- stable message identity where available
- timestamped messages
- stable direction semantics: customer, business, system
- usable text content
- optional metadata and provenance

## Solution

Build `jbuild` as a headless product engine with adapter-backed persistence.

### Core Stack

1. Canonical conversations
   - owners and messages arrive through an adapter
   - connector-specific normalization happens before `jbuild` logic

2. Traits
   - reusable attributes on a canonical owner
   - sources: imported, rule, manual, classifier
   - source precedence and provenance are explicit

3. Routing
   - deterministic assignment into one current journey
   - ordered first-match rules plus one fallback
   - rules read resolved traits only

4. Enrollments
   - one current enrollment per canonical owner in v1
   - enrollment freshness invalidates downstream stage results

5. Journey-stage classification
   - one active journey version per journey
   - stage definitions are versioned
   - current result is scoped to owner plus journey

6. Reads and audiences
   - inspector explains the current causal chain
   - analytics summarize current journey/enrollment/stage state
   - audiences are filters over current-state reads

### Adapter Boundary

Core modules should depend on store protocols, not runtime-specific clients:

- `TraitStore`
- `RoutingStore`
- future `ClassificationStore`
- future `ReadStore`
- future `ImportStore`

The first Supabase adapter can map those stores to existing schema files and
RPCs. That mapping must remain inside `journey-builder/jbuild/adapters/` and
the database schema files. CLI/API/product docs should use product names.

### UI Boundary

React is a client. It should not own:

- trait precedence
- routing evaluation
- draft activation
- stale detection
- current-state joins
- audience semantics

Legacy Streamlit screens and scripts can be kept as references or adapters, but
they should not remain the source of truth for `jbuild`.

### Build Surface Alignment

Product docs live in `journey-builder/README.md`,
`journey-builder/docs/product-scope.md`,
`journey-builder/contracts/classifier-input-contract.md`,
`journey-builder/contracts/trait-inference-model.md`,
`journey-builder/contracts/journey-routing-model.md`, and
`docs/PRODUCT_MAP.md`. Core implementation belongs in
`journey-builder/jbuild/core/`, runtime mappings in
`journey-builder/jbuild/adapters/`, HTTP wrappers in
`journey-builder/jbuild/api/`, and command wrappers in
`journey-builder/jbuild/cli/`. React work under `journey-builder/app/src/`
must remain a client, while `app/`, `scripts/`, and `database/` are legacy or
adapter surfaces unless a child mold says otherwise.

## Child Molds

- `dialo-9`: traits and Trait Classifiers
- `dialo-10`: deterministic routing and current enrollments
- `dialo-11`: journey-stage classifier lifecycle
- `dialo-12`: inspector, analytics, and audiences
- `dialo-13`: UI MVP shell
- `dialo-14`: adapter-boundary correction for the first trait slice

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/README.md` | refine | Product home and boundary description |
| `journey-builder/docs/product-scope.md` | refine | Keep scope aligned with adapter-backed product model |
| `journey-builder/contracts/classifier-input-contract.md` | refine | Canonical conversation contract for classifiers |
| `journey-builder/contracts/trait-inference-model.md` | refine | Trait and Trait Classifier contract |
| `journey-builder/contracts/journey-routing-model.md` | refine | Journey, routing, and enrollment contract |
| `journey-builder/jbuild/core/` | refactor | Storage-agnostic product services |
| `journey-builder/jbuild/adapters/` | refactor | Runtime adapter implementations |
| `journey-builder/jbuild/api/` | refactor | Thin HTTP wrappers over core services |
| `journey-builder/jbuild/cli/` | refactor | Headless operator/developer CLI |
| `journey-builder/app/src/` | client | React client for product workflows |
| `app/` | adapter/legacy | Isolate legacy Streamlit behavior from product truth |
| `scripts/` | adapter/legacy | Reuse provider/classifier pieces only behind jbuild boundaries |
| `database/` | adapter schema | Current Supabase adapter schema-as-code |
| `docs/PRODUCT_MAP.md` | refine | Keep product split explicit |

## Verification

- Product docs describe `jbuild` without provider-specific or physical schema
  language.
- Core services depend on store contracts and do not import runtime clients.
- CLI/API names use owner, message, trait, journey, routing, enrollment, stage,
  inspector, audience, and import vocabulary.
- The first Supabase adapter can still run the current implementation without
  leaking table names into the product contract.
- Child molds inherit the same adapter boundary.
- Future builds can run `jbuild` over canonical data without provider
  credentials.
- React remains a client of headless APIs instead of duplicating domain logic.

## Implementation Notes

- This is an umbrella mold. The detailed build work belongs in child molds.
- Do not block product-contract cleanup on a physical schema rename.
- Do not describe CSV/API imports as writes into adapter tables. They are
  writes into canonical messages and imported traits through an adapter.
- Do not make Trait Classifiers mandatory. Imported, manual, rule, and
  classifier sources must coexist.
- Do not turn routing into a generic workflow graph. Deterministic routing plus
  per-journey stage classification is the v1 shape.
- worktree: yes


## Notes

- [2026-04-18T13:43:36Z] Cleanup pass: aligned active jbuild mold language to the adapter-boundary model. Removed legacy medallion/schema vocabulary from user-facing/core contract text, kept product terms and store/adapter boundaries, and verified the design gate passes cleanly.
