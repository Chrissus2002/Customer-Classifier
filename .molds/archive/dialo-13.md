<!-- molds
id: dialo-13
stage: closed
resume_stage: 
parent: dialo-7
deps: 
priority: P2
created_at: 2026-04-17T08:25:00Z
updated_at: 2026-04-17T13:49:38Z
closed_at: 2026-04-17T13:49:38Z
defer_until: 
code_branch: mold/dialo-13
cast_until: inherit
-->



# Journey Builder — UI MVP shell and route refactor

## TL;DR

- Build the first real Journey Builder frontend as a focused MVP, not as a wireframe review deck.
- Replace the current `gallery` / `focus` app shape with three real routes: `/journeys`, `/journeys/:journeyKey`, and `/contacts/:contactId`.
- Lock the implementation to URL-driven navigation with `react-router-dom`; do not keep the MVP on in-memory surface toggles.
- Require stable mock route identifiers (`journeyKey`, `contactId`) and explicit empty/not-found states for unknown route params so the shell behaves like a real product even before live data wiring.
- Clarify route behavior for `/`, unknown paths, and inspector navigation so the first build does not fake a top-level page model that the product does not really have.
- Keep `Traits` and `Routing` visible, but only as summary panels in this slice; do not build their full CRUD/editor surfaces yet.
- Make `Journey Studio` the primary working screen and fold `Eval + Activate` into that page instead of keeping it as a separate top-level surface.
- Keep the whole slice mock-first so it can be built now without waiting for every backend mold to land; real data wiring can follow on top of the same page/component structure.
- The product goal of this mold is to give Manuel a real UI to build now and give Christian a clean continuation path later.

## Problem

The current React app in `journey-builder/app/` is still a review artifact, not a product shell.

Ground-truth code audit:

- `journey-builder/app/src/App.tsx` is one large file that renders all major surfaces directly.
- The current app still uses `gallery` and `focus` review modes rather than real product routes.
- `Traits`, `Routing`, `Journeys`, `Journey Studio`, `Eval + Activate`, and `Contact Inspector` are all treated as equal top-level mock screens.
- Global UI framing like `Wireframe review`, `Gallery`, and `Focus` still makes the app feel like a design deck rather than a product.
- `Eval + Activate` is still modeled as its own top-level surface, even though the intended operator workflow clearly wants it embedded in `Journey Studio`.
- The current scaffold is useful for visual review, but if implementation begins directly on top of it without narrowing scope, the build will drift into trying to solve `dialo-9`, `dialo-10`, `dialo-11`, and `dialo-12` all at once.

That creates two practical risks:

1. the first real UI build becomes too broad and slow
2. the page/component structure will optimize for mock review instead of for the product workflow

The MVP needs to be explicit enough that someone can start building immediately without re-deciding the app shape.

## Solution

Build a mock-first UI MVP that turns the current Vite scaffold into one coherent operator flow.

### MVP workflow

The first real Journey Builder UI should support this loop:

1. see the list of journeys
2. open one journey
3. edit prompt and stages
4. test the draft
5. activate the draft
6. inspect one contact and understand why it landed where it did

That implies a smaller app than the current wireframe gallery.

### Route model

Use three real routes in this slice.

Locked decision for this pass:

- use `react-router-dom` in v1
- route params, not component-local selected state, are the source of truth for the active journey/contact screen
- `/` should redirect to `/journeys`
- unknown routes should render an explicit product-level not-found page, not a silent redirect
- the sidebar should navigate only between real top-level MVP destinations; `Traits`, `Routing`, and `Eval + Activate` should not survive as first-class nav items
- `Contact Inspector` is a real route, but should usually be reached contextually from journey/contact links rather than promoted as the main global destination in the sidebar
- do not add a global client-state library like Zustand, Redux, or React Query in this slice
- keep page data mock-first and colocated with the page/component tree until real backend reads are added later
- route params must resolve against stable mock identifiers, not array indices or implicit first-row defaults

