# Journey Builder

Standalone product home for the customer journey and conversation intelligence
layer.

## Purpose

This product owns the application layer that reads canonical conversation data
from any adapter that satisfies the documented contract and turns it into
operator value:

- reusable chat traits and optional Trait Classifiers
- multi-journey routing and classification
- prompt and stage configuration
- analytics dashboards
- segmentation
- campaign audience generation

It should work on top of a documented canonical conversation contract. Wati is
one connector and Supabase is the current runtime adapter; neither is the
defining product boundary.

The product should be thought of as:

- a chat-traits workbench
- a journey router
- a per-journey classifier workbench
- a journey analytics surface

## Target Layer Model

This product should be described using explicit layer names rather than
medallion jargon:

- `staging`: connector-owned raw landing area
- `canonical`: the conversation contract Journey Builder consumes
- `analytics`: derived views and metrics the product surfaces
- `ops`: runtime/admin state, not the core product contract

For Journey Builder, the center of gravity is `canonical` + `analytics`. The
current code maps that contract to the legacy Supabase `silver` schema through
an adapter.

## Current Code That Belongs Here

- `app/`
- `scripts/classify_worker.py`
- `scripts/classifiers/`
- classifier and segmentation tables/views in `database/`

## Depends On

- canonical contacts/messages from a contract-compatible adapter
- reliable message direction and ordering
- stable contact identity keys

## Does Not Own

- Wati webhook ingestion
- Wati API client behavior
- Wati backfills and sync progress
- provider-specific operational drift checks

## Near-Term Goal

Separate the journey product story from the connector story without breaking the
shared schema. The classifier should be documented as consuming canonical
conversation data, not arbitrary raw chat exports.

## Scaffold

- `app/` — Vite + React + TypeScript frontend scaffold
- `docs/` — Journey Builder product docs
- `contracts/` — classifier and product-facing contract notes
- `runtime/` — app/runtime boundary notes
- `ui/` — product-facing UI boundary notes

## Seed Files

- `app/README.md`
- `contracts/classifier-input-contract.md`
- `contracts/trait-inference-model.md`
- `contracts/journey-routing-model.md`
- `docs/ui-mvp.md`
- `docs/product-scope.md`
- `ui/README.md`
