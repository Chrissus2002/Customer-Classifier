# Journey Builder UI Implementation Checklist

Concrete implementation checklist for turning the current Vite wireframe deck
into the first real Journey Builder UI.

This is intentionally tied to the current scaffold in `journey-builder/app/`.
It is not a generic frontend plan.

## Current Starting Point

Today the frontend is still a review deck:

- one large `src/App.tsx`
- `gallery` and `focus` review modes
- six top-level mock surfaces:
  - Traits
  - Routing
  - Journeys
  - Journey Studio
  - Eval + Activate
  - Contact Inspector
- review-oriented copy like `Wireframe review`, `Gallery`, and `Focus`
- no route structure yet

That is good for review, but it is the wrong shape for the MVP.

## Target MVP Shape

Turn the app into three real pages plus two summary panels:

### Real pages

- `/journeys`
- `/journeys/:journeyKey`
- `/contacts/:contactId`

### Summary panels only

- traits summary
- routing summary

This means the app should stop behaving like a design gallery and start behaving
like one coherent product workflow.

## Route Plan

### Route 1: `/journeys`

Purpose:

- landing page
- list all journeys
- show enough context to open one journey
- show traits and routing summaries in a side rail or lower section

Required sections:

- page header
- journey cards list
- traits summary panel
- routing summary panel
- recent changes block optional

### Route 2: `/journeys/:journeyKey`

Purpose:

- main working surface for one journey
- stage editing, prompt editing, test summary, version history, activation

Required sections:

- journey header
- stage list editor
- prompt editor
- test summary / eval summary
- version history
- draft notes

Important:

- `Eval + Activate` should no longer be a separate top-level screen
- it should become a section inside Journey Studio

### Route 3: `/contacts/:contactId`

Purpose:

- trust and explainability
- one place to understand why a contact got a journey and stage

Required sections:

- identity header
- recent conversation excerpt
- resolved traits
- routing explanation
- current journey state
- current stage state

## What To Delete Or Demote From The Current Scaffold

### Delete

- `gallery` review mode
- `focus` review mode toggle
- `Wireframe review` page framing
- `Connect Supabase later` button
- `New draft` button in the global shell
- `WireframeSection` wrappers as the main page model

### Demote

- `Traits` page -> `TraitsSummaryPanel`
- `Routing` page -> `RoutingSummaryPanel`
- `Eval + Activate` page -> `EvalSummaryPanel` inside Journey Studio

### Keep, but move

- pipeline rail can stay, but it should become contextual page framing rather
  than the main navigation model
- existing mock content can stay, but it should be redistributed into page
  components instead of one monolithic review file

## Component Extraction Plan

Start by splitting `src/App.tsx` into real page and shell components.

### Step 1: App shell

Create:

- `src/components/AppShell.tsx`
- `src/components/SidebarNav.tsx`
- `src/components/PageHeader.tsx`
- `src/components/PipelineRail.tsx`

Move out of current `App.tsx`:

- sidebar brand
- sidebar nav
- page header
- pipeline card

### Step 2: Journeys page

Create:

- `src/pages/JourneyListPage.tsx`
- `src/components/journeys/JourneyCard.tsx`
- `src/components/journeys/RecentChangesPanel.tsx`
- `src/components/traits/TraitsSummaryPanel.tsx`
- `src/components/routing/RoutingSummaryPanel.tsx`

Current sources to extract from:

- `JourneysSurface()`
- `TraitsSurface()`
- `RoutingSurface()`
- `recentJourneyChanges`, `journeys`, `traitCards`, `routingRules`

### Step 3: Journey Studio page

Create:

- `src/pages/JourneyStudioPage.tsx`
- `src/components/studio/JourneyHeader.tsx`
- `src/components/studio/StageListEditor.tsx`
- `src/components/studio/StageRowEditor.tsx`
- `src/components/studio/PromptEditor.tsx`
- `src/components/studio/PromptPreview.tsx`
- `src/components/studio/DraftNotesEditor.tsx`
- `src/components/studio/VersionHistoryList.tsx`
- `src/components/studio/EvalSummaryPanel.tsx`