Use three real routes in this slice:

1. `/journeys`
   - landing page
   - journey cards list
   - traits summary panel
   - routing summary panel
   - recent changes block optional

2. `/journeys/:journeyKey`
   - `Journey Studio`
   - journey header
   - stage editor
   - prompt editor
   - draft notes
   - version history
   - `Eval + Activate` summary built into the page

3. `/contacts/:contactId`
   - `Contact Inspector`
   - reached from contextual links in journeys/studio flows
   - recent conversation excerpt
   - resolved traits
   - routing explanation
   - current journey state
   - current stage state

### Deliberate scope cut

This mold is intentionally narrower than the full Journey Builder product plan.

Included:

- route structure
- page/component extraction from the monolithic `App.tsx`
- `Journeys` page
- `Journey Studio` page
- `Contact Inspector` page
- traits summary panel
- routing summary panel
- redistribution of current mock content into reusable page/component modules
- styling cleanup so the app feels like a product shell rather than a review board

Excluded:

- full trait definition CRUD
- full Trait Classifier builder
- full routing rule builder
- full analytics dashboard overhaul
- audience builder
- provider-specific export UX
- full timeline/history explorer
- broad live backend wiring across all surfaces

### Data strategy

This slice should stay mock-first.

Reason:

- the product flow and page structure can be validated now
- the backend molds are still in design
- keeping the MVP mock-first avoids fake coupling to unstable table/helper shapes

Expected posture for this mold:

- mocked data remains acceptable throughout the build
- the mock layer should still behave like a real app contract: stable `journeyKey`, stable `contactId`, and deterministic lookup behavior
- real reads can be layered later onto the same components
- real writes like `save draft`, `test draft`, and `activate draft` are follow-on work, not required to complete this shell refactor
- do not introduce a Supabase client, fetch abstraction, or query cache in this slice unless the user explicitly widens scope

### Component refactor direction

Refactor the current app into explicit shell and page modules.

Create:

- `src/components/AppShell.tsx`
- `src/components/SidebarNav.tsx`
- `src/components/PageHeader.tsx`
- `src/components/PipelineRail.tsx`
- `src/pages/JourneyListPage.tsx`
- `src/pages/JourneyStudioPage.tsx`
- `src/pages/ContactInspectorPage.tsx`
- `src/pages/NotFoundPage.tsx`
- `src/components/journeys/`
- `src/components/studio/`
- `src/components/inspector/`
- `src/components/traits/TraitsSummaryPanel.tsx`
- `src/components/routing/RoutingSummaryPanel.tsx`

Demote current top-level surfaces as follows:

- `Traits` -> `TraitsSummaryPanel`
- `Routing` -> `RoutingSummaryPanel`
- `Eval + Activate` -> `EvalSummaryPanel` inside `Journey Studio`

Delete from the product shell:

- `gallery` / `focus` review mode behavior
- in-memory `activeSurface` as the primary navigation model
- top-level wireframe-section framing
- review-deck copy like `Wireframe review`
- sidebar entries for `Traits`, `Routing`, or `Eval + Activate` as standalone destinations
- global-shell placeholder actions that do not belong to the page model

### Relationship to other Journey Builder molds

This mold is a UI-shell mold, not a backend-model mold.

That means:

- it can be built now without waiting for `dialo-9`, `dialo-10`, `dialo-11`, and `dialo-12` to be fully implemented
- it should still respect the product boundaries those molds define
- later real data wiring should align primarily with:
  - `dialo-11` for Journey Studio reads/writes
  - `dialo-12` for Contact Inspector reads
  - `dialo-9` and `dialo-10` for traits/routing summaries when those data contracts become real

In other words: this mold defines the UI skeleton that later molds will populate.

Concrete implementation surface for this slice:

