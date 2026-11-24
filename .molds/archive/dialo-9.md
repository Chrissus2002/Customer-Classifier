<!-- molds
id: dialo-9
stage: closed
resume_stage: 
parent: dialo-7
deps: 
priority: P2
created_at: 2026-04-16T10:01:47Z
updated_at: 2026-04-18T11:09:27Z
closed_at: 2026-04-18T11:09:27Z
defer_until: 
code_branch: mold/dialo-9
cast_until: inherit
-->







# jbuild — Chat traits and Trait Classifiers

## TL;DR

- Build the first headless `jbuild` slice: trait definitions, current trait
  values, Trait Classifier drafts/tests/activation, and the importable package
  skeleton that later molds extend.
- Treat product “chat traits” as resolved attributes on the current canonical
  chat owner. In v1 that owner is existing `silver.contacts.contact_id`, not a
  new `chat_id` table or unstable `conversation_id`.
- Store current trait values only, with explicit unresolved vs `unknown`,
  source/confidence/reasoning metadata, and Postgres-enforced precedence so
  manual/imported/rule/classifier writes cannot race each other.
- Keep Trait Classifiers separate from Journey classifiers: one narrow
  per-trait draft/test/activate lifecycle, allowed-value snapshots per config
  version, and no tenant-global classifier fallback.
- Implement Python code under an importable `journey-builder/jbuild/` package,
  expose `./jbuild` CLI and FastAPI routes as thin wrappers over core services,
  and keep React/Streamlit as clients or adapters only.
- Stop before routing. The deliverable is trustworthy resolved trait values
  plus the package/API/CLI substrate for `dialo-10`, `dialo-11`, and `dialo-12`.

## Problem

`dialo-7` established that traits should be chat-level attributes, not vague
global metadata and not journey stages. But the repo still has no dedicated
model for:

- trait definitions
- resolved trait values on the current canonical chat owner
- Trait Classifier configs and versions
- source precedence between imported/Supabase/rule/manual/classifier values

Without this slice, routing has nothing concrete to read and any UI keeps
talking about “traits” without a stable storage and resolution contract. In the
headless model, that contract must be callable without a browser: core services
own behavior, the `jbuild` CLI and API expose it, and React becomes only one
client.

Ground-truth code audit:

- today the classifier groups message history by `silver.messages.contact_id`
  in `scripts/classifiers/orchestrator.py`
- `silver.contacts.contact_id` is the only stable canonical thread-like unit in
  the current model
- `silver.messages.conversation_id` exists, but the ingest path explicitly
  falls back to sentinel values like `'Conversation had no ID'`, so it is not a
  safe v1 trait anchor
- the current app/database helpers and analytics all assume `contact_id`, not a
  separate chat entity
- `app/database.py` is a Streamlit-era adapter with caching concerns; it should
  not become the long-term service layer for `jbuild`
- the current classifier activation flow already uses a DB RPC
  (`public.activate_classifier_config`) because client-side sequential writes
  are not safe enough for state that must stay singular

One more hidden constraint from the codebase:

- if multiple sources can write the current trait row, a plain
  `app/database.py` upsert helper will not be strong enough to enforce
  precedence safely under concurrency
- this mold therefore needs an explicit DB-side write contract, not just table
  definitions
- `silver.merge_contacts()` already has to move contact-owned state manually;
  anything keyed by `contact_id` will need explicit merge behavior rather than
  assuming the table can be ignored safely

That means this mold must answer a concrete design question before build:

- do we introduce a new `chat_id` entity now, or
- do we anchor trait values on existing canonical `contact_id` and document
  that as the v1 “chat” unit?

My read from the code is that the second option is the safer first-principles
decision for v1.

Non-goals:

- routing rules
- journey enrollments
- journey stage classification
- analytics surfaces beyond what is needed to inspect one resolved trait value

## Solution

Add the first buildable layer for `jbuild`:

- define trait definitions and typed current values on the v1 canonical owner
- define first-class Trait Classifiers for model-backed trait resolution
- define resolution/source precedence
- make trait values inspectable with source, confidence, and reasoning
- create the headless core/API/CLI skeleton that later `dialo-10`, `dialo-11`,
  and `dialo-12` extend

### Headless implementation posture

`jbuild` should be implemented as a headless product engine first:

- `journey-builder/jbuild/core/traits.py` owns trait domain behavior and calls
  the required Supabase tables/RPCs
- `journey-builder/jbuild/core/trait_classifier.py` adapts the existing LLM
  provider/factory code without leaking `journey_stage` into the trait domain
- `journey-builder/jbuild/api/main.py` creates a FastAPI app, and
  `journey-builder/jbuild/api/traits.py` exposes HTTP routes that wrap the same
  core services
- `journey-builder/jbuild/cli/main.py` exposes operator and development
  commands under the `jbuild` command
- root `jbuild` follows the existing `wati-supabase` wrapper pattern so local
  use does not depend on an installed package
- `journey-builder/jbuild/workers/trait_classifiers.py` owns async or batch
  trait classifier runs when they stop fitting in a request/response path
- `journey-builder/app/src/` may render trait management later, but it must call
  the API and must not duplicate source precedence, activation, or classifier
  test logic
- `app/database.py` can keep legacy Streamlit compatibility wrappers if needed,
  but new `jbuild` behavior belongs in the core service layer
- `requirements.txt` should add the minimal API runtime dependencies if the
  build uses FastAPI routes, expected to be `fastapi` and `uvicorn`

Example CLI shape:

```bash
jbuild traits list --tenant 310131
jbuild traits create --tenant 310131 --key customer_type --type enum --values retail,wholesale,unknown
jbuild traits values set --tenant 310131 --contact <contact-id> --trait customer_type --value wholesale --source manual
jbuild trait-classifiers draft --tenant 310131 --trait customer_type
jbuild trait-classifiers test --tenant 310131 --trait customer_type --sample 20
jbuild trait-classifiers activate --tenant 310131 --trait customer_type --version 2
```

Example API shape:

```http
GET  /traits
POST /traits
POST /traits/{trait_id}/values
POST /trait-classifiers/{trait_id}/drafts
POST /trait-classifiers/{trait_id}/tests
POST /trait-classifiers/{trait_id}/activate
```

### Recommended v1 decisions

1. Internal anchor
   - use `silver.contacts.contact_id` as the internal trait owner in v1
   - product copy can still say `chat_id`, but schema/build code should not
     invent a second canonical identifier yet
   - leave room to rename or formalize a dedicated chat entity later if the
     canonical contract broadens beyond today’s contact-thread model

2. Current value first
   - store one current resolved trait value per `(tenant_id, contact_id, trait_key)`
   - include `source`, `confidence`, `reasoning`, `classifier_version`,
     `resolved_at`, and raw provenance metadata where useful
   - defer full trait-history/event-sourcing to a later mold unless a concrete
     auditing need appears during design
   - distinguish clearly between:
     - no row = unresolved / not yet computed
     - explicit `unknown` value = resolved but unknown

3. Trait Classifier as first-class config
   - separate tables from journey classifier config
   - one classifier family per trait, with versions/activation state
   - support the same conceptual lifecycle as Journey classifiers, but do not
     force the full Studio UI into this first build slice
   - each config version must snapshot the label set it classifies against;
     do not rely on the current mutable trait definition alone

4. Source precedence
   - explicit precedence order in the model and helpers
   - likely: manual > imported/Supabase > rule > classifier
   - classifier should fill gaps, not overwrite stronger business truth by
     default

5. Name honesty
   - keep the DB and helper layer honest in v1: use `contact_id`
   - product copy can explain that `jbuild` is operating on the current
     canonical chat-thread owner, which today is `contact_id`
   - do not introduce a half-real `chat_id` alias in SQL or helper APIs during
     this slice

6. Trait Classifier lifecycle
   - yes, Trait Classifiers should get a real per-trait
     `draft -> test -> activate` lifecycle in v1
   - keep it narrow: at most one active config and one mutable draft per
     `(tenant, trait)`
   - do not support branching drafts or cohort rollouts in this slice

7. Atomic precedence
   - current-value trait writes should go through a DB-side function/RPC
   - do not implement precedence via client-side read/compare/write
   - this follows the same first-principles reasoning that already justified
     `public.activate_classifier_config`

8. Narrow v1 client UI
   - the React client can show definitions, current resolver, and coverage
   - Trait Classifiers should be visible as first-class objects through the API
     before UI controls depend on them
   - contact/chat-level inspection belongs in later molds; this mold only needs
     enough headless surface to prove the model is coherent

9. Merge-aware ownership
   - because trait rows are keyed by `contact_id`, manual contact merges must
     reconcile `silver.contact_trait_values`
   - when both source and target contacts have a value for the same trait, the
     merge path should apply the same precedence rules used for normal writes
   - do not copy the current “best effort” pattern where some contact-owned
     tables are updated and others are silently left behind

10. Python package and API boundary
   - keep the existing `journey-builder/` directory as the product home, but do
     not put importable Python modules directly under a hyphenated package name
   - create `journey-builder/jbuild/` with normal `__init__.py` files, then run
     tests and CLI commands with `PYTHONPATH=journey-builder` or the root
     `./jbuild` wrapper
   - use `click`, already present in `requirements.txt`, for the CLI
   - use FastAPI for HTTP route definitions and add the missing dependency rows
     to `requirements.txt` during build
   - API route modules should be thin transport adapters over core services;
     they should not import Streamlit or React code

### Exact v1 schema proposal

1. `public.tenant_trait_definitions`
   - purpose: durable trait catalog per tenant
   - columns:
     - `trait_id UUID PRIMARY KEY`
     - `tenant_id BIGINT NOT NULL`
     - `trait_key TEXT NOT NULL`
     - `display_label TEXT NOT NULL`
     - `description TEXT`
     - `value_type TEXT NOT NULL`
     - `allowed_values JSONB`
     - `resolver_mode TEXT NOT NULL DEFAULT 'mixed'`
     - `is_active BOOLEAN NOT NULL DEFAULT TRUE`
     - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - constraints:
     - `UNIQUE(tenant_id, trait_key)`
     - keep `value_type` intentionally narrow in v1: `enum`, `boolean`, `text`
     - `allowed_values` should stay simple in v1: JSON array of strings for
       enum-like traits, nullable otherwise
     - keep numeric/range-heavy traits out of scope if they complicate routing

2. `public.tenant_trait_classifier_configs`
   - purpose: first-class classifier configs for one trait
   - columns:
     - `config_id UUID PRIMARY KEY`
     - `tenant_id BIGINT NOT NULL`
     - `trait_id UUID NOT NULL REFERENCES public.tenant_trait_definitions(trait_id)`
     - `version INTEGER NOT NULL`
     - `master_prompt TEXT NOT NULL`
     - `provider TEXT`
     - `model TEXT`
     - `allowed_values_snapshot JSONB NOT NULL`
     - `is_active BOOLEAN NOT NULL DEFAULT FALSE`
     - `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `activated_at TIMESTAMPTZ`
     - `notes TEXT`
   - constraints:
     - `UNIQUE(tenant_id, trait_id, version)`
     - one active config per `(tenant_id, trait_id)`
   - note:
     - v1 can still avoid a child table like `tenant_journey_stages`, but only
       if each config snapshots the allowed values it was authored/tested with
     - mirror the current draft convention: the most recent inactive row is the
       mutable draft for that trait
     - treat edits to `tenant_trait_definitions.allowed_values` as current
       trait-definition changes, not retroactive mutation of old classifier
       versions

3. `silver.contact_trait_values`
   - purpose: current resolved trait value on the canonical contact/chat owner
   - columns:
     - `trait_value_id UUID PRIMARY KEY`
     - `tenant_id BIGINT NOT NULL`
     - `contact_id UUID NOT NULL REFERENCES silver.contacts(contact_id)`
     - `trait_id UUID NOT NULL REFERENCES public.tenant_trait_definitions(trait_id)`
     - `resolved_value TEXT NOT NULL`
     - `resolution_source TEXT NOT NULL`
     - `confidence FLOAT`
     - `reasoning TEXT`
     - `classifier_version TEXT`
     - `source_metadata JSONB`
     - `resolved_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
     - `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`
   - constraints:
     - `UNIQUE(tenant_id, contact_id, trait_id)`
   - indexes:
     - `(tenant_id, trait_id, resolved_value)`
     - `(contact_id)`
   - note:
     - use normalized textual storage for v1 routing simplicity; the
       definition table still carries `value_type` and allowed-values metadata
     - store the current resolved value only; this table is not a history log
     - keep `resolved_value NOT NULL`; unresolved should mean “no row”
     - enum-like traits that need an explicit unknown state should include
       `"unknown"` in `allowed_values`

