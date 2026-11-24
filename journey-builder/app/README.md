# Journey Builder App

Vite + React + TypeScript frontend for the Journey Builder MVP.

## Purpose

This app is intentionally disconnected from live backend data for now. It gives
Journey Builder a real route-based product shell that can evolve independently
from the legacy Streamlit app.

## Current Scope

- route-based app shell with `react-router-dom`
- three real routes:
  - `/journeys`
  - `/journeys/:journeyKey`
  - `/contacts/:contactId`
- product pages for:
  - `Journeys`
  - `Journey Studio`
  - `Contact Inspector`
- read-only `Traits` and `Routing` summary panels on the journeys page
- mocked data only, with stable `journeyKey` and `contactId` identifiers
- explicit not-found states for unknown routes and unknown mock identifiers

## MVP Direction

The first real UI is deliberately smaller than the full Journey Builder product.

Primary MVP loop:

1. `Journeys`
2. `Journey Studio`
3. `Contact Inspector`

Keep `Traits` and `Routing` visible as summary panels in the first pass rather
than full CRUD/product areas.

See:

- `journey-builder/docs/ui-mvp.md`
- `journey-builder/docs/ui-implementation-checklist.md`

## Run

```bash
cd journey-builder/app
npm install
npm run dev
```

## Build

```bash
npm run build
```

## Notes

- Keep connector operations out of this app.
- This frontend is for the Journey Builder product, not the `wati-supabase`
  connector.
- When real data wiring starts, preserve the product model:
  canonical conversations -> optional trait inference -> routing ->
  per-journey stage classification.
