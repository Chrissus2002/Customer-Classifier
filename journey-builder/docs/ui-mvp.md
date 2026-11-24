# Journey Builder UI MVP

Concrete MVP cut for the first real Journey Builder frontend.

The goal is not to ship the full product model at once. The goal is to ship
one coherent operator loop that feels real, teaches the product clearly, and
leaves clean rails for later expansion.

## MVP Principle

Build the smallest UI that supports this loop:

1. See the list of journeys
2. Open one journey
3. Edit its prompt and stages
4. Test the draft against sample contacts
5. Activate the draft
6. Inspect one contact and understand why it landed where it did

Everything else can stay read-only or mocked for now.

## MVP Surfaces

### 1. Journeys

Primary landing page.

Purpose:

- show the stable set of journeys
- show which version is active
- show whether a draft exists
- show high-level counts for enrolled and stale contacts
- open one journey into Journey Studio

Required cards/fields:

- journey display label
- journey key
- active version
- draft exists yes/no
- enrolled count
- stale count
- last updated

Actions:

- `Open Studio`
- `Create Journey` can be stubbed or disabled in the first pass if needed

### 2. Journey Studio

Primary working screen.

Purpose:

- edit one journey's stages and prompt
- preserve the current product's strongest loop: `draft -> test -> activate`

Required sections:

- header
  - journey label
  - active version
  - draft version
  - unsaved changes state
- stages editor
  - ordered list of stage rows
  - `stage_key`
  - display label
  - description
- prompt editor
  - main prompt text area
  - optional prompt preview panel
- draft notes
- version history list
- test results summary

Required actions:

- `Save Draft`
- `Test Draft`
- `Activate Draft`
- `Restore As Draft`

### 3. Contact Inspector

Trust surface.

Purpose:

- explain the full current-state chain for one contact
- make the classifier and routing output legible

Required sections:

- contact identity
  - name
  - contact id
  - last inbound / last activity
- recent conversation excerpt
- resolved traits
  - trait key
  - value
  - source
  - confidence if present
- routing explanation
  - matched rule
  - routing config version
  - routing reason
- current journey
  - journey label
  - enrollment freshness / reroute state
- current stage
  - stage key
  - display label
  - confidence
  - classified at
  - state: `current`, `stale`, or `missing`

### 4. Traits Summary

Not a full trait-management product yet.

Purpose:

- give users enough context to understand what routing and classification are
  reading
- avoid building the full `dialo-9` management surface in the MVP

Keep it summary-only:

- trait coverage table
- resolver type
- example allowed values
- optional link or placeholder for future Trait Classifier editing

No full CRUD required in the MVP.

### 5. Routing Summary

Not a full routing-builder yet.

Purpose:

- show the current routing logic so the product loop makes sense
- avoid blocking the MVP on a full rule-builder UI

Keep it summary-only:

- ordered rules list
- target journey
- fallback rule marker
- simple preview/diff summary

No drag-and-drop or full rule editing required in the MVP.

## Explicitly Out Of MVP

- full trait definition editor
- full Trait Classifier builder
- full routing rule builder
- journey analytics dashboard overhaul
- audience builder
- provider-specific export UX
- timeline/history explorer
- multi-journey membership
- experiment/canary rollout UI

These should remain clearly out of scope so the MVP lands as one coherent
surface instead of half-implementing four molds at once.

## MVP Route Map

Recommended first route structure:

- `/journeys`
- `/journeys/:journeyKey`
- `/contacts/:contactId`

Recommended behavior:

- `/journeys`
  - journey list plus small right rail for traits/routing summaries
- `/journeys/:journeyKey`
  - Journey Studio as the main screen
- `/contacts/:contactId`
  - Contact Inspector

Avoid adding top-level routes for every future product area yet. The MVP should
feel like one focused workflow rather than a large empty shell.

## Suggested Component Map

Keep the component tree boring and explicit.

### App shell

- `AppShell`
- `SidebarNav`
- `PageHeader`

### Journeys page

- `JourneyListPage`
- `JourneyCard`
- `TraitsSummaryPanel`
- `RoutingSummaryPanel`

### Journey Studio

- `JourneyStudioPage`
- `JourneyHeader`
- `StageListEditor`
- `StageRowEditor`
- `PromptEditor`
- `PromptPreview`
- `DraftNotesEditor`
- `VersionHistoryList`
- `EvalSummaryPanel`

### Contact Inspector

- `ContactInspectorPage`
- `ConversationExcerpt`
- `TraitStatePanel`
- `RoutingExplanationPanel`
- `JourneyStatePanel`
- `StageStatePanel`

## Data Strategy

### Phase 0: mocked-only

Use mocked data to get the experience right first.

Good enough for:

- layout
- navigation
- interaction flow
- visual hierarchy
- naming validation

### Phase 1: partially real

Wire in real reads for:

- journeys list
- one journey detail
- version history
- one contact inspector

Keep writes mocked until the backend tables/functions settle if needed.

### Phase 2: real edit loop

Wire in real:

- save draft
- test draft
- activate draft

Do not block the MVP UI on full traits/routing CRUD.

## Backend Expectations For The MVP

The MVP can start before every child mold is fully built, but it needs a clear
data contract.

Minimum useful real data:

- journeys list
- active version metadata per journey
- stage set for one journey version
- sample eval rows
- current-state inspector payload for one contact

Best current backend alignment:

- `dialo-11` for Journey Studio shape
- `dialo-12` for Contact Inspector shape

Traits and routing can remain summary/mock surfaces until `dialo-9` and
`dialo-10` land fully.

## Build Order

Recommended implementation order:

1. `Journeys` page
2. `Journey Studio` layout
3. `Contact Inspector`
4. traits summary panel
5. routing summary panel
6. connect read data
7. connect draft/test/activate writes

This order gets the highest-signal workflow in front of you fastest.

## What Christian Should Inherit Later

Once the MVP lands, later expansion should be straightforward:

- expand traits summary into a real trait-management surface
- expand routing summary into a rule builder
- add journey analytics pages
- add audience generation
- add deeper evaluation tooling

That means the MVP should optimize for a clean component boundary and a clean
product story, not for feature completeness.


## Related implementation plan

- `journey-builder/docs/ui-implementation-checklist.md`