### Exact v1 database functions

1. `public.activate_trait_classifier_config(p_tenant_id BIGINT, p_trait_id UUID, p_config_id UUID)`
   - purpose: atomically swap the active Trait Classifier config for one trait
   - pattern: mirror `public.activate_classifier_config`, but scope the
     uniqueness to `(tenant, trait)`

2. `public.upsert_contact_trait_values(p_tenant_id BIGINT, p_rows JSONB)`
   - purpose: apply one or more current-value trait resolutions atomically
   - input row shape:
     - `contact_id`
     - `trait_id`
     - `resolved_value`
     - `resolution_source`
     - `confidence`
     - `reasoning`
     - `classifier_version`
     - `source_metadata`
     - `resolved_at`
   - required behavior:
     - insert when no row exists
     - update when incoming source outranks existing source
     - update when source is the same and the incoming resolution is newer
     - reject or ignore lower-precedence writes by default
   - reason:
     - imported/manual/classifier writes will eventually race; precedence must
       be enforced where the data lives

3. extend `silver.merge_contacts(...)`
   - purpose: reconcile trait rows when one canonical contact absorbs another
   - required behavior:
     - move trait rows from source contact to target when target has no row
     - resolve conflicts by source precedence first, then by newer resolution
     - preserve auditability via existing merge audit trail rather than adding a
       second trait-history system in this slice

### Exact v1 source precedence

Keep precedence global and explicit in v1.

Canonical `resolution_source` strings:

1. `manual`
2. `imported`
3. `rule`
4. `classifier`

Implementation rule:

- trusted Supabase-backed values should enter as `imported` with provenance in
  `source_metadata` unless a later mold proves a separate source is needed
- stronger sources win by default
- Trait Classifiers fill gaps and low-confidence cases; they do not overwrite
  stronger business truth unless an operator explicitly requests it

### Exact v1 versioning rule

- `tenant_trait_definitions` stores the current canonical trait definition
- `tenant_trait_classifier_configs.allowed_values_snapshot` stores the label set
  that a specific classifier version was authored/tested against
- classification runs should use the config snapshot, not the live mutable
  trait definition
- changing a trait's allowed values should lead to a new Trait Classifier draft
  or version, not silent reinterpretation of old versions

### Reuse vs new code

Reuse:

- the existing provider/factory behavior in `scripts/classifiers/base.py` and
  `scripts/classifiers/factory.py`, but only behind a `jbuild` adapter
- the general draft/save/activate/version-history pattern already used by
  `tenant_classifier_configs` helpers in `app/database.py`

Do not reuse blindly:

- `scripts/classifiers/models.py` because `ClassificationResult.journey_stage`
  is journey-specific language
- `scripts/classifiers/orchestrator.py` because it is tenant-global and assumes
  one active classifier config per tenant

Recommended new module boundary:

