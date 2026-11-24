#!/usr/bin/env python3
"""
Batch Import Script for Wati Contacts
Fetches contacts from Wati API and imports them into the database.

Usage:
    python scripts/batch_import.py --tenant-id YOUR_TENANT_ID
"""

import sys
import os
import argparse
import time
from datetime import datetime
from pathlib import Path

# Add parent directory to path to import from app/
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "app"))
sys.path.insert(0, str(project_root / "scripts"))

from wati_client import WatiAPIClient
from daemon_tasks.contact_identity_refresh import ContactIdentityRefreshTask
from database import (
    get_tenant_credentials,
    create_import_job,
    insert_bronze_contacts,
    process_contacts_bronze_to_silver,
    mark_job_completed,
    mark_job_failed,
    get_all_tenants,
)


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Import Wati contacts into database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="Import contacts for all tenants in database"
    )

    parser.add_argument(
        "--tenant-id",
        type=int,
        help="Tenant ID to import contacts for"
    )

    return parser.parse_args()


def run_contact_imports(tenant_id):
    """
    Main import logic.

    Args:
        tenant_id: The tenant ID to import for

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    start_time = time.time()

    print("=" * 60)
    print(f"🚀 Starting batch import for tenant: {tenant_id}")
    print("=" * 60)

    # Step 1: Get tenant credentials
    print("\n🔑 Fetching tenant credentials...")
    tenant, success = get_tenant_credentials(tenant_id)

    if not success:
        print(f"❌ Error: {tenant}")
        return 1

    print(f"   ✅ Found tenant: {tenant.get('name', 'Unknown')}")

    # Step 2: Create import job
    print("\n📋 Creating import job...")
    job, success = create_import_job(tenant_id)

    if not success:
        print(f"❌ Error: {job}")
        return 1

    job_id = job["job_id"]
    print(f"   ✅ Job ID: {job_id}")

    try:
        # Step 3: Initialize Wati API client
        print("\n📡 Initializing Wati API client...")
        wati_client = WatiAPIClient(
            tenant_id=str(tenant_id),
            tenant_access_token=tenant["wati_api_token"]
        )
        print("   ✅ Client ready")

        # Step 4: Fetch contacts from Wati
        print("\n📥 Fetching contacts from Wati API...")
        print("   (This may take a while for large contact lists)")

        all_contacts = wati_client.get_contacts()

        if all_contacts is None:
            raise Exception("Failed to fetch contacts from Wati API")

        print(f"   ✅ Fetched {len(all_contacts)} total contacts")

        # Step 5: Insert into bronze layer
        print("\n💾 Inserting contacts into database...")
        count, success = insert_bronze_contacts(
            tenant_id=tenant_id,
            batch_id=job_id,
            contacts=all_contacts
        )

        if not success:
            raise Exception(f"Failed to insert contacts: {count}")

        print(f"   ✅ Inserted {count} contacts into bronze layer")

        # Step 6: Process bronze to silver
        print("\n⚙️  Processing bronze → silver layer...")
        result, success = process_contacts_bronze_to_silver(job_id)

        if not success:
            raise Exception(f"Failed to process to silver: {result}")

        print(f"   ✅ Processed to silver layer")

        # Step 6b: Populate shadow canonical identity fields and Wati key mappings
        print("\n🧭 Refreshing shadow contact identities...")
        refresh_result = ContactIdentityRefreshTask().run(tenant_id)
        if refresh_result.status != "success":
            raise Exception(
                "Failed to refresh shadow contact identities: "
                f"{refresh_result.error_message or refresh_result.notes or 'unknown error'}"
            )
        print(
            "   ✅ Shadow identity coverage: "
            f"{refresh_result.result.get('shadow_coverage_pct', 0):.2f}% "
            f"({refresh_result.result.get('covered_active_contacts', 0)}/"
            f"{refresh_result.result.get('active_contacts', 0)})"
        )

        # Step 7: Mark job as completed
        print("\n📊 Updating job status...")
        result, success = mark_job_completed(job_id, len(all_contacts))

        if not success:
            print(f"   ⚠️ Warning: Failed to update job status: {result}")
        else:
            print("   ✅ Job marked as completed")

        # Success summary
        duration = time.time() - start_time
        print("\n" + "=" * 60)
        print("✅ Import completed successfully!")
        print("=" * 60)
        print(f"  Tenant ID:      {tenant_id}")
        print(f"  Tenant Name:    {tenant.get('name', 'Unknown')}")
        print(f"  Batch ID:       {job_id}")
        print(f"  Total Contacts: {len(all_contacts)}")
        print(f"  Duration:       {duration:.2f} seconds")
        print("=" * 60)

        return 0  # Success

    except KeyboardInterrupt:
        print("\n\n⚠️ Import interrupted by user")
        mark_job_failed(job_id, "Interrupted by user")
        return 1

    except Exception as e:

        # Mark job as failed
        mark_job_failed(job_id, str(e))

        print("\n" + "=" * 60)
        print("❌ Import failed")
        print("=" * 60)
        print(f"  Tenant ID:  {tenant_id}")
        print(f"  Batch ID:   {job_id}")
        print(f"  Error:      {e}")

        return 1  # Failure


def main():
    """Entry point for the script."""
    args = parse_arguments()

    if args.all:
        tenants = get_all_tenants()
        if isinstance(tenants, tuple):
            print(f"❌ Error fetching tenants: {tenants[0]}")
            sys.exit(1)
        any_failed = False
        for tenant in tenants:
            if run_contact_imports(tenant["tenant_id"]) != 0:
                any_failed = True
        sys.exit(1 if any_failed else 0)
    elif args.tenant_id:
        sys.exit(run_contact_imports(args.tenant_id))
    else:
        print("❌ Error: provide --tenant-id <id> or --all")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
