# jbuild Product Scope

Working scope for the standalone headless `jbuild` product.

## Owns

- reusable trait definitions and optional Trait Classifiers for the current
  canonical chat owner; the current Supabase adapter maps that owner to legacy
  `silver.contacts.contact_id` in v1
- multi-journey design and routing
- journey classification
- prompt, stage, and version configuration per journey
- analytics dashboards
- segmentation and audience generation

## Depends On

- canonical contacts/messages from a contract-compatible adapter
- stable identity grouping
- stable direction and chronological ordering

## Does Not Own

- Wati webhook ingestion
- Wati API behavior
- provider sync/drift plumbing
- connector credentials and runtime health

## Product Promise

`jbuild` works on top of a documented canonical conversation contract. Wati is
the first connector and Supabase is the first runtime adapter, not the product
definition.

The product model is:

- chat traits
- optional Trait Classifiers
- routing
- journeys
- per-journey versions
- per-journey stage taxonomies

not one tenant-global classifier config forever.