Current sources to extract from:

- `StudioSurface()`
- `EvalSurface()`
- `studioStages`, `studioPrompt`, `evalRows`

### Step 4: Contact Inspector page

Create:

- `src/pages/ContactInspectorPage.tsx`
- `src/components/inspector/ConversationExcerpt.tsx`
- `src/components/inspector/TraitStatePanel.tsx`
- `src/components/inspector/RoutingExplanationPanel.tsx`
- `src/components/inspector/JourneyStatePanel.tsx`
- `src/components/inspector/StageStatePanel.tsx`

Current sources to extract from:

- `InspectorSurface()`
- `inspectorTraits`, `inspectorTimeline`

### Step 5: Data organization

Create:

- `src/data/journeys.ts`
- `src/data/studio.ts`
- `src/data/inspector.ts`
- `src/data/traits.ts`
- `src/data/routing.ts`

Goal:

- stop using one large `mockData.ts` file once the page split begins

## First Screens To Build This Week

### 1. Journeys page

Why first:

- becomes the real landing page
- gives the app an immediate non-gallery identity
- easiest place to anchor the MVP route structure

Definition of done:

- `/journeys` exists
- journey cards render cleanly
- traits summary and routing summary show in a secondary rail or section
- no gallery/focus framing remains on that route

### 2. Journey Studio page

Why second:

- this is the core product value
- prompt/stage iteration is the thing you care about most

Definition of done:

- `/journeys/:journeyKey` exists
- stage editor and prompt editor render as a real page
- eval summary lives on the page
- version history is visible
- activate is page-local, not global-shell UI

### 3. Contact Inspector page

Why third:

- this is the trust surface
- without it, the classifier UX still feels blind

Definition of done:

- `/contacts/:contactId` exists
- it clearly shows the chain:
  - conversation
  - traits
  - routing
  - current journey
  - current stage
- stale/current status is visually explicit

## What Can Stay Mocked At First

Safe to keep mocked in the first implementation pass:

- journey counts
- stale counts
- version history
- eval summary rows
- routing explanation payload
- inspector reasoning text

The key is to get the layout and interaction model right before real data
 wiring.

## What To Wire To Real Data First

Once the MVP shell is stable, wire these reads first:

1. journeys list
2. one journey detail
3. one journey version history list
4. one contact inspector payload

Then wire these writes:

1. save draft
2. test draft
3. activate draft

Do not start with full traits CRUD or full routing CRUD.

## Suggested Implementation Sequence In The Repo

1. add routing library (`react-router-dom`) if you want route-based pages now
2. split `App.tsx` into shell + page components
3. make `/journeys` the default route
4. move Eval into Journey Studio
5. demote Traits and Routing into summary panels
6. add `/contacts/:contactId`
7. tighten styling around the three-page MVP
8. only then start wiring real reads

## Suggested File Targets

Likely first files to touch:

- `journey-builder/app/src/App.tsx`
- `journey-builder/app/src/main.tsx`
- `journey-builder/app/src/styles.css`
- `journey-builder/app/src/data/mockData.ts`

Likely new files to add first:

- `journey-builder/app/src/pages/JourneyListPage.tsx`
- `journey-builder/app/src/pages/JourneyStudioPage.tsx`
- `journey-builder/app/src/pages/ContactInspectorPage.tsx`
- `journey-builder/app/src/components/AppShell.tsx`
- `journey-builder/app/src/components/SidebarNav.tsx`
- `journey-builder/app/src/components/PageHeader.tsx`
- `journey-builder/app/src/components/PipelineRail.tsx`

## Practical Rule For This MVP

If a screen does not directly help with:

- choosing a journey
- editing/testing/activating one journey
- understanding one contact

then it probably should not be a top-level MVP page yet.
