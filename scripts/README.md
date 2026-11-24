# Scripts Directory

Utility scripts for database operations, admin tasks, and development tools.

## Database Scripts

### 🔌 `supabase_client.py`
Reusable Supabase connection module. Import this in your scripts to interact with the database.

**Usage:**
```python
from scripts.supabase_client import get_supabase_client, get_all_tenants

# Get client
supabase = get_supabase_client()

# Use built-in helpers
tenants = get_all_tenants()
```

### ✅ `test_connection.py`
Test your Supabase connection and display tenant information.

**Usage:**
```bash
python scripts/test_connection.py
```

### ➕ `create_tenant.py`
Interactive script to create a new tenant in the database.

**Usage:**
```bash
python scripts/create_tenant.py
```

Prompts you for:
- Tenant name
- Tenant slug (unique identifier)
- Wati API token
- Wati phone number (optional)
- Journey stages (uses defaults or custom)

## Authentication Scripts

### 🔐 `generate_password_hash.py`
Generate bcrypt password hashes for admin authentication.

**Usage:**
```bash
python scripts/generate_password_hash.py
```

Follow the prompts to enter your password and get a hash to add to your `.env` file.

## Common Workflows

### Setting Up a New Environment

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Generate admin password:**
   ```bash
   python scripts/generate_password_hash.py
   # Add output to .env as ADMIN_PASSWORD_HASH
   ```

3. **Test database connection:**
   ```bash
   python scripts/test_connection.py
   ```

4. **Create first tenant:**
   ```bash
   python scripts/create_tenant.py
   ```

### Checking Database Status

```bash
# Quick connection test
python scripts/test_connection.py

# See all tenants
python -c "from scripts.supabase_client import get_all_tenants; print(get_all_tenants())"
```

### Creating Custom Scripts

Import the Supabase client in your own scripts:

```python
# my_custom_script.py
from scripts.supabase_client import get_supabase_client

supabase = get_supabase_client()

# Your custom operations here
response = supabase.table('contacts').select('*').limit(10).execute()
print(response.data)
```

## Helper Functions in `supabase_client.py`

| Function | Description |
|----------|-------------|
| `get_supabase_client()` | Get authenticated Supabase client |
| `test_connection()` | Test database connection |
| `get_all_tenants()` | Fetch all active tenants |
| `get_tenant_by_id(id)` | Get tenant by ID |
| `get_tenant_by_slug(slug)` | Get tenant by slug |
| `create_tenant(...)` | Create a new tenant |

## Environment Variables Required

Make sure these are set in your `.env` file:

```bash
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key
```

## Troubleshooting

**Connection fails:**
- Check `.env` file exists and has correct credentials
- Verify Supabase project is active
- Check network connection

**Import errors:**
- Make sure you're in the project root directory
- Activate virtual environment: `source .venv/bin/activate`
- Install dependencies: `pip install -r requirements.txt`

**Permission errors:**
- Verify you're using the `service_role` key (not `anon` key)
- Check RLS policies in Supabase dashboard
