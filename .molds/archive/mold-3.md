# Add last_inbound_message_at to journey_intent_results for smart reclassification

## Problem

The classifier batch worker (`scripts/classify_worker.py` via `orchestrator.py`) only classifies contacts that have **never been classified** — once a contact has any row in `silver.journey_intent_results`, they are permanently excluded from future runs regardless of new message activity.

This means:
- Contacts classified months ago with stale data are never updated
- New messages from already-classified contacts are silently ignored
- The journey stage shown in the UI is frozen at the first classification

The root cause is in `get_unclassified_contacts`: it does a simple set difference (`all_contacts - classified`) with no regard for whether new messages have arrived since the last classification.

## Solution

### 1. Schema — `database/03_silver_layer.sql`
The column `last_inbound_message_at TIMESTAMPTZ` has already been added to `silver.journey_intent_results` in the schema file. Apply it to the live database.

### 2. Classifier write — `scripts/classifiers/orchestrator.py`
In `classify_and_store`, before inserting, query `silver.messages` for the contact's latest inbound message timestamp and include it in the INSERT:

```python
latest_msg = (
    self.client.schema("silver").table("messages")
    .select("timestamp")
    .eq("tenant_id", tenant_id)
    .eq("contact_id", contact_id)
    .eq("direction", "inbound")
    .order("timestamp", desc=True)
    .limit(1)
    .execute()
)
last_inbound_message_at = latest_msg.data[0]["timestamp"] if latest_msg.data else None

self.client.schema("silver").table("journey_intent_results").insert({
    "tenant_id": tenant_id,
    "contact_id": contact_id,
    "journey_stage": result.journey_stage,
    "confidence": result.confidence,
    "classifier_version": result.classifier_version,
    "last_inbound_message_at": last_inbound_message_at,
}).execute()
```

### 3. Reclassification logic — `scripts/classifiers/orchestrator.py`
Update `get_unclassified_contacts` to also return contacts whose latest inbound message postdates their last classification:

```python
# Contacts needing reclassification:
# latest inbound message timestamp > last_inbound_message_at stored at classification time
```

Logic:
1. Get latest inbound message timestamp per contact from `silver.messages`
2. Get latest `classified_at` + `last_inbound_message_at` per contact from `journey_intent_results`
3. Return contacts where no classification exists OR `current latest inbound > stored last_inbound_message_at`

## Files to Modify

| File | Action | Purpose | Done |
|------|--------|---------|------|
| `database/03_silver_layer.sql` | Already updated — apply to DB | Add `last_inbound_message_at` column | yes |
| `scripts/classifiers/orchestrator.py` | Modify | Store `last_inbound_message_at` on insert; update `get_unclassified_contacts` to include reclassification candidates | yes |

## Verification

1. Apply schema change via Supabase MCP
2. Run classifier: `python -m scripts.classify_worker --tenant YOUR_TENANT_ID`
3. Confirm `last_inbound_message_at` is populated on new `journey_intent_results` rows
4. Manually update a contact's latest message to be newer than their `last_inbound_message_at`
5. Re-run classifier — confirm the contact is picked up for reclassification
6. Confirm a contact with no new messages since last classification is NOT re-classified

## Implementation Notes

- `silver.messages` has an index on `(contact_id, timestamp DESC)` — the latest message query is efficient
- The existing `UNIQUE(tenant_id, contact_id, classified_at)` constraint allows multiple classification rows per contact over time — reclassification just inserts a new row, doesn't update the old one
- `get_unclassified_contacts` currently uses a `since_date` filter (`2026-01-01`) on messages — reclassification candidates should use the same filter to avoid re-processing very old contacts
