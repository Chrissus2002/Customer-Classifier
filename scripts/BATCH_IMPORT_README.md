# Batch Import Tool - Usage Guide

## 📋 Overview

The batch import tool fetches contacts from Wati API and imports them into the database.

## 🚀 Usage

### Basic Usage

```bash
# Import all contacts for a tenant
python scripts/batch_import.py --tenant-id YOUR_TENANT_ID
```

### What It Does

1. ✅ Fetches tenant credentials from database
2. ✅ Creates an import job record (tracks progress)
3. ✅ Connects to Wati API
4. ✅ Fetches ALL contacts (handles pagination automatically)
5. ✅ Inserts contacts into `bronze.wati_contacts` table
6. ✅ Marks job as completed/failed

## 📊 Output Example

```
============================================================
🚀 Starting batch import for tenant: YOUR_TENANT_ID
============================================================

🔑 Fetching tenant credentials...
   ✅ Found tenant: Filippa

📋 Creating import job...
   ✅ Job ID: a1b2c3d4-e5f6-7890-abcd-1234567890ab

📡 Initializing Wati API client...
   ✅ Client ready

📥 Fetching contacts from Wati API...
   (This may take a while for large contact lists)
   ✅ Fetched 550 total contacts

💾 Inserting contacts into database...
   ✅ Inserted 550 contacts into bronze layer

📊 Updating job status...
   ✅ Job marked as completed

============================================================
✅ Import completed successfully!
============================================================
  Tenant ID:      YOUR_TENANT_ID
  Tenant Name:    Filippa
  Batch ID:       a1b2c3d4-e5f6-7890-abcd-1234567890ab
  Total Contacts: 550
  Duration:       45.23 seconds
============================================================
```

## 🗄️ Database Tables Updated

### `import_jobs`
- Tracks import progress
- Fields: job_id, tenant_id, status, total_messages, started_at, completed_at

### `bronze.wati_contacts`
- Raw contact data from Wati
- Fields: id, tenant_id, batch_id, wati_contact_id, raw_data, synced_at

## ✅ Verifying the Import

### 1. Check Import Job Status

```sql
-- See all import jobs
SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT 5;

-- Check specific job
SELECT * FROM import_jobs WHERE job_id = 'your-batch-id';
```

### 2. Check Bronze Contacts

```sql
-- Count contacts for a tenant
SELECT COUNT(*) FROM bronze.wati_contacts WHERE tenant_id = YOUR_TENANT_ID;

-- See recent contacts
SELECT * FROM bronze.wati_contacts
WHERE tenant_id = YOUR_TENANT_ID
ORDER BY synced_at DESC
LIMIT 10;

-- Check a specific batch
SELECT COUNT(*) FROM bronze.wati_contacts WHERE batch_id = 'your-batch-id';
```

### 3. Check Silver Contacts (After Processing)

```sql
-- If triggers are processing bronze → silver
SELECT COUNT(*) FROM silver.contacts WHERE tenant_id = YOUR_TENANT_ID;
```

## ⚠️ Error Handling

### If Import Fails

The script will:
1. Mark the import job as `'failed'`
2. Save error message to `import_jobs.error_message`
3. Exit with code 1

Check the error:
```sql
SELECT error_message FROM import_jobs WHERE status = 'failed' ORDER BY created_at DESC LIMIT 1;
```

### Common Errors

**"Tenant not found"**
- Make sure tenant exists in database
- Check tenant_id is correct

**"Tenant has no API token configured"**
- Go to Settings page and add Wati API token
- Or update directly: `UPDATE tenants SET wati_api_token = '***REMOVED*** xyz...' WHERE tenant_id = YOUR_TENANT_ID;`

**"Failed to fetch contacts from Wati API"**
- Check API token is valid
- Check network connectivity
- Verify Wati API is accessible

## 🔄 Re-running Import

You can run the import multiple times. Each run:
- Creates a NEW import_job record
- Uses a NEW batch_id
- Inserts contacts again (bronze allows duplicates)

## 📝 Next Steps

After importing contacts to bronze:

1. **Verify data in bronze layer:**
   ```sql
   SELECT raw_data FROM bronze.wati_contacts LIMIT 1;
   ```

2. **Process to silver layer** (if not automatic):
   - Database triggers should process automatically
   - Or call `bronze.process_to_silver(batch_id)` manually

3. **Check deduplication:**
   ```sql
   -- Should have unique phone numbers per tenant
   SELECT phone_normalized, COUNT(*)
   FROM silver.contacts
   WHERE tenant_id = YOUR_TENANT_ID
   GROUP BY phone_normalized
   HAVING COUNT(*) > 1;
   ```

4. **Eventually add messages import** (future enhancement)

## 🐛 Troubleshooting

### Script won't run
```bash
# Make sure you're in project root
cd /path/to/V2_wati_filippa

# Try with python3 explicitly
python3 scripts/batch_import.py --tenant-id YOUR_TENANT_ID
```

### Import hangs
- Check Wati API rate limits
- Increase `self.rate_limit` in WatiAPIClient if needed
- Use Ctrl+C to cancel (job will be marked as failed)

### Want more verbose output
- Edit `wati_client.py` to add more print statements
- Or modify `batch_import.py` to show progress per contact
