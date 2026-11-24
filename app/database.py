import streamlit as st
import sys
import os
import bcrypt
from datetime import datetime, timezone

module_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),"..","scripts"))
sys.path.append(module_dir)
from supabase_client import get_supabase_client

def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: The password entered by the user
        password_hash: The bcrypt hash from environment variable

    Returns:
        True if password matches, False otherwise
    """
    if not password_hash:
        return False

    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            password_hash.encode('utf-8')
        )
    except Exception as e:
        print("Error verifying password: " + str(e))
        return False


def hash_password(password: str) -> str:
    """Generate a bcrypt hash from a plaintext password."""
    salt = bcrypt.gensalt()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), salt)
    return password_hash.decode('utf-8')

# ==============================================
# TENANT AND DATABASE FUNCTIONS
# ==============================================

def insert_tenant_into_db(tenant_dict: dict):
    client = get_supabase_client()
    
    existing_tenant = client.table("tenants").select("tenant_id").eq("tenant_id", tenant_dict["tenant_id"]).execute()
    if existing_tenant.data:
        return "Tenant already exists", False

    # Try and catch response in case of any errors, otherwise it inserts new tenant
    try:
        response = client.table("tenants").insert(tenant_dict).execute()
        return response, True
    except Exception as e:
        err = f"Error inserting tenant: {e}"
        return err, False


def retrieve_tenant_from_db(tenant_id, slug, password):
    client = get_supabase_client()

    tenant = client.table("tenants").select("*").eq("tenant_id", tenant_id).eq("slug", slug).execute()

    if not tenant.data:
        return "Tenant not found", False

    if tenant.data[0]["slug"] != slug or not verify_password(password, tenant.data[0]["password"]):
        return "Invalid username or password", False

    return tenant.data[0], True


def update_wati_credentials(tenant_id, wati_api_token=None, wati_phone_number=None):
    """
    Update Wati credentials for a tenant.
    Only updates wati_api_token and wati_phone_number fields.

    Args:
        tenant_id: The tenant ID to update
        wati_api_token: New Wati API token (optional)
        wati_phone_number: New Wati phone number (optional)

    Returns:
        Tuple of (result, success_bool)
    """
    client = get_supabase_client()

    # Build update dict with only provided values
    updates = {}
    if wati_api_token is not None:
        updates["wati_api_token"] = wati_api_token
    if wati_phone_number is not None:
        updates["wati_phone_number"] = wati_phone_number

    if not updates:
        return "No updates provided", False

    try:
        response = client.table("tenants").update(updates).eq("tenant_id", tenant_id).execute()

        if not response.data:
            return "Update failed", False

        return response.data[0], True
    except Exception as e:
        return f"Error updating credentials: {e}", False


def count_distinct_normalized_phones(phone_numbers):
    """
    Count distinct normalized phone numbers using the database authority.

    This calls bronze.count_distinct_normalized_phones(), which in turn
    delegates to bronze.normalize_phone() so the drift check matches the
    same dedupe rule used by contact ingestion.
    """
    client = get_supabase_client()

    try:
        response = client.schema("bronze").rpc(
            "count_distinct_normalized_phones",
            {"p_phones": phone_numbers or []},
        ).execute()
        data = response.data
        if isinstance(data, list):
            if not data:
                return 0, True
            data = data[0]
        if data is None:
            return "No data returned from normalization function", False
        return int(data), True
    except Exception as e:
        return f"Error counting normalized phones: {e}", False


def get_contact_count_by_tenant(tenant_id):
    """Return the exact number of deduplicated contacts for a tenant."""
    client = get_supabase_client()

    try:
        response = (
            client.schema("silver")
            .table("contacts")
            .select("contact_id", count="exact")
            .eq("tenant_id", tenant_id)
            .limit(0)
            .execute()
        )
        return response.count or 0, True
    except Exception as e:
        return f"Error fetching contact count: {e}", False


def get_contact_identity_count_by_tenant(tenant_id, default_region=None):
    """Return the distinct canonical identity count for a tenant's contacts."""
    from phone_identity import identity_from_contact_record

    try:
        contacts = get_all_contacts_by_tenant(tenant_id)
        identity_keys = set()
        for contact in contacts:
            if not contact.get("is_canonical", True):
                continue
            key = contact.get("phone_identity_key")
            if not key:
                key = identity_from_contact_record(contact, default_region=default_region).phone_identity_key
            if key:
                identity_keys.add(key)
        return len(identity_keys), True
    except Exception as e:
        return f"Error fetching contact identity count: {e}", False


