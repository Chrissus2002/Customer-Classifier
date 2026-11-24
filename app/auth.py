import streamlit as st
from dotenv import load_dotenv
from pathlib import Path
import os
import yaml
import bcrypt
from database import insert_tenant_into_db, retrieve_tenant_from_db, hash_password

# TODO: Eventual fixes needed for security:
# - Do not use session_state to store sensitive user data
# - Look for a way to hide the users API keys and wati credentials

load_dotenv()

# Load app config
_config_path = Path(__file__).parent.parent / "config.yaml"
with open(_config_path) as f:
    APP_CONFIG = yaml.safe_load(f)

admin_username = os.getenv('ADMIN_USERNAME', '')
admin_password_hash = os.getenv('ADMIN_PASSWORD_HASH', '')


def show_registration_form():
    """Display the tenant registration form."""
    st.title("Tenant Registration")

    col1, col2 = st.columns(2)
    items = {}

    with col1:
        tenant_name = st.text_input("Tenant Name", placeholder="Enter tenant name")
        slug_suggestion = tenant_name.lower().replace(" ", "-") if tenant_name else ""
        username = st.text_input("Username", placeholder="Enter username", value=slug_suggestion)
        phone = st.text_input("Wati Phone number", placeholder="Enter wati phone number")

    with col2:
        wati_tenant_id = st.text_input("Wati Tenant ID", placeholder="Enter wati tenant id", max_chars=8)
        password = st.text_input("Password", type="password", placeholder="Enter password")
        confirm_password = st.text_input("Confirm Password", type="password", placeholder="Confirm password")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Register", use_container_width=True):
            if password != confirm_password or not password or not confirm_password:
                st.error("Passwords do not match or are empty")
            else:
                hashed_password = hash_password(password)
                items = {
                    "tenant_id": wati_tenant_id,
                    "name": tenant_name,
                    "wati_api_token": None,
                    "webhook_url": "https://live-mt-server.wati.io/" + wati_tenant_id,
                    "slug": username,
                    "wati_phone_number": phone,
                    "password": hashed_password
                }
                result, is_success = insert_tenant_into_db(items)
                if not is_success:
                    st.error(result)
                else:
                    st.success(f"✅ Tenant '{tenant_name}' registered successfully!")
                    st.info("You can now log in with your credentials.")
    with col_b:
        if st.button("Back to Login", use_container_width=True):
            st.session_state.show_registration = False
            st.rerun()
    

def _auto_login_single_tenant():
    """Auto-authenticate when config.yaml auth.mode is single_tenant."""
    from database import get_tenant_credentials, update_wati_credentials
    tenant_id = APP_CONFIG["auth"]["default_tenant_id"]
    tenant, ok = get_tenant_credentials(tenant_id)
    if not ok:
        st.error(f"Single-tenant auto-login failed: {tenant}")
        st.stop()

    # Sync wati config from config.yaml + .env into the DB
    wati_phone = APP_CONFIG.get("wati", {}).get("phone")
    wati_token = os.getenv("WATI_API_TOKEN") or os.getenv("WATI_DEFAULT_TOKEN")
    needs_sync = (
        (wati_phone and wati_phone != tenant.get("wati_phone_number"))
        or (wati_token and wati_token != tenant.get("wati_api_token"))
    )
    if needs_sync:
        update_wati_credentials(
            tenant_id,
            wati_api_token=wati_token if wati_token else None,
            wati_phone_number=wati_phone if wati_phone else None,
        )

    st.session_state.authenticated = True
    st.session_state.username = tenant.get("slug", "admin")
    st.session_state.tenant_id = tenant["tenant_id"]
    st.session_state.first_login = tenant.get("first_login", False)
    st.session_state.batch_import_contacts = tenant.get("batch_import_contacts_done", True)
    st.session_state.batch_import_messages = tenant.get("batch_import_messages_done", True)


def login_form():
    """Check if user is authenticated. If not, show login form and stop."""

    # Initialize session state
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = ""
    if "show_registration" not in st.session_state:
        st.session_state.show_registration = False

    # If already authenticated, return immediately (don't show login)
    if st.session_state.authenticated:
        return True

    # Single-tenant mode: skip the login form entirely
    if APP_CONFIG.get("auth", {}).get("mode") == "single_tenant":
        _auto_login_single_tenant()
        return True

    # Show registration form if requested
    if st.session_state.show_registration:
        show_registration_form()
        st.stop()

    # Not authenticated - show login form
    st.title("Authentication Required")
    st.write("Please enter your credentials to access the application.")
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col2:
        tenant_id = st.text_input("Tenant ID", placeholder="Enter your tenant ID", max_chars=8)
        username = st.text_input("Username", placeholder="Enter your username")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        login = st.button("Login", use_container_width=True)
        create_tenant = st.button("Create Tenant", use_container_width=True)

    if create_tenant:
        st.session_state.show_registration = True
        st.rerun()

    if login:
        tenant_response, found_tenant = retrieve_tenant_from_db(tenant_id, username, password)
        if found_tenant:
            st.session_state.authenticated = True
            st.session_state.username = username
            st.session_state.tenant_id = tenant_response.get("tenant_id")
            st.session_state.first_login = tenant_response.get("first_login")
            st.session_state.batch_import_contacts = tenant_response.get("batch_import_contacts_done")
            st.session_state.batch_import_messages = tenant_response.get("batch_import_messages_done")
            st.rerun()  # Refresh page to show main content
        else:
            st.error(tenant_response)
            return False

    # Stop execution so the rest of the page doesn't render
    st.stop()

def require_authentication():
    if not login_form():
        st.stop()

def logout_button():
    """Display a logout button in the sidebar."""
    with st.sidebar:
        if st.button("Logout", use_container_width=True):
            # Clear all session state on logout
            for key in ["authenticated", "username", "tenant_data", "tenant_id",
                        "first_login", "batch_import_contacts", "batch_import_messages",
                        "batch_imports_contacts_done"]:
                st.session_state.pop(key, None)
            st.rerun()

def setup_page(title=None):
    """
    Setup function to call at the top of every page.
    - Checks authentication (redirects to login if not authenticated)
    - Shows logout button in sidebar
    - Optionally sets page title

    Usage:
        from auth import setup_page
        setup_page("Journey Analytics")

        # Rest of your page code here...
    """
    require_authentication()
    logout_button()

    if title:
        st.title(title)