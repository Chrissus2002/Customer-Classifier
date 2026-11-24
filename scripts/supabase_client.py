"""
Supabase Database Connection Module

Provides a reusable Supabase client for database operations.
Import this in your scripts to interact with the database.

Usage:
    from scripts.supabase_client import get_supabase_client, execute_sql

    # Get client
    supabase = get_supabase_client()

    # Query data
    response = supabase.table('tenants').select('*').execute()

    # Execute SQL
    result = execute_sql("SELECT * FROM tenants WHERE status = 'active'")
"""

import os
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from supabase import create_client, Client
import logging

# Load environment variables
load_dotenv()
# Create logger to check for potential issues
logger = logging.getLogger(__name__)


def get_supabase_client() -> Client:
    """
    Create and return a Supabase client instance.

    Returns:
        Supabase Client instance

    Raises:
        ValueError: If required environment variables are missing
    """
    supabase_url = os.getenv('SUPABASE_URL')
    supabase_key = os.getenv('SUPABASE_ANON_KEY')

    logger.info(f"Supabase URL: {supabase_url}")
    logger.info(f"Supabase Key: {supabase_key}")
    if not supabase_url:
        raise ValueError(
            "SUPABASE_URL not found in environment variables. "
            "Please check your .env file."
        )

    if not supabase_key:
        raise ValueError(
            "SUPABASE_KEY not found in environment variables. "
            "Please check your .env file."
        )

    try:
        client = create_client(supabase_url, supabase_key)
        return client
    except Exception as e:
        raise ConnectionError(f"Failed to connect to Supabase: {e}")


def execute_sql(query: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """
    Execute a raw SQL query using Supabase RPC.

    Args:
        query: SQL query string
        params: Optional dictionary of query parameters

    Returns:
        Query result

    Example:
        result = execute_sql("SELECT * FROM tenants WHERE status = $1", {"1": "active"})
    """
    client = get_supabase_client()

    try:
        # Note: For raw SQL, you may need to create a database function
        # This is a placeholder - adapt based on your actual setup
        response = client.rpc('execute_query', {'query': query, 'params': params}).execute()
        return response.data
    except Exception as e:
        raise RuntimeError(f"SQL execution failed: {e}")


def test_connection() -> bool:
    """
    Test the Supabase connection.

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = get_supabase_client()
        # Try a simple query
        response = client.table('tenants').select('tenant_id').limit(1).execute()
        print("✅ Supabase connection successful!")
        print(f"   URL: {os.getenv('SUPABASE_URL')}")
        return True
    except Exception as e:
        print(f"❌ Supabase connection failed: {e}")
        return False

def get_tenant_by_id(tenant_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a specific tenant by ID.

    Args:
        tenant_id: Tenant ID to fetch

    Returns:
        Tenant dictionary or None if not found
    """
    client = get_supabase_client()

    try:
        response = client.table('tenants').select('*').eq('tenant_id', tenant_id).single().execute()
        return response.data
    except Exception as e:
        print(f"Warning: Failed to fetch tenant {tenant_id}: {e}")
        return None


def get_tenant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific tenant by slug.

    Args:
        slug: Tenant slug (e.g., 'filippa')

    Returns:
        Tenant dictionary or None if not found
    """
    client = get_supabase_client()

    try:
        response = client.table('tenants').select('*').eq('slug', slug).single().execute()
        return response.data
    except Exception as e:
        print(f"Warning: Failed to fetch tenant with slug '{slug}': {e}")
        return None


def create_tenant(
    name: str,
    slug: str,
    wati_api_token: str,
    wati_phone_number: Optional[str] = None,
    default_journey_stages: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a new tenant.

    Args:
        name: Tenant name (e.g., "Filippa")
        slug: Unique slug (e.g., "filippa")
        wati_api_token: Wati API token
        wati_phone_number: Optional Wati phone number
        default_journey_stages: Optional list of journey stage names

    Returns:
        Created tenant dictionary
    """
    client = get_supabase_client()

    tenant_data = {
        'name': name,
        'slug': slug,
        'wati_api_token': wati_api_token,
        'wati_phone_number': wati_phone_number,
        'default_journey_stages': default_journey_stages or [
            'browsing',
            'purchase_intent',
            'order_support',
            'wholesale_inquiry',
            'location_inquiry'
        ],
        'status': 'active'
    }

    try:
        response = client.table('tenants').insert(tenant_data).execute()
        print(f"✅ Created tenant: {name} ({slug})")
        return response.data[0]
    except Exception as e:
        raise RuntimeError(f"Failed to create tenant: {e}")


if __name__ == "__main__":
    """Test the connection when run directly."""
    print("Testing Supabase connection...")
    print("=" * 60)

    if test_connection():
        print()
        print("Fetching tenants...")
        try:
            tenants = get_supabase_client().table("tenants").select("tenant_id, name, slug").execute().data
            if tenants:
                print(f"Found {len(tenants)} active tenant(s):")
                for tenant in tenants:
                    print(f"  - {tenant['name']} (slug: {tenant['slug']})")
            else:
                print("No tenants found in database.")
        except Exception as e:
            print(f"Error fetching tenants: {e}")
