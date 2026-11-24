"""
Classification Worker

Batch-processes unclassified contacts for one or all tenants.

Usage:
    python -m scripts.classify_worker --tenant all
    python -m scripts.classify_worker --tenant YOUR_TENANT_ID
    python -m scripts.classify_worker --tenant YOUR_TENANT_ID --provider openai --model gpt-4o-mini
"""

import argparse
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Ensure scripts/ is on the path so sibling imports work regardless of how
# the script is invoked (python scripts/classify_worker.py OR python -m scripts.classify_worker)
sys.path.insert(0, str(Path(__file__).parent))

from classifiers.factory import get_classifier
from classifiers.orchestrator import JourneyClassifier
from supabase_client import get_supabase_client


def classify_contact_with_retry(
    classifier: JourneyClassifier,
    tenant_id: int,
    contact_id: str,
    tenant_config: tuple,
):
    """Classify a single contact, retrying on failure with a 5-second delay."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            return classifier.classify_and_store(tenant_id, contact_id, tenant_config=tenant_config)
        except Exception as e:
            if attempt < max_retries:
                print(f"    Attempt {attempt} failed: {e} — retrying in 5s...")
                time.sleep(5)
            else:
                print(f"    Attempt {attempt} failed: {e} — giving up")
                raise


def get_classify_since_date(tenant_id: int) -> str:
    """Fetch classify_since_date from DB, fall back to the orchestrator default."""
    default = "2026-01-01"
    try:
        client = get_supabase_client()
        resp = client.table("tenants").select("classify_since_date").eq("tenant_id", tenant_id).single().execute()
        return resp.data.get("classify_since_date") or default
    except Exception as e:
        print(f"Warning: could not fetch classify_since_date: {e}")
        return default


def classify_tenant(tenant_id: int, classifier: JourneyClassifier, batch_size: int):
    """Classify all unclassified contacts for a tenant."""
    # Load config once — eliminates per-contact DB round trips for tenant config
    tenant_config = classifier.get_tenant_config(tenant_id)
    _, _, version = tenant_config
    print(f"  Config version: v{version}")

    since_date = get_classify_since_date(tenant_id)
    print(f"  Classify since: {since_date}")

    succeeded = 0
    failed = 0
    while True:
        unclassified, reclassify_contacts = classifier.get_unclassified_contacts(tenant_id, batch_size, since_date=since_date)
        print(f"  Found {len(unclassified)} unclassified contact(s)")
        for i, contact in enumerate(unclassified):
            contact_id = contact["contact_id"]
            try:
                result = classify_contact_with_retry(classifier, tenant_id, contact_id, tenant_config)
                succeeded += 1
                if contact_id in reclassify_contacts:
                    print(f"  [{i+1}/{len(unclassified)}] RECLASSIFIED {contact_id[:8]}... -> {result.journey_stage} ({result.confidence:.2f})")
                else:
                    print(
                        f"  [{i+1}/{len(unclassified)}] {contact_id[:8]}... "
                        f"-> {result.journey_stage} ({result.confidence:.2f})"
                    )
            except Exception:
                failed += 1
                print(f"  [{i+1}/{len(unclassified)}] {contact_id[:8]}... FAILED after retries")
        if len(unclassified) < batch_size:
            break

    print(f"  Summary: {succeeded} classified, {failed} failed")
    return succeeded


def main():
    parser = argparse.ArgumentParser(description="Classify unclassified contacts")
    parser.add_argument(
        "--tenant",
        required=True,
        help="Tenant ID or 'all' to process all tenants",
    )
    parser.add_argument("--provider", default=None, help="LLM provider override")
    parser.add_argument("--model", default=None, help="Model name override")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("PRODUCTION_BATCH_SIZE", "20")),
        help="Max contacts per tenant per run",
    )
    args = parser.parse_args()

    provider = get_classifier(provider=args.provider, model=args.model)
    orchestrator = JourneyClassifier(classifier=provider)

    print(f"Provider: {provider.provider_name}/{provider.model_name}")
    print(f"Batch size: {args.batch_size}")
    print()

    if args.tenant == "all":
        client = get_supabase_client()
        tenants = client.table("tenants").select("tenant_id, name").eq("status", "active").execute()
        for tenant in tenants.data or []:
            print(f"Tenant: {tenant['name']} ({tenant['tenant_id']})")
            classify_tenant(tenant["tenant_id"], orchestrator, args.batch_size)
            print()
    else:
        tenant_id = int(args.tenant)
        print(f"Tenant: {tenant_id}")
        classify_tenant(tenant_id, orchestrator, args.batch_size)

    print("Done.")


if __name__ == "__main__":
    main()
