# Journey Routing Model

Draft first-principles model for multi-journey Journey Builder.

## Purpose

Journey Builder should not assume one tenant-global classifier config. It
should support multiple journeys per tenant, each with its own versions and
stage taxonomy, with deterministic routing of contacts into those journeys.

Routing sits after optional trait inference and before per-journey stage
classification.

## Core Objects

### `journey`

A stable business track.

Examples:

- `retail_buyers`
- `wholesale_buyers`
- `vip_recovery`

This should be the durable product object a user recognizes.

### `journey version`

A versioned configuration for one journey.

Owns:

- prompt content
- stage definitions
- model/provider choice
- notes/eval state
- activation status

V1 recommendation:

- allow one mutable draft version
- allow one active version per journey

### `routing rule`

Determines whether a contact should enter a journey.

V1 recommendation:

- deterministic ordered rules
- first-match-wins plus one required fallback rule
- router inputs come from resolved trait values, not from arbitrary downstream
  classifier chaining
- rules should be versioned as part of a tenant-wide routing config so preview
  and activation are safe
- rules should reference stable trait identities, not only mutable trait keys
- if conditions are stored as JSON-like payloads, config save/activate paths
  must validate referenced traits and journeys explicitly

### `contact trait`

A routing input attached to a contact.

Potential sources:

- imported labels from customer datasets
- manual tagging
- canonical contact metadata
- future CRM syncs
- optional model-backed trait inference

### `enrollment`

Represents that a contact belongs to a journey.

At minimum this should capture:

- contact
- journey
- matched rule
- routing config version
- enrollment reason
- enrolled_at

V1 recommendation:

- exactly one current enrollment per canonical contact
- current-state table first, not a history/event log
- enough metadata to explain current routing and detect reroute candidates
- an explicit reroute-invalid flag is preferable to vague implicit drift after
  contact merges or rule/model changes

### `classification result`

Journey-scoped output for a contact under a specific journey version.

This should include:

- journey identity
- journey version identity
- stage identity
- confidence
- timestamps

## Key Design Rules

1. `version` is scoped to a journey, not to the tenant globally.
1a. Routing config version is tenant-wide because routing chooses among all
    journeys for a tenant.
2. Stage identity should separate immutable keys from editable display labels.
3. Trait inference happens before routing when imported or rule-based data is
   insufficient.
4. Routing decides the journey before journey classification runs.
5. Imported labels are best treated as traits or routing inputs, not as hard
   rewrites of classifier output.
6. V1 should not become an arbitrary workflow graph engine.

## V1 Recommendation

Support:

- optional trait inference before routing
- multiple journeys per tenant
- one active version per journey
- deterministic routing with one active routing config per tenant
- imported traits/labels and inferred traits as routing inputs
- exactly one current enrollment per contact
- journey-scoped results and analytics

Defer:

- cohort-based rollout across different versions of the same journey
- arbitrary chained classifiers
- generic DAG/workflow builders
- full enrollment history/event sourcing