def upsert_contact_identity_rows(rows):
    """Persist shadow contact identity fields via contact_id upserts."""
    client = get_supabase_client()

    if not rows:
        return 0, True

    try:
        response = (
            client.schema("silver")
            .table("contacts")
            .upsert(rows, on_conflict="contact_id")
            .execute()
        )
        return len(response.data or rows), True
    except Exception as e:
        return f"Error upserting contact identity rows: {e}", False


def upsert_contact_wati_key_rows(rows):
    """Persist Wati contact key mappings via tenant_id + wati_contact_id upserts."""
    client = get_supabase_client()

    if not rows:
        return 0, True

    try:
        response = (
            client.schema("silver")
            .table("contact_wati_keys")
            .upsert(rows, on_conflict="tenant_id,wati_contact_id")
            .execute()
        )
        return len(response.data or rows), True
    except Exception as e:
        return f"Error upserting contact_wati_keys rows: {e}", False


def insert_daemon_task_run(
    tenant_id,
    task_name,
    trigger="daemon",
    status="running",
    started_at=None,
    finished_at=None,
    duration_ms=None,
    result=None,
    error_message=None,
    notes=None,
):
    """Insert a daemon task run row and return the created record."""
    client = get_supabase_client()
    payload = {
        "tenant_id": tenant_id,
        "task_name": task_name,
        "trigger": trigger,
        "status": status,
    }

    if started_at is not None:
        payload["started_at"] = started_at
    if finished_at is not None:
        payload["finished_at"] = finished_at
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    if result is not None:
        payload["result"] = result
    if error_message is not None:
        payload["error_message"] = error_message
    if notes is not None:
        payload["notes"] = notes

    try:
        response = client.table("daemon_task_runs").insert(payload).execute()
        if not response.data:
            return "Failed to insert daemon task run", False
        return response.data[0], True
    except Exception as e:
        return f"Error inserting daemon task run: {e}", False


def update_daemon_task_run(run_id, updates=None, **kwargs):
    """Update an existing daemon task run row."""
    if updates is None:
        updates = kwargs
    elif kwargs:
        updates = {**updates, **kwargs}

    client = get_supabase_client()

    try:
        response = client.table("daemon_task_runs").update(updates).eq("id", run_id).execute()
        if not response.data:
            return "Failed to update daemon task run", False
        return response.data[0], True
    except Exception as e:
        return f"Error updating daemon task run: {e}", False


def finish_daemon_task_run(run_id, status, finished_at, duration_ms, result=None, error_message=None, notes=None):
    """Finalize a daemon task run row with its outcome metadata."""
    updates = {
        "status": status,
        "finished_at": finished_at,
        "duration_ms": duration_ms,
    }
    if result is not None:
        updates["result"] = result
    if error_message is not None:
        updates["error_message"] = error_message
    if notes is not None:
        updates["notes"] = notes

    return update_daemon_task_run(run_id, updates)


