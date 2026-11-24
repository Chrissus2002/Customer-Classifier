# Classifier Input Contract

Draft product-facing contract for Journey Builder.

## Purpose

Journey Builder does not consume arbitrary chat dumps. It consumes canonical
conversation data with stable semantics.

This contract is the shared classifier input surface across all journeys. The
same canonical conversation data may feed different journey-specific
classifiers, depending on routing.

Current physical mapping is still legacy:

- `silver.contacts`
- `silver.messages`

Target conceptual dependency is:

- `canonical.contacts`
- `canonical.messages`

## Required Contact Semantics

- one canonical contact groups one coherent customer conversation identity
- stable `contact_id` and `tenant_id`
- contact identity is already deduped at the canonical layer

## Required Message Semantics

- one row per conversational unit
- stable chronological `timestamp`
- stable `direction`
- usable `text`
- messages queryable by `contact_id` in order

## Direction Contract

Journey Builder depends on connector-guaranteed direction semantics:

- inbound = customer
- outbound = business
- system = non-conversation/system noise

## Explicit Non-Goals

- raw provider webhook formats
- provider-specific lookup semantics
- arbitrary CSV/chat exports without normalization

## Relationship To Journeys

This contract says what the classifier can rely on from canonical data.

It does not define:

- which reusable traits should be inferred from that data
- which journey a contact belongs to
- which journey version should classify that contact
- how routing rules choose between journeys

Those are defined by the trait and journey/routing models.