- `journey-builder/jbuild/core/trait_classifier.py`
  - compose trait-classifier prompts
  - load contact messages through core data access
  - call the existing provider factory behind an adapter
  - convert the existing `journey_stage`-named provider result into a
    trait-domain result before returning from `jbuild`
- do not create `scripts/trait_classifiers/`; new product behavior belongs in
  the `jbuild` package and legacy scripts should only delegate later if needed

### Recommended core/API/CLI surface

Add core service functions under `journey-builder/jbuild/core/traits.py`, then
expose them through `journey-builder/jbuild/api/traits.py` and the `jbuild` CLI.
Legacy Streamlit wrappers may delegate to these services, but they should not
own the business behavior.

Core service methods:

- `list_trait_definitions(tenant_id)`
- `create_or_update_trait_definition(...)`
- `get_active_trait_classifier_config(tenant_id, trait_id)`
- `get_draft_trait_classifier_config(tenant_id, trait_id)`
- `save_trait_classifier_draft(...)`
- `test_trait_classifier_config(tenant_id, trait_id, config_id, sample_contact_ids=None)`
- `activate_trait_classifier_config(...)`
- `get_trait_classifier_version_history(tenant_id, trait_id)`
- `upsert_contact_trait_values(rows)` via RPC, not naive table upsert
- `get_contact_trait_values(tenant_id, contact_ids=None, trait_keys=None)`
- save/test paths should always read labels from `allowed_values_snapshot`, not
  from the mutable current trait definition

CLI command families:

- `jbuild traits ...`
- `jbuild traits values ...`
- `jbuild trait-classifiers ...`

API route families:

- `/traits`
- `/traits/{trait_id}/values`
- `/trait-classifiers/{trait_id}/...`

### Build surface alignment

The build should update the product contract in
`journey-builder/contracts/trait-inference-model.md` and keep
`journey-builder/docs/product-scope.md` honest about `contact_id` as the v1
internal chat owner. Headless behavior belongs in `journey-builder/jbuild/`,
especially `journey-builder/jbuild/core/`,
`journey-builder/jbuild/core/traits.py`, and
`journey-builder/jbuild/core/trait_classifier.py`, with HTTP exposure in
`journey-builder/jbuild/api/`, `journey-builder/jbuild/api/main.py`, and
`journey-builder/jbuild/api/traits.py`, CLI exposure in
`journey-builder/jbuild/cli/`, `journey-builder/jbuild/cli/main.py`, and the
root `jbuild` wrapper, and optional async execution in
`journey-builder/jbuild/workers/` and
`journey-builder/jbuild/workers/trait_classifiers.py`. API dependencies belong
in `requirements.txt`. Persistence still requires `database/03_silver_layer.sql`,
`database/04_rls_policies.sql`, and `database/05_functions.sql`. Provider reuse
should stay limited to `scripts/classifiers/base.py` and
`scripts/classifiers/factory.py`. Legacy `app/database.py` may delegate only as
an adapter, and React work in `journey-builder/app/src/` is client-only.
Verification belongs in `tests/unit/`, `tests/unit/test_jbuild_traits.py`,
`tests/unit/test_jbuild_cli.py`, `tests/unit/test_jbuild_api.py`, and
`tests/unit/test_sql_contracts.py`.

Resolved v1 calls after this pass:

- keep `contact_id` as the stored/internal key for this slice
- keep precedence global and explicit in v1; trait-specific override rules can
  wait for a later mold if a real use case appears
- give Trait Classifiers their own narrow draft/test/activate lifecycle in v1
- create an importable `journey-builder/jbuild/` package and root `jbuild`
  wrapper instead of trying to import from the hyphenated product directory
- reuse provider/base layers behind an adapter, but not journey-specific result
  models or the tenant-global journey orchestrator
- keep unresolved distinct from explicit `unknown`
- standardize the source string for model-backed values as `classifier`, not
  `model`, and update the product contract during build
- update the existing merge path instead of pretending `contact_id`-owned trait
  rows never face merge conflicts
