"""
Batch import of Wati messages into the bronze layer (then bronze → silver).

Intended use:
  - Run once at the start of business to backfill historical conversation data.
  - Run again anytime you want to catch up missed messages; the upsert is
    idempotent (composite key tenant_id,wati_message_id), so re-runs are safe.
  - The webhook handles real-time incoming messages — this script does NOT
    replace the webhook, it complements it for history backfill.

Prerequisites:
  - The target tenant must already exist in public.tenants with a valid
    wati_api_token and status='active'.
  - silver.contacts must already contain contacts for this tenant. Run
    batch_contact_imports.py first. (The message→silver transform INNER
    JOINs against silver.contacts, so missing contacts silently drop
    messages during bronze→silver processing.)

CLI:
  --tenant-id <int>   Required. Which tenant's messages to backfill.
  --limit <int>       Optional. Process at most N contacts. Default: all.
  --from-file <path>  Optional. Read phone numbers (one per line, normalized
                      Wati lookup form) from a file; only those contacts are processed.
                      Lines starting with '#' and blank lines are skipped.
  --dry-run           Print which contacts WOULD be processed (up to 20 shown)
                      without making any Wati API calls or DB writes.
  --no-resume         Force re-fetch from scratch, ignoring bronze.sync_progress.

Examples:
  python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --limit 5
  python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --dry-run
  python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --from-file phones.txt
  python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --no-resume --limit 3
"""

import sys
import os
import argparse
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path to import from app/ and scripts/
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "app"))
sys.path.insert(0, str(project_root / "scripts"))

load_dotenv()

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logger.info(f"SUPABASE_URL: {'set' if os.getenv('SUPABASE_URL') else 'MISSING'}")
logger.info(f"SUPABASE_ANON_KEY: {'set' if os.getenv('SUPABASE_ANON_KEY') else 'MISSING'}")

from wati_client import WatiAPIClient
from database import (
    get_tenant_credentials,
    create_import_job,
    update_import_job,
    get_all_contacts_by_tenant,
    insert_bronze_messages,
    process_messages_bronze_to_silver,
    mark_job_completed,
    mark_job_failed,
    upsert_sync_progress,
    get_synced_contact_ids,
)


def argument_parser():
    parser = argparse.ArgumentParser(
        description="Import Wati messages per contact into the bronze layer (then bronze → silver).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--tenant-id",
        type=int,
        required=True,
        help="Tenant ID whose messages to import (must already exist in public.tenants with a valid Wati token)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of contacts to process (default: all)",
    )
    parser.add_argument(
        "--from-file",
        type=str,
        default=None,
        help="Path to a file with phone numbers (one per line, normalized form) to process instead of all contacts",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which contacts WOULD be fetched without making API calls or writing to the database",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore bronze.sync_progress and re-process all contacts from scratch",
    )
    parser.add_argument(
        "--job-id",
        type=str,
        default=None,
        help="Use an existing import_jobs UUID instead of creating a new one (used by Streamlit launcher)",
    )

    return parser.parse_args()


def _load_phones_from_file(path):
    """Read a file of phone numbers. Ignore blank lines and # comments."""
    with open(path) as f:
        return {
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        }


def _cancel_flag_path(job_id: str) -> Path:
    return Path(f"/tmp/dialo-cancel-{job_id}")


def _check_cancel(job_id: str) -> bool:
    """Return True if the cancel flag file exists for this job."""
    return _cancel_flag_path(job_id).exists()


