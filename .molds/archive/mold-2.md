# Fix owner direction check and contact name extraction in webhook trigger

## Problem

Two bugs in `bronze.transform_webhook_to_silver` (`database/05_functions.sql`) discovered by inspecting a real Wati webhook payload:

**1. Contact name is never populated from webhooks**
The trigger extracts name via:
```sql
COALESCE(NEW.raw_data->>'name', NEW.raw_data->>'pushName')
```
But real Wati webhook payloads use `senderName` for the contact's display name. Neither `name` nor `pushName` are present, so contacts created from webhooks always have `name = NULL`.

**2. `owner` direction check is fragile**
The trigger determines message direction with:
```sql
WHEN NEW.raw_data->>'owner' = 'true' THEN 'outbound'
```
Real payloads send `owner` as a JSON boolean (`false`/`true`), not a string. PostgreSQL's `->>` operator coerces booleans to `"true"`/`"false"` strings so it currently works — but it is an implicit dependency on that coercion. Hardening it to handle both forms is safer.

## Solution

Both fixes are in `database/05_functions.sql`, in the `transform_webhook_to_silver` function.

**Fix 1 — Contact name:** add `senderName` to the COALESCE chain for both the INSERT and the ON CONFLICT UPDATE:
```sql
COALESCE(NEW.raw_data->>'senderName', NEW.raw_data->>'name', NEW.raw_data->>'pushName')
```

**Fix 2 — Direction check:** outbound payloads have no `owner` field, so use `wati_contact_id IS NULL` as the primary outbound signal (consistent with the phone-lookup branch above). Keep `owner` as a secondary check for edge cases:
```sql
CASE
  WHEN NEW.wati_contact_id IS NULL THEN 'outbound'
  WHEN NEW.raw_data->>'type' IN ('0','1','2','3','4','5') THEN 'system'
  WHEN NEW.raw_data->>'owner' IN ('true', 'True', '1') THEN 'outbound'
  ELSE 'inbound'
END
```

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `database/05_functions.sql` | Modify | Add `senderName` to name COALESCE (insert + update paths); harden `owner` direction check | yes |

## Verification

1. Apply updated function via Supabase MCP (`mcp__supabase__apply_migration`)
2. Send a real Wati webhook or replay one from `webhook_logs`
3. Confirm `silver.contacts.name` is populated with the sender's name
4. Confirm `silver.messages.direction = 'inbound'` for `owner: false` payloads
5. Confirm `silver.messages.direction = 'outbound'` for `owner: true` payloads

## Implementation Notes

- Only `database/05_functions.sql` changes — no Edge Function or schema changes needed
- The `ON CONFLICT DO UPDATE SET name` block also references name and needs the same `senderName` addition to stay consistent with the insert path
