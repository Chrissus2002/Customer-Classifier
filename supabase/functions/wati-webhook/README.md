# Wati Webhook Edge Function

## Purpose

Receives webhooks from Wati and logs them to the database for trigger-based processing.

**Design Philosophy:** This Edge Function is intentionally minimal - it only logs the webhook. All processing happens via database triggers (stateless, resilient).

## Architecture

```
Wati → Edge Function → webhook_logs table
                            ↓
                    TRIGGER: process_webhook_to_bronze
                            ↓
                    bronze.wati_messages table
                            ↓
                    TRIGGER: transform_webhook_to_silver
                            ↓
                    silver.contacts + messages tables
```

## URL Pattern

```
POST https://<project-ref>.supabase.co/functions/v1/wati-webhook/{tenant-id}
```

**Example:**
```
POST https://YOUR_PROJECT_REF.supabase.co/functions/v1/wati-webhook/1
```

## Deployment

### 1. Deploy to Supabase

```bash
supabase functions deploy wati-webhook
```

### 2. Set Environment Variables

The function needs these environment variables (automatically set in Supabase):
- `SUPABASE_URL` - Your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` - Service role key (admin access)

These are automatically available in deployed Edge Functions.

### 3. Get Function URL

After deployment, the URL will be:
```
https://<project-ref>.supabase.co/functions/v1/wati-webhook/{tenant-id}
```

## Testing

### Local Testing (with Supabase running)

```bash
# Start local Supabase
supabase start

# Serve function locally
supabase functions serve wati-webhook

# Test with curl (replace with your test tenant UUID)
curl -X POST http://localhost:54321/functions/v1/wati-webhook/YOUR-TENANT-ID \
  -H "Content-Type: application/json" \
  -d '{
    "waId": "5215554146581",
    "text": "Hello from test",
    "id": "test-msg-001",
    "timestamp": "2025-02-16T12:00:00Z"
  }'
```

### Remote Testing (after deployment)

```bash
# First, create a test tenant in your database
# Then test with the tenant UUID

curl -X POST https://YOUR-PROJECT.supabase.co/functions/v1/wati-webhook/TENANT-UUID \
  -H "Content-Type: application/json" \
  -d '{
    "waId": "5215554146581",
    "text": "Hello from production test",
    "id": "test-msg-002",
    "timestamp": "2025-02-16T12:00:00Z"
  }'
```

## Verification

After sending a test webhook, verify the data flow:

```sql
-- 1. Check webhook was logged
SELECT * FROM public.webhook_logs
ORDER BY created_at DESC
LIMIT 1;

-- 2. Check it was processed to bronze
SELECT * FROM bronze.wati_messages
ORDER BY synced_at DESC
LIMIT 1;

-- 3. Check it was transformed to silver
SELECT * FROM silver.contacts
ORDER BY created_at DESC
LIMIT 1;

SELECT * FROM silver.messages
ORDER BY created_at DESC
LIMIT 1;

-- 4. Check processing log
SELECT * FROM public.webhook_processing_log
ORDER BY created_at DESC
LIMIT 5;
```

## Response Format

### Success (200 OK)
```json
{
  "success": true,
  "message": "Webhook received and logged",
  "tenant_id": 1
}
```

### Missing Tenant ID (400 Bad Request)
```json
{
  "error": "Missing tenant ID in URL path",
  "usage": "POST /wati-webhook/{tenant-id}"
}
```

### Invalid Tenant (401 Unauthorized)
```json
{
  "error": "Tenant not found or inactive",
  "tenant_id": 1
}
```

### Internal Error (500)
```json
{
  "error": "Internal server error",
  "message": "Error details here"
}
```

## Configuration in Wati

Once deployed, configure in Wati dashboard:

1. Go to Wati → Settings → Webhooks
2. Set webhook URL to:
   ```
   https://YOUR-PROJECT.supabase.co/functions/v1/wati-webhook/YOUR-TENANT-ID
   ```
3. Select events to receive (messages, status updates, etc.)
4. Save and test

## Monitoring

### Check webhook health
```sql
SELECT * FROM check_webhook_health(24); -- Last 24 hours
```

### Debug specific webhook
```sql
SELECT * FROM debug_webhook('webhook-uuid-here');
```

### View processing status
```sql
SELECT * FROM webhook_processing_status;
```

## Troubleshooting

**Webhook received but not in bronze:**
- Check `webhook_logs.processed` = false
- Check `webhook_logs.error` for trigger errors
- Verify trigger is enabled: `process_webhook_to_bronze`

**Webhook in bronze but not in silver:**
- Check for errors in `webhook_processing_log`
- Verify trigger is enabled: `transform_webhook_to_silver`
- Check contact deduplication logic (phone normalization)

**401 Unauthorized errors:**
- Tenant UUID incorrect in URL
- Tenant doesn't exist in database
- Tenant status is not 'active'

## Performance

Expected response time: **< 100ms**

The function only performs:
1. URL parsing (instant)
2. Tenant validation (1 SELECT query)
3. Webhook logging (1 INSERT query)

All heavy processing happens asynchronously via database triggers.