def run_imports(tenant_id, limit=None, from_file=None, dry_run=False, no_resume=False, job_id=None):
    # --- 0. Validate inputs ---
    if limit is not None and limit <= 0:
        print(f" - Error: --limit must be a positive integer, got {limit}")
        return 1

    # --- 1. Tenant lookup ---
    tenant, success = get_tenant_credentials(tenant_id)
    if not success:
        print(f" - Error: {tenant}")
        return 1
    print(f" - Found tenant: {tenant.get('name', 'Unknown')}")

    if not tenant.get('wati_api_token'):
        print(
            f" - Error: tenant {tenant_id} has no wati_api_token configured.\n"
            f"   Update public.tenants via the Streamlit UI or SQL."
        )
        return 1

    # --- 2. Precondition: silver.contacts must exist for this tenant ---
    contacts_list = get_all_contacts_by_tenant(tenant_id)
    if not contacts_list:
        print(
            f" - ERROR: No contacts found in silver.contacts for tenant {tenant_id}.\n"
            f"   Run batch_contact_imports.py first — message backfill requires\n"
            f"   contacts to exist in silver.contacts, because the bronze → silver\n"
            f"   transform does an INNER JOIN against silver.contacts and drops\n"
            f"   any message that doesn't match an existing contact."
        )
        return 1

    # --- 3. Filter by --from-file if provided ---
    if from_file:
        try:
            wanted = _load_phones_from_file(from_file)
        except Exception as e:
            print(f" - Error reading {from_file}: {e}")
            return 1
        if not wanted:
            print(f" - {from_file} is empty or all lines commented out")
            return 1
        contacts_list = [
            c for c in contacts_list
            if (c.get('wati_lookup_phone') or c.get('phone_normalized')) in wanted
        ]
        if not contacts_list:
            print(f" - No contacts in silver matched any phone in {from_file}")
            return 1
        print(f" - Filtered to {len(contacts_list)} contact(s) from {from_file}")

    # --- 4. Apply --limit ---
    if limit is not None:
        contacts_list = contacts_list[:limit]

    # --- 5. Dry run: print and exit without side effects ---
    if dry_run:
        print(f" - DRY RUN: would process {len(contacts_list)} contact(s):")
        preview = contacts_list[:20]
        for c in preview:
            name = c.get('name') or '<no name>'
            print(f"     {c.get('wati_lookup_phone') or c.get('phone_normalized')}  ({name})")
        if len(contacts_list) > len(preview):
            print(f"     ... and {len(contacts_list) - len(preview)} more")
        print("\n   Dry run complete. No API calls made, no DB writes.")
        return 0

    # --- 6. Create or adopt import job (non-dry-run only) ---
    if job_id:
        # Job pre-created by Streamlit launcher — adopt it
        print(f" - Using existing import job: {job_id}")
    else:
        import_job, success = create_import_job(tenant_id)
        if not success:
            print(f" - Error creating import job: {import_job}")
            return 1
        job_id = import_job['job_id']
        print(f" - Import job created: {job_id}")

    # --- 6b. Write PID so Streamlit can verify liveness ---
    pid = os.getpid()
    update_import_job(job_id, subprocess_pid=pid)
    print(f" - PID: {pid}")

    # --- 6c. Resume: load already-synced contacts (unless --no-resume) ---
    if no_resume:
        already_synced = set()
        print(" - --no-resume: processing all contacts from scratch")
    else:
        already_synced = get_synced_contact_ids(tenant_id)
        if already_synced:
            print(f" - Resume: skipping {len(already_synced)} already-synced contact(s)")

    contacts_to_process = [
        c for c in contacts_list
        if c.get('wati_contact_id') not in already_synced
    ]
    skipped_count = len(contacts_list) - len(contacts_to_process)
    print(f" - Processing {len(contacts_to_process)} contact(s) ({skipped_count} already synced)")

    # --- 7. Fetch + insert ---
    try:
        messages_fetched = 0    # count of messages returned by the Wati API
        bronze_inserted = 0     # count of rows actually written to bronze (0 on dup re-runs)
        contacts_failed = 0
        contacts_done = 0       # accumulating total of successfully processed contacts
        wati_client = WatiAPIClient(str(tenant_id), tenant['wati_api_token'])

        for i, contact in enumerate(contacts_to_process, 1):
            # Cancellation check every 5 contacts
            if i % 5 == 0 and _check_cancel(job_id):
                print(f"\n - Cancel flag detected at contact {i}. Running bronze → silver for messages so far...")
                process_messages_bronze_to_silver(job_id)
                print(f" - Marking job cancelled.")
                update_import_job(job_id, status='cancelled')
                _cancel_flag_path(job_id).unlink(missing_ok=True)
                return 0

            phone = contact.get('wati_lookup_phone') or contact.get('phone_normalized')
            wati_contact_id = contact.get('wati_contact_id')
            if not phone:
                print(f"   [{i}/{len(contacts_to_process)}] SKIP: contact has no wati_lookup_phone")
                contacts_failed += 1
                upsert_sync_progress(
                    tenant_id, wati_contact_id,
                    messages_synced=False,
                    error_message="no wati_lookup_phone"
                )
                continue

            wati_message_list, fetch_success = wati_client.get_messages_per_contact(phone)
            if not fetch_success:
                print(f"   [{i}/{len(contacts_to_process)}] API error for {phone}; skipping")
                contacts_failed += 1
                upsert_sync_progress(
                    tenant_id, wati_contact_id,
                    messages_synced=False,
                    error_message="API fetch failed"
                )
                continue

            if wati_message_list:
                insert_count, insert_success = insert_bronze_messages(
                    tenant_id, job_id, wati_message_list, wati_contact_id
                )
                if not insert_success:
                    print(f"   [{i}/{len(contacts_to_process)}] Error inserting bronze messages for {phone}: {insert_count}")
                    contacts_failed += 1
                    upsert_sync_progress(
                        tenant_id, wati_contact_id,
                        messages_synced=False,
                        error_message=str(insert_count)[:500]
                    )
                    continue

                messages_fetched += len(wati_message_list)
                if isinstance(insert_count, int):
                    bronze_inserted += insert_count

            # Mark contact done in sync_progress (after bronze write succeeds)
            msg_count = len(wati_message_list) if wati_message_list else 0
            upsert_sync_progress(
                tenant_id, wati_contact_id,
                messages_synced=True,
                message_count=msg_count
            )

            contacts_done += 1
            # Update accumulating progress counter
            update_import_job(job_id, processed_messages=contacts_done)

            if i % 10 == 0 or i == len(contacts_to_process):
                print(
                    f"   progress: {i}/{len(contacts_to_process)} contacts, "
                    f"{messages_fetched} fetched, {bronze_inserted} new in bronze, "
                    f"{contacts_failed} failures"
                )

        # --- 8. Process bronze → silver ---
        silver_created = 0
        silver_skipped = 0
        if messages_fetched == 0:
            print(" - No messages fetched this run, skipping bronze → silver transform.")
        else:
            print(f" - Processing bronze → silver for batch {job_id}")
            response, process_success = process_messages_bronze_to_silver(job_id)
            if not process_success:
                print(f" - Error processing bronze → silver: {response}")
                mark_job_failed(job_id, f"bronze→silver failed: {response}")
                return 1
            if isinstance(response, dict):
                silver_created = response.get('messages_created', 0) or 0
                silver_skipped = response.get('messages_skipped', 0) or 0
                print(
                    f"   bronze → silver: created={silver_created}, "
                    f"skipped={silver_skipped}"
                )
                if silver_skipped > 0 and silver_created == 0:
                    print(
                        "   WARNING: all bronze rows were skipped by the silver "
                        "JOIN. Your silver.contacts may be out of sync with "
                        "the contacts these messages reference."
                    )

        # --- 9. Mark job complete ---
        result, success_job = mark_job_completed(job_id, bronze_inserted)
        if not success_job:
            print(f" - WARNING updating job status: {result}")
            return 1

        print(
            f"\n✅ Job completed!\n"
            f"   Job ID:              {job_id}\n"
            f"   Tenant ID:           {tenant_id}\n"
            f"   Contacts processed:  {contacts_done}/{len(contacts_to_process)}\n"
            f"   Contacts skipped:    {skipped_count} (already synced)\n"
            f"   Messages fetched:    {messages_fetched}\n"
            f"   New bronze rows:     {bronze_inserted}\n"
            f"   New silver rows:     {silver_created}\n"
            f"   Silver skipped:      {silver_skipped}\n"
            f"   Contact failures:    {contacts_failed}\n"
        )
        return 0

    except KeyboardInterrupt:
        print("\n - Interrupted by user")
        mark_job_failed(job_id, "Interrupted by user")
        return 1

    except Exception as e:
        print(f" - Error: {e}")
        mark_job_failed(job_id, str(e))
        return 1


def main():
    args = argument_parser()
    exit_code = run_imports(
        tenant_id=args.tenant_id,
        limit=args.limit,
        from_file=args.from_file,
        dry_run=args.dry_run,
        no_resume=args.no_resume,
        job_id=args.job_id,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