def get_latest_daemon_task_run(tenant_id, task_name):
    """Return the latest daemon task run for a tenant/task pair."""
    client = get_supabase_client()

    try:
        response = (
            client.table("daemon_task_runs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("task_name", task_name)
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0], True
        return None, True
    except Exception as e:
        return f"Error fetching latest daemon task run: {e}", False


def get_daemon_task_run_history(tenant_id, task_name, limit=10):
    """Return recent daemon task runs for a tenant/task pair."""
    client = get_supabase_client()

    try:
        response = (
            client.table("daemon_task_runs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("task_name", task_name)
            .order("started_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or [], True
    except Exception as e:
        return f"Error fetching daemon task history: {e}", False

@st.cache_data(ttl=300)
def get_all_contacts_by_tenant(tenant_id):
    """Fetch all contacts for a tenant with pagination."""
    client = get_supabase_client()
    all_contacts = []
    page_size = 1000  # Rows per request
    offset = 0

    while True:
        try:
            response = (
                client.schema("silver")
                .table("contacts")
                .select("*")
                .eq("tenant_id", tenant_id)
                .order("contact_id")
                .range(offset, offset + page_size - 1)
                .execute()
            )

            if not response.data:
                break 

            all_contacts.extend(response.data)

            # Break if we got less than page_size (last page)
            if len(response.data) < page_size:
                break
            offset += page_size

        except Exception as e:
            print(f"Error fetching contacts: {e}")
            break

    return all_contacts

def get_contact_info_by_phone_number(phone_number):
    client = get_supabase_client()
    try:
        response = client.schema("silver").table("contacts").select("*").eq("phone_raw", phone_number).execute()
        if not response.data:
            return "Contact not found", False
        return response.data[0], True
    except Exception as e:
        return f"Error fetching contact info: {e}", False

def get_all_tenants():
    """
    Get all tenants from the database.

    Returns:
        List of tenant dictionaries
    """
    client = get_supabase_client()
    
    try:
        response = client.table("tenants").select("tenant_id").execute()
        return response.data
    except Exception as e:
        print(f"Error fetching tenants: {e}")
        return []

@st.cache_data(ttl=300)
def get_journey_intent_results_by_tenant(tenant_id):
    client = get_supabase_client()
    try:
        page_size = 1000
        offset = 0
        all_data = []
        while True:
            response = (client.schema("silver")
            .table("journey_intent_results")
            .select("*")
            .eq("tenant_id", tenant_id)
            .range(offset, offset + page_size - 1)
            .execute())

            if not response.data:
                break
            all_data.extend(response.data)

            if len(response.data) < page_size:
                break

        return all_data
    except Exception as e:
        return f"Error fetching intent journey results: {e}"


@st.cache_data(ttl=300)
def get_contact_activity_by_tenant(tenant_id):
    """Fetch last_inbound_at per contact from the gold layer for recency metrics."""
    client = get_supabase_client()
    offset = 0
    page_size = 1000
    all_data = []
    try:
        while True:
            response = (
                client.schema("gold")
                .table("contact_activity")
                .select("contact_id, phone_identity_key, phone_e164, phone_normalized, wati_lookup_phone, display_phone, last_inbound_at, current_journey_stage")
                .eq("tenant_id", tenant_id)
                .order("contact_id")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            all_data.extend(response.data)
            if len(response.data) < page_size:
                break
            offset += page_size
        return all_data
    except Exception as e:
        print(f"Error fetching contact activity: {e}")
        return []


def has_messages_in_silver(tenant_id, contact_phone):
    client = get_supabase_client()
    try:
        contact_resp = (
            client.schema("silver")
            .table("contacts")
            .select("contact_id")
            .eq("tenant_id", tenant_id)
            .eq("wati_lookup_phone", contact_phone)
            .limit(1)
            .execute()
        )
        if not contact_resp.data:
            return 0, False

        contact_id = contact_resp.data[0]["contact_id"]
        response = (
            client.schema("silver")
            .table("messages")
            .select("message_id")
            .eq("tenant_id", tenant_id)
            .eq("contact_id", contact_id)
            .execute()
        )
        return len(response.data), len(response.data) > 0
    except Exception as e:
        return f"Error checking messages: {e}", False


# =====================================================================
# BATCH IMPORT FUNCTIONS
# =====================================================================
def contacts_import_completed(tenant_id: str):
    client = get_supabase_client()
    try:
        result = (client.schema("public").table("tenants")
        .update({"batch_import_contacts_done": True}).eq("tenant_id", tenant_id).execute())
        return result, True
    except Exception as e:
        return f"Error completing initial import flow: {e}", False

def messages_import_completed(tenant_id: str):
    client = get_supabase_client()
    try:
        result = (client.schema("public").table("tenants")
        .update({"batch_import_messages_done": True}).eq("tenant_id", tenant_id).execute())
        return result, True
    except Exception as e:
        return f"Error completing initial import flow: {e}", False
    
def initial_login_complete(tenant_id: str):
    client = get_supabase_client()
    try:
        result = (client.schema("public").table("tenants")
        .update({"first_login": False}).eq("tenant_id", tenant_id).execute())
        return result, True
    except Exception as e:
        return f"Error completing initial import flow: {e}", False

def get_tenant_credentials(tenant_id):
    """
    Get tenant's Wati API credentials for import.

    Args:
        tenant_id: The tenant ID

    Returns:
        Tuple of (tenant_dict, success_bool)
    """
    client = get_supabase_client()

    try:
        response = client.table("tenants").select("*").eq("tenant_id", tenant_id).single().execute()

        if not response.data:
            return "Tenant not found", False

        tenant = response.data

        # Check if tenant has API token
        if not tenant.get("wati_api_token"):
            return "Tenant has no API token configured", False

        return tenant, True

    except Exception as e:
        return f"Error fetching tenant: {e}", False


def get_tenant_record(tenant_id):
    """Fetch a tenant row without requiring Wati credentials."""
    client = get_supabase_client()

    try:
        response = client.table("tenants").select("*").eq("tenant_id", tenant_id).single().execute()

        if not response.data:
            return "Tenant not found", False

        return response.data, True
    except Exception as e:
        return f"Error fetching tenant: {e}", False


def create_import_job(tenant_id, start_date=None, end_date=None):
    """
    Create a new import job record.

    Args:
        tenant_id: The tenant ID
        start_date: Optional start date for import
        end_date: Optional end date for import

    Returns:
        Tuple of (job_dict, success_bool)
    """
    client = get_supabase_client()

    job_data = {
        "tenant_id": tenant_id,
        "status": "pending",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_messages": 0,
        "processed_messages": 0
    }

    if start_date:
        job_data["start_date"] = start_date
    if end_date:
        job_data["end_date"] = end_date

    try:
        response = client.table("import_jobs").insert(job_data).execute()

        if not response.data:
            return "Failed to create import job", False

        return response.data[0], True

    except Exception as e:
        return f"Error creating import job: {e}", False


def update_import_job(job_id, updates=None, **kwargs):
    """
    Update an import job record.

    Args:
        job_id: The job ID (UUID)
        updates: Dictionary of fields to update (or pass as keyword args)

    Returns:
        Tuple of (job_dict, success_bool)
    """
    if updates is None:
        updates = kwargs
    elif kwargs:
        updates = {**updates, **kwargs}

    client = get_supabase_client()

    try:
        response = client.table("import_jobs").update(updates).eq("job_id", job_id).execute()

        if not response.data:
            return "Failed to update import job", False

        return response.data[0], True

    except Exception as e:
        return f"Error updating import job: {e}", False


def insert_bronze_contacts(tenant_id, batch_id, contacts):
    """
    Bulk insert all contacts into bronze.wati_contacts table in a single request.

    Args:
        tenant_id: The tenant ID
        batch_id: The import job ID (for tracking)
        contacts: List of contact dicts from Wati API

    Returns:
        Tuple of (count, success_bool)
    """
    client = get_supabase_client()

    if not contacts:
        return 0, True

    # Build full list of records upfront, and deduplicate by contact ID
    records = []
    seen_contacts = set()
    for contact in contacts:
        if contact.get("id") not in seen_contacts:
            seen_contacts.add(contact.get("id"))
            records.append({
                "tenant_id": tenant_id,
                "batch_id": batch_id,
                "wati_contact_id": contact.get("id", "Missing"),
                "raw_data": contact,
            })
        else:
            print(f"Skipping duplicate contact {contact.get('id', 'Missing')}")
    print(f"Total contacts processed: {len(records)}")

    try:
        # Single bulk insert of all records
        response = (
            client.schema("bronze")
            .table("wati_contacts")
            .upsert(records, on_conflict="tenant_id, wati_contact_id", ignore_duplicates=True)
            .execute()
        )

        inserted_count = len(response.data) if response.data else 0

        return inserted_count, True

    except Exception as e:
        return f"Error inserting bronze contacts: {e}", False

def insert_bronze_messages(tenant_id, batch_id, messages, contact_id):
    """
    Insert messages into the bronze layer.
    
    Args:
        tenant_id: The tenant ID
        batch_id: The import job ID (for tracking)
        messages: List of message dicts from Wati API
    
    Returns:
        Tuple of (count, success_bool)
    """
    client = get_supabase_client()
    
    if not messages:
        return 0, True
    
    # Build full list of records
    records = []
    for message in messages:
        # Wati's /getMessages API doesn't always return conversationId.
        # Fall back to the same sentinel the bronze.wati_messages DEFAULT
        # and the webhook trigger use, so batch imports don't crash on
        # NOT NULL. See database/02_bronze_layer.sql.
        convo_id = message.get("conversationId") or "Conversation had no ID"
        message_id = message.get("id")
        records.append({
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "conversation_id": convo_id,
            "wati_message_id": message_id,
            "wati_contact_id": contact_id,
            "raw_data": message,
        })
    
    try:
        # Single bulk insert of all records
        response = (
            client.schema("bronze")
            .table("wati_messages")
            .upsert(records, on_conflict="tenant_id,wati_message_id", ignore_duplicates=True)
            .execute()
        )
        
        inserted_count = len(response.data) if response.data else 0

        return inserted_count, True

    except Exception as e:
        return f"Error inserting bronze messages: {e}", False


def process_contacts_bronze_to_silver(batch_id):
    """
    Process contacts from bronze layer to silver layer.

    Calls the bronze.process_contacts_to_silver() database function
    which handles deduplication, phone normalization, and upserts.

    Args:
        batch_id: The batch ID (UUID) to process

    Returns:
        Tuple of (result_dict, success_bool)
    """
    client = get_supabase_client()

    try:
        # Call the database function
        response = client.schema("bronze").rpc('process_contacts_to_silver', {
            'p_batch_id': batch_id
        }).execute()

        if response.data:
            result = response.data
            print(f"✅ Bronze→Silver processing complete:")
            print(f"   - Contacts processed: {result.get('contacts_processed', 0)}")
            print(f"   - Created: {result.get('contacts_created', 0)}")
            print(f"   - Updated: {result.get('contacts_updated', 0)}")
            return result, True
        else:
            return "No data returned from processing function", False

    except Exception as e:
        return f"Error processing bronze to silver: {e}", False


def process_messages_bronze_to_silver(batch_id):
    """
    Process messages from bronze layer to silver layer.

    Calls the bronze.process_messages_to_silver() database function
    which handles deduplication, phone normalization, and upserts.

    Args:
        batch_id: The batch ID (UUID) to process

    Returns:
        Tuple of (result_dict, success_bool)
    """
    client = get_supabase_client()

    try:
        # Call the database function
        response = client.schema("bronze").rpc('process_messages_to_silver', {
            'p_batch_id': batch_id
        }).execute()

        if response.data:
            result = response.data
            print(f"✅ Bronze→Silver processing complete:")
            print(f"   - Messages processed: {result.get('messages_processed', 0)}")
            print(f"   - Created: {result.get('messages_created', 0)}")
            print(f"   - Updated: {result.get('messages_updated', 0)}")
            return result, True
        else:
            return "No data returned from processing function", False

    except Exception as e:
        return f"Error processing bronze to silver: {e}", False


def mark_job_completed(job_id, total_contacts):
    """
    Mark import job as completed.

    Args:
        job_id: The job ID (UUID)
        total_contacts: Total number of contacts imported

    Returns:
        Tuple of (job_dict, success_bool)
    """
    updates = {
        "status": "completed",
        "total_messages": total_contacts,
        "processed_messages": total_contacts,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    return update_import_job(job_id, updates)


def mark_job_failed(job_id, error_message):
    """
    Mark import job as failed.

    Args:
        job_id: The job ID (UUID)
        error_message: Error description

    Returns:
        Tuple of (job_dict, success_bool)
    """
    updates = {
        "status": "failed",
        "error_message": error_message,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    return update_import_job(job_id, updates)


# =====================================================================
# MOLD-5: Resumable backfill helpers
# =====================================================================

def upsert_sync_progress(tenant_id, wati_contact_id, messages_synced, message_count=0, error_message=None):
    """
    Upsert a row in bronze.sync_progress for a single contact.

    Args:
        tenant_id: Tenant ID
        wati_contact_id: Wati contact ID
        messages_synced: True if messages were successfully synced
        message_count: Number of messages synced
        error_message: Error message if failed (truncated to 500 chars)

    Returns:
        Tuple of (data, success_bool)
    """
    client = get_supabase_client()
    row = {
        "tenant_id": tenant_id,
        "wati_contact_id": wati_contact_id,
        "messages_synced": messages_synced,
        "message_count": message_count,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if error_message is not None:
        row["error_message"] = str(error_message)[:500]

    try:
        response = (
            client.schema("bronze").table("sync_progress")
            .upsert(row, on_conflict="tenant_id,wati_contact_id")
            .execute()
        )
        return response.data, True
    except Exception as e:
        return f"Error upserting sync_progress: {e}", False


def get_synced_contact_ids(tenant_id):
    """
    Return the set of wati_contact_ids already fully synced for a tenant.

    Returns:
        set of wati_contact_id strings
    """
    client = get_supabase_client()
    try:
        page_size = 1000
        offset = 0
        result = set()
        while True:
            response = (
                client.schema("bronze").table("sync_progress")
                .select("wati_contact_id")
                .eq("tenant_id", tenant_id)
                .eq("messages_synced", True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = response.data or []
            for row in rows:
                result.add(row["wati_contact_id"])
            if len(rows) < page_size:
                break
            offset += page_size
        return result
    except Exception as e:
        print(f"Warning: could not load sync_progress: {e}")
        return set()


def get_sync_progress_stats(tenant_id):
    """
    Return stats from bronze.sync_progress for a tenant.

    Returns:
        dict with keys: total_synced, total_failed, total
    """
    client = get_supabase_client()
    try:
        synced_resp = (
            client.schema("bronze").table("sync_progress")
            .select("wati_contact_id", count="exact")
            .eq("tenant_id", tenant_id)
            .eq("messages_synced", True)
            .limit(0)
            .execute()
        )
        total_resp = (
            client.schema("bronze").table("sync_progress")
            .select("wati_contact_id", count="exact")
            .eq("tenant_id", tenant_id)
            .limit(0)
            .execute()
        )
        synced = synced_resp.count or 0
        total = total_resp.count or 0
        return {"total_synced": synced, "total_failed": total - synced, "total": total}
    except Exception as e:
        return {"total_synced": 0, "total_failed": 0, "total": 0, "error": str(e)}


def get_active_job(tenant_id):
    """
    Return the active (running or pending) import job for a tenant, or None.

    Returns:
        Tuple of (job_dict or None, success_bool)
    """
    client = get_supabase_client()
    try:
        response = (
            client.table("import_jobs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .in_("status", ["running", "pending"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if response.data:
            return response.data[0], True
        return None, True
    except Exception as e:
        return f"Error fetching active job: {e}", False


def get_import_jobs_by_tenant(tenant_id, limit=10):
    """
    Return recent import jobs for a tenant, newest first.

    Args:
        tenant_id: Tenant ID
        limit: Max rows to return (default 10)

    Returns:
        Tuple of (list_of_job_dicts, success_bool)
    """
    client = get_supabase_client()
    try:
        response = (
            client.table("import_jobs")
            .select("job_id, status, processed_messages, created_at, completed_at, error_message, subprocess_pid, log_path")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data or [], True
    except Exception as e:
        return [], False


# =====================================================================
# MOLD-6: Classifier config helpers
# =====================================================================

def get_active_classifier_config(tenant_id):
    """
    Return the active classifier config for a tenant, including its stages.

    Returns:
        Tuple of (config_dict_with_stages or None, success_bool)
        config_dict has keys: config_id, version, master_prompt, is_active,
                              created_at, activated_at, notes, stages (list)
    """
    client = get_supabase_client()
    try:
        config_resp = (
            client.table("tenant_classifier_configs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )
        if not config_resp.data:
            return None, True
        config = config_resp.data[0]
        stages_resp = (
            client.table("tenant_journey_stages")
            .select("stage_id, stage_name, stage_description, display_order")
            .eq("config_id", config["config_id"])
            .order("display_order")
            .execute()
        )
        config["stages"] = stages_resp.data or []
        return config, True
    except Exception as e:
        return f"Error loading active config: {e}", False


def get_draft_classifier_config(tenant_id):
    """
    Return the most recently created inactive (draft) classifier config, or None.
    Convention: draft = most recently created is_active=FALSE row.

    Returns:
        Tuple of (config_dict_with_stages or None, success_bool)
    """
    client = get_supabase_client()
    try:
        config_resp = (
            client.table("tenant_classifier_configs")
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("is_active", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not config_resp.data:
            return None, True
        config = config_resp.data[0]
        stages_resp = (
            client.table("tenant_journey_stages")
            .select("stage_id, stage_name, stage_description, display_order")
            .eq("config_id", config["config_id"])
            .order("display_order")
            .execute()
        )
        config["stages"] = stages_resp.data or []
        return config, True
    except Exception as e:
        return f"Error loading draft config: {e}", False


def save_classifier_draft(tenant_id, master_prompt, stages, notes=None):
    """
    Upsert a draft classifier config for a tenant.

    If a draft already exists (is_active=FALSE, most recent), update it in place.
    Otherwise insert a new draft with version = active_version + 1.

    Args:
        tenant_id: Tenant ID
        master_prompt: Full prompt text
        stages: list of dicts with keys: stage_name, stage_description, display_order
        notes: Optional notes string

    Returns:
        Tuple of (config_dict or error_str, success_bool)
    """
    if not stages:
        return "Cannot save with zero stages", False

    client = get_supabase_client()
    try:
        # Find existing draft
        draft_resp = (
            client.table("tenant_classifier_configs")
            .select("config_id")
            .eq("tenant_id", tenant_id)
            .eq("is_active", False)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )

        if draft_resp.data:
            config_id = draft_resp.data[0]["config_id"]
            # Update existing draft prompt + notes
            client.table("tenant_classifier_configs").update(
                {"master_prompt": master_prompt, "notes": notes}
            ).eq("config_id", config_id).execute()
        else:
            # Determine next version number
            active_resp = (
                client.table("tenant_classifier_configs")
                .select("version")
                .eq("tenant_id", tenant_id)
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
            next_version = (active_resp.data[0]["version"] + 1) if active_resp.data else 1
            new_resp = (
                client.table("tenant_classifier_configs")
                .insert({
                    "tenant_id": tenant_id,
                    "version": next_version,
                    "master_prompt": master_prompt,
                    "is_active": False,
                    "notes": notes,
                })
                .execute()
            )
            config_id = new_resp.data[0]["config_id"]

        # Replace child stages: delete existing, insert new
        client.table("tenant_journey_stages").delete().eq("config_id", config_id).execute()
        if stages:
            stage_rows = [
                {
                    "config_id": config_id,
                    "tenant_id": tenant_id,
                    "stage_name": s["stage_name"],
                    "stage_description": s["stage_description"],
                    "display_order": s.get("display_order", i),
                }
                for i, s in enumerate(stages)
            ]
            client.table("tenant_journey_stages").insert(stage_rows).execute()

        return get_draft_classifier_config(tenant_id)[0] or {"config_id": config_id}, True
    except Exception as e:
        return f"Error saving draft: {e}", False


def activate_classifier_config(tenant_id, config_id):
    """
    Atomically activate a classifier config via the RPC.

    Returns:
        Tuple of (None or error_str, success_bool)
    """
    client = get_supabase_client()
    try:
        client.rpc("activate_classifier_config", {
            "p_tenant_id": tenant_id,
            "p_config_id": config_id,
        }).execute()
        return None, True
    except Exception as e:
        return f"Error activating config: {e}", False


def get_classifier_version_history(tenant_id, limit=10):
    """
    Return recent classifier config versions for a tenant, newest first.

    Returns:
        Tuple of (list_of_config_dicts, success_bool)
    """
    client = get_supabase_client()
    try:
        resp = (
            client.table("tenant_classifier_configs")
            .select("config_id, version, is_active, created_at, activated_at, notes, master_prompt")
            .eq("tenant_id", tenant_id)
            .order("version", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or [], True
    except Exception as e:
        return [], False


def get_stale_contact_count(tenant_id, active_version):
    """
    Count contacts in silver.journey_intent_results that were classified with
    an older config version than active_version.

    Returns:
        int (count), or 0 on error
    """
    client = get_supabase_client()
    try:
        resp = (
            client.schema("silver").table("journey_intent_results")
            .select("contact_id", count="exact")
            .eq("tenant_id", tenant_id)
            .not_.like("classifier_version", f"%/v{active_version}")
            .limit(0)
            .execute()
        )
        return resp.count or 0
    except Exception:
        return 0

def get_classify_since_date(tenant_id):
    client = get_supabase_client()
    try:
        resp = (
            client.schema("public").table("tenants")
            .select("classify_since_date")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        return resp.data[0]["classify_since_date"] if resp.data else None
    except Exception:
        return None

def set_classify_since_date(tenant_id, classify_since_date):
    client = get_supabase_client()
    try:
        client.schema("public").table("tenants").update({"classify_since_date": classify_since_date}).eq("tenant_id", tenant_id).execute()
        return True
    except Exception:
        return False
