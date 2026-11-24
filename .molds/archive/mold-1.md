# Test and make changes to wati_webhook

## Problem

The `wati-webhook` Edge Function (`supabase/functions/wati-webhook/index.ts`) is the entry point for all live WhatsApp messages. The pipeline is:

```
POST /wati-webhook/{tenant_id}
  → webhook_logs (Edge Function)
  → bronze.wati_messages (trigger: process_webhook_to_bronze)
  → silver.contacts + silver.messages (trigger: transform_webhook_to_silver)
```

Two gaps in scope:

**1. Payload validation is missing at the Edge Function layer.**
The `id` field (message ID) is required — if absent, `process_webhook_to_bronze` writes `"Message had no ID"` as a string, which causes UNIQUE constraint collisions on `bronze.wati_messages(tenant_id, wati_message_id)`.

**2. Outbound messages (no `waId`) are not handled correctly in the bronze→silver trigger.**
Wati sends two payload types:
- **Inbound** (`waId` present) — message from a customer; `waId` is the customer's phone number
- **Outbound** (`waId` absent) — message sent by the business; contact phone must be sourced differently

Currently `transform_webhook_to_silver` calls `bronze.normalize_phone(NULL)` for outbound messages, producing a null/junk phone and breaking the contact UPSERT.

## Solution

### Edge Function (`index.ts`)
- Validate that `id` (or `messageId`) is present — reject with 400 if missing
- Do NOT reject on missing `waId` — absence of `waId` is valid and means outbound

### `process_webhook_to_bronze` (`database/06_webhook_logging.sql`)
- Fix the `'Message had no ID'` fallback — replace with `gen_random_uuid()::TEXT` to avoid UNIQUE collisions when `id` somehow still missing after Edge Function validation

### `transform_webhook_to_silver` (`database/05_functions.sql`)
Add a branch for outbound messages:
```sql
IF NEW.wati_contact_id IS NULL THEN
  -- Outbound: use the tenant's own WhatsApp number as the contact phone
  SELECT wati_phone_number INTO v_raw_phone
  FROM public.tenants WHERE tenant_id = NEW.tenant_id;
  v_phone_normalized := bronze.normalize_phone(v_raw_phone);
ELSE
  -- Inbound: use waId from payload
  v_phone_normalized := bronze.normalize_phone(NEW.wati_contact_id);
END IF;
```
The rest of the contact UPSERT and message insert remains unchanged.

## Files to Modify

| File | Action | Purpose |
|------|--------|---------|
| `supabase/functions/wati-webhook/index.ts` | Modify | Reject if message `id` is missing | yes |
| `database/06_webhook_logging.sql` | Modify | Replace `'Message had no ID'` with `gen_random_uuid()` | yes |
| `database/05_functions.sql` | Modify | Add outbound branch in `transform_webhook_to_silver` | yes |
| `supabase/functions/wati-webhook/test.sh` | Modify | Add outbound test case and missing-id test case | yes |

## Verification

1. Deploy updated Edge Function: `supabase functions deploy wati-webhook`
2. Run `test.sh <tenant_id>` — happy path (inbound with `waId`)
3. Run outbound test — payload without `waId`, confirm row lands in `silver.messages` with `direction = 'outbound'` and contact matched to tenant's `wati_phone_number`
4. Run missing-id test — confirm 400 returned and nothing written to `webhook_logs`
5. Confirm `webhook_logs.processed = true` and bronze row exists after each successful test
6. Confirm `silver.contacts` and `silver.messages` both receive the message

## Implementation Notes

- `bronze.normalize_phone()` already exists — reuse it for the tenant phone lookup
- `public.tenants.wati_phone_number` may be NULL if tenant hasn't configured it; the trigger should log a warning via `webhook_processing_log` and return gracefully rather than raising
- `transform_webhook_to_silver` trigger already fires only when `batch_id IS NULL` (webhooks only) — no change needed to trigger condition
- The `ON CONFLICT (tenant_id, phone_normalized) DO UPDATE` on `silver.contacts` is safe to reuse — outbound messages will either find the existing tenant contact or create it
