# Journey Builder UI

Product-facing UI boundary for Journey Builder.

## Purpose

This surface owns the user-facing product experience built on top of canonical
conversation data.

## Current Legacy Homes

- analytics and campaign audience UX in `app/Home.py`
- classifier configuration currently mixed into `app/pages/2_Admin.py`

## Should Own

- trait definitions and trait inference surfaces
- journey list and routing surfaces
- journey analytics
- classifier configuration
- per-journey prompt, stage, and version management
- audience generation and segmentation

## Should Not Own

- Wati connection health
- contact import
- message backfill
- daemon/webhook operational status

## Near-Term Rule

The Vite app in `journey-builder/app/` is now the primary frontend rail for the
new product. Keep it route-driven and focused on the MVP loop rather than
recreating the old mixed admin surface.

## MVP Cut

The first real UI stays smaller than the full product map:

- `Journeys`
- `Journey Studio`
- `Contact Inspector`
- read-only `Traits` summary
- read-only `Routing` summary

That gives the product one strong operator loop first:

`see journeys -> edit/test/activate one journey -> inspect one contact`

Use `journey-builder/docs/ui-mvp.md` as the concrete build target for this
first pass.

Implementation checklist:

- `journey-builder/docs/ui-implementation-checklist.md`

## Inspector Scope

The current inspector direction is current-state-first:

- resolved traits
- matched routing rule
- current journey enrollment
- current journey stage result
- recent conversation context

Detailed history/timeline views are later work once the write-side model grows
beyond current-state storage.

## Current App Shape

The current frontend rail lives in `journey-builder/app/` as a Vite + React +
TypeScript app with three real routes:

- `/journeys`
- `/journeys/:journeyKey`
- `/contacts/:contactId`

Unknown routes render a real not-found page, and unknown `journeyKey` or
`contactId` values render explicit product-level empty states.
