# Trait Inference Model

Build contract for reusable chat traits in `jbuild`.

## Purpose

Journey routing often needs information the user does not already have for the
current canonical chat owner.

Examples:

- `customer_type = wholesale | retail | unknown`
- `is_existing_customer = true | false | unknown`
- `preferred_language = es | en | unknown`

These are not usually journey stages. They are reusable attributes resolved for
one chat/contact owner, and they can feed routing, analytics, and product
experiences across multiple journeys.

For v1, product language can still say chat, but the safe contract anchor is
the canonical `contact_id` supplied by the conversation adapter. The current
Supabase adapter maps that to legacy `silver.contacts.contact_id`. The repo
does not yet have a separate reliable chat entity, and `conversation_id` is not
stable enough to use as the primary owner for trait values.

## Product Position

Trait resolution sits between canonical conversation data and routing.

Fixed v1 stack:

1. canonical conversations
2. optional trait resolution
3. deterministic routing
4. per-journey stage classification

This is intentionally simpler than an arbitrary classifier graph engine.

## Core Objects

### `trait definition`

Defines a reusable attribute the product knows how to store and reason about
for a chat.

Examples:

- `customer_type`
- `preferred_language`
- `is_existing_customer`

At minimum it should capture:

- stable `trait_key`
- display label
- description
- value type
- allowed values where relevant

### `chat trait value`

One chat's current value for a trait.

At minimum it should capture:

- chat
- trait definition
- value
- confidence
- source
- explanation/evidence
- evaluated_at

In v1 this should be modeled as one current value per canonical owner, not a
history/event log.

Important state distinction:

- no current row = unresolved / not yet computed
- explicit `unknown` value = resolved, but unknown

### `trait source`

How the chat trait value was set.

V1 should support:

- `imported`
- `rule`
- `manual`
- `classifier`

The product should not force all traits through a model if a stronger source
already exists.

Recommended v1 precedence:

1. `manual`
2. `imported`
3. `rule`
4. `classifier`

Trusted values supplied by an upstream system should enter as `imported` with
provenance in metadata unless a later product need proves a separate source is
necessary.

That precedence should be enforced atomically where the data lives, not via
naive client-side read/then-upsert logic.

Because v1 trait values are anchored to canonical `contact_id`, contact merges
must reconcile trait rows explicitly. The trait model should not assume that a
contact merge can ignore contact-owned truth.

### `trait classifier`

A first-class classifier that resolves one trait for a chat. This classifier is
not part of any Journey.

Examples:

- prompt / instructions for a trait classifier
- allowed output values
- active version
- activation state

Important versioning rule:

- the live trait definition may change over time
- each Trait Classifier version should snapshot the label set it was authored
  and tested against
- old classifier versions should not silently reinterpret results because the
  current trait definition changed later

Trait Classifiers should get a narrow but real per-trait lifecycle:

- draft
- test
- activate

V1 does not need branching drafts or experiment cohorts.

## Key Design Rules

1. Traits are reusable attributes on the current canonical chat owner, not
   journey stages.
2. Trait resolution is optional. Imported values may already exist.
3. Trait values should be inspectable and explainable per chat.
4. Routing should read normalized trait values, not raw provider payloads.
5. Model-backed Trait Classifiers should be narrow and purposeful, not a hidden
   general workflow engine.
6. Trait Classifiers are first-class classifiers, separate from Journey classifiers.

## V1 Recommendation

Support:

- typed trait definitions
- one current trait value per `(contact_id, trait_key)` in v1
- multiple trait sources with precedence rules
- optional model-backed Trait Classifiers
- routing based on imported, manual, rule, or classifier traits
- chat-level trait inspection with source and explanation

Defer:

- arbitrary trait dependency graphs
- fully generic feature-engineering pipelines
- multi-step trait workflows with branching execution