- snapshot allowed values per Trait Classifier config version so version history
  remains meaningful after trait-definition edits

## Files to Modify
| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/contracts/trait-inference-model.md` | refine | Turn the current concept doc into a concrete build contract |
| `journey-builder/docs/product-scope.md` | refine later | Keep the product language honest about chat_id vs current canonical contact anchor |
| `requirements.txt` | refactor later | Add minimal HTTP API runtime dependencies, expected `fastapi` and `uvicorn` |
| `jbuild` | create | Root wrapper that runs the local CLI with `PYTHONPATH=journey-builder`, mirroring `wati-supabase` |
| `journey-builder/jbuild/` | create | Importable Python package for the headless `jbuild` runtime |
| `journey-builder/jbuild/core/` | create | Headless `jbuild` core service package; trait behavior starts here |
| `journey-builder/jbuild/core/traits.py` | create | Trait definitions, classifier config reads/writes, value reads/writes, and RPC delegation |
| `journey-builder/jbuild/core/trait_classifier.py` | create | Trait Classifier orchestration and adapter around existing provider/factory code |
| `journey-builder/jbuild/api/` | create | FastAPI package for `jbuild` clients |
| `journey-builder/jbuild/api/main.py` | create | FastAPI app entrypoint and router registration |
| `journey-builder/jbuild/api/traits.py` | create | Trait and Trait Classifier routes wrapping core services |
| `journey-builder/jbuild/cli/` | create | CLI package exposing the `jbuild` command |
| `journey-builder/jbuild/cli/main.py` | create | `jbuild traits` and `jbuild trait-classifiers` command tree |
| `journey-builder/jbuild/workers/` | create later | Async/batch execution home for Trait Classifier runs when needed |
| `journey-builder/jbuild/workers/trait_classifiers.py` | create later | Batch Trait Classifier runner if request/response tests become too slow |
| `database/03_silver_layer.sql` | refactor later | Add trait definition / trait value / Trait Classifier tables |
| `database/04_rls_policies.sql` | refactor later | Add tenant isolation policies for new silver/public trait tables; do not widen this slice into a legacy RLS reorganization |
| `database/05_functions.sql` | refactor later | Add atomic activation and precedence-enforcing write functions for Trait Classifiers and trait values |
| `app/database.py` | adapter later | Keep legacy Streamlit wrappers only if needed; delegate to `jbuild` core rather than owning new behavior |
| `scripts/classifiers/base.py` | reuse | Shared provider-agnostic classify interface |
| `scripts/classifiers/factory.py` | reuse/refine later | Reuse provider factory for Trait Classifiers |
| `journey-builder/app/src/` | client later | React client should call the `jbuild` API; no duplicated precedence or activation logic |
| `tests/unit/` | create later | Add unit coverage for precedence, trait-classifier lifecycle, and merge-conflict resolution |
| `tests/unit/test_jbuild_traits.py` | create | Core service and precedence tests for trait definitions, values, and classifier config lifecycle |
| `tests/unit/test_jbuild_cli.py` | create | CLI smoke tests for `jbuild traits` and `jbuild trait-classifiers` command wiring |
| `tests/unit/test_jbuild_api.py` | create | API route smoke tests that prove routes delegate to core services without Streamlit/React dependencies |
| `tests/unit/test_sql_contracts.py` | refactor later | Cover the new SQL function contract for activation, precedence, and merge behavior |

## Verification

- Trait definitions exist with stable keys and typed value contracts
- One resolved trait value can be stored and read for the chosen canonical chat
  owner in v1
- Resolution source is explicit: imported / Supabase / rule / manual / classifier
- A Trait Classifier is modeled separately from Journey classifier config
- Trait evidence is inspectable enough for routing and inspector work later
- The build does not invent a second unstable “chat id” concept that conflicts
  with current `contact_id`-based classifier code
- One active Trait Classifier config can exist per `(tenant, trait)`
- Current-value writes respect source precedence and do not overwrite stronger
  sources by default
- Precedence enforcement happens atomically in the DB, not via naive
  read-compare-write client code
- Trait Classifiers support a real per-trait draft/test/activate flow without
  introducing tenant-global classifier assumptions
- Unresolved and explicit `unknown` are distinct states
- Contact merges preserve or reconcile trait rows correctly instead of leaving
  orphaned contact-owned truth behind
- A historical Trait Classifier version still knows exactly which labels it was
  tested and activated with, even if the trait definition changes later
- The same trait definition, value write, draft/test/activate, and read paths
  are callable through core services, `jbuild` CLI commands, and HTTP API routes
- `PYTHONPATH=journey-builder python -m jbuild.cli.main --help` and the root
  `./jbuild --help` path both reach the CLI without importing from a hyphenated
  Python package name
- FastAPI route modules can be imported and tested without Streamlit, React, or
  a running Vite app
- Existing classifier provider results are adapted into trait-domain results;
  public `jbuild` APIs do not expose a `journey_stage` field for Trait
  Classifier output
- `journey-builder/contracts/trait-inference-model.md` uses the same canonical
  `resolution_source` names as the SQL/core implementation
- React, if touched in this slice, is only a client of the `jbuild` API and does
  not implement source precedence, activation, or classifier test semantics

## Implementation Notes

- This mold should produce the substrate for later routing work, not try to
  solve routing itself.
- This mold also establishes the first headless `jbuild` package shape for
  later molds. Keep the skeleton small but real: core service, CLI entry point,
  API route module, and tests around core behavior.
- worktree: yes
- Do not place importable Python modules directly at `journey-builder/core/`;
  that path reads nicely in prose but the hyphenated parent directory makes a
  real package awkward. Use `journey-builder/jbuild/` for Python modules.
- The API dependency decision is now explicit: if HTTP routes land in this
  mold, add FastAPI and uvicorn to `requirements.txt` in the same commit.
- Keep the language sharp: traits are chat attributes, Trait Classifiers are
  first-class classifiers, and neither is a journey stage.
- If this mold does not end with a clear `chat_id -> resolved trait values`
  contract, later molds will stay muddy.
- If the implementation introduces both `contact_id` and a new `chat_id`
  without a strict mapping contract, it will likely make later molds harder,
  not easier.
- The main simplification to protect is scope: current values only, narrow
  trait types, one draft per trait, and no history engine.
- Do not let this slice expand into a full legacy-RLS cleanup just because the
  current repo has mixed placement for policies. Add the needed new policies and
  move on.
- Snapshotting labels on config is the minimal version-safe substitute for a
  full child-table design like `tenant_journey_stages`.
- Maturity: late design after this pass. The next design pass should critique
  or simplify the exact build cut, not revisit first principles.


## Notes

- [2026-04-18T09:54:28Z] gate: action=design_approved kind=approval from=design to=build actor="dev"
- [2026-04-18T10:24:55Z] Build implemented headless jbuild trait slice: schema/RLS/RPCs, importable jbuild core/API/CLI/workers, docs contract updates, and focused tests. Verification passed: focused jbuild tests 21/21 and full pytest tests 80/80 in repo venv.
- [2026-04-18T10:25:46Z] build complete: action=build_passed from=build to=qa branch=mold/dialo-9
- [2026-04-18T10:53:14Z] QA passed after hardening trait value and Trait Classifier draft contracts. Verification passed: full pytest tests 81/81, CLI help, root ./jbuild help, API route import, and git diff --check. action=qa_passed from=qa to=land branch=mold/dialo-9

- [2026-04-18T11:09:23Z] QA freshness override: markdown-mode payload has no qa_freshness field; branch notes show QA passed at 2026-04-18T10:53:14Z, and landing verification on main passed with full pytest 81/81, CLI help, root ./jbuild help, API route import, and git diff --check.

- [2026-04-18T11:09:27Z] gate: action=land_accepted kind=approval from=land to=closed actor="dev"