- `journey-builder/app/package.json`
- `journey-builder/app/src/App.tsx`
- `journey-builder/app/src/data/mockData.ts` must stop being a loose review-data bucket and start providing stable route-oriented identifiers
- `journey-builder/app/src/main.tsx`
- `journey-builder/app/src/pages/NotFoundPage.tsx`
- `journey-builder/app/src/styles.css`
- `journey-builder/app/src/data/mockData.ts`
- new modules under `journey-builder/app/src/pages/` and `journey-builder/app/src/components/`
- the supporting product docs in `journey-builder/docs/ui-mvp.md`, `journey-builder/docs/ui-implementation-checklist.md`, `journey-builder/app/README.md`, and `journey-builder/ui/README.md`

## Files to Modify
| File | Action | Purpose |
|------|--------|---------|
| `journey-builder/app/src/App.tsx` | refactor later | Remove review-deck behavior and turn the app into a real routed shell |
| `journey-builder/app/src/main.tsx` | refactor later | Introduce route-based page mounting if needed |
| `journey-builder/app/src/styles.css` | refactor later | Retune layout and styling around the three-page MVP |
| `journey-builder/app/src/data/mockData.ts` | split later | Break large mock-data file into page-aligned data modules |
| `journey-builder/app/src/pages/` | create later | Add `JourneyListPage`, `JourneyStudioPage`, and `ContactInspectorPage` |
| `journey-builder/app/src/components/` | create later | Add shell, journeys, studio, inspector, traits-summary, and routing-summary components |
| `journey-builder/docs/ui-mvp.md` | keep aligned later | Product-level statement of the MVP cut |
| `journey-builder/docs/ui-implementation-checklist.md` | keep aligned later | Concrete implementation order and extraction plan |
| `journey-builder/app/README.md` | refine later | Keep scaffold guidance aligned with the MVP cut |
| `journey-builder/ui/README.md` | refine later | Keep the UI boundary honest about what is and is not in this slice |

## Verification

- `react-router-dom` is installed and the app uses route-based navigation rather than `activeSurface` toggles as the primary page model.
- `/` redirects cleanly to `/journeys`.
- Unknown routes render a real not-found page rather than redirecting silently.
- Mock route params are backed by stable IDs/keys, not array position assumptions.
- Unknown `journeyKey` or `contactId` renders an explicit empty/not-found product state instead of a blank page, crash, or silent fallback to another item.
- Direct navigation to `/journeys`, `/journeys/:journeyKey`, and `/contacts/:contactId` renders the expected page in Vite dev and build output.
- The app no longer presents itself as a wireframe gallery or review deck.
- Three real routes exist and render correctly: `/journeys`, `/journeys/:journeyKey`, and `/contacts/:contactId`.
- `Journeys`, `Journey Studio`, and `Contact Inspector` each feel like actual product pages rather than sections in one giant mock screen.
- `Traits` and `Routing` are visible only as summary panels in the MVP, not as full standalone management screens.
- `Eval + Activate` is part of `Journey Studio`, not a separate top-level route.
- `npm run build` passes for the Vite app after the refactor.
- The resulting UI structure is simple enough that real backend reads/writes can be layered later without redoing the page architecture.

## Implementation Notes

- This mold should stay disciplined. If it starts adding full trait CRUD, full routing CRUD, analytics overhaul, or backend query plumbing, it is becoming too broad.
- Prefer route constants and page-local composition over adding app-wide state machinery.
- Keep the sidebar honest: it should represent the top-level workspace, not every route that exists in the app.
- The likely first dependency added in this slice is `react-router-dom`; anything beyond that should be justified explicitly in the build.
- Add stable mock identifiers early: the MVP should not depend on whatever item happens to be first in a list.
- The best implementation order is still:
  1. `Journeys`
  2. `Journey Studio`
  3. `Contact Inspector`
- Manuel should be able to build this slice directly from the docs without first solving the backend molds.
- Christian should inherit a clean, route-based, componentized shell rather than a monolithic `App.tsx` review deck.


## Notes

- [2026-04-17T13:49:38Z] gate: action=manual_disposition kind=disposition from=design to=closed actor="dev" reason="Landed on main after integrated build verification"
