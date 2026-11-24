# Dialo CX

Multi-tenant AI classification platform for WhatsApp Business conversations. Connects to the [Wati](https://www.wati.io/) API, imports message history per contact, and uses an LLM to classify each customer's position in the buying journey. Results are displayed in a Streamlit analytics dashboard.


## What it does

1. **Ingests** contacts and messages from Wati (bulk backfill + real-time webhooks)
2. **Deduplicates** contacts by normalized phone number
3. **Classifies** each contact into a journey stage (browsing, purchase_intent, order_support, …) using a configurable LLM prompt
4. **Surfaces** results in a Streamlit dashboard with journey analytics, segment export, and per-tenant classifier configuration


## Architecture

The system follows a **Medallion Architecture** with trigger-driven promotion:

```
Wati API / Webhooks
        │
        ▼
bronze layer  ← raw data, never deleted
        │  (DB trigger)
        ▼
silver layer  ← deduplicated contacts + messages
        │  (classify_worker.py)
        ▼
silver.journey_intent_results
        │  (Postgres views)
        ▼
gold layer    ← pre-aggregated analytics
        │
        ▼
Streamlit dashboard
```

**Schemas**

| Schema | Purpose |
|--------|---------|
| `public` | Tenants, import jobs, classifier configs |
| `bronze` | Raw contacts and messages from Wati |
| `silver` | Normalized contacts, messages, classification results |
| `audit` | Contact merge history |
| `gold` | Pre-computed analytics views |


## Tech stack

- **Python 3.11** — batch scripts and Streamlit app
- **Supabase (PostgreSQL)** — database, RLS, Edge Functions
- **Streamlit** — dashboard UI
- **DeepSeek / OpenAI / Gemini / Anthropic** — Provides compatibility with these LLM providers for classification
- **Deno** — Edge Function runtime for the Wati webhook handler

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd dialo-cx

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

- Go to your supabase project dashboard
- Copy your project URL and service_role key
- The service_role key is in the `Settings` → `API` section

Copy `.env.example` to `.env` and fill in the values:

```env
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# AI provider (at least one required)
DEEPSEEK_API_KEY=sk-...
OPENAI_API_KEY=sk-...          # optional
ANTHROPIC_API_KEY=sk-ant-...   # optional
GEMINI_API_KEY=...             # optional

# Default classification settings
PRODUCTION_PROVIDER=deepseek
PRODUCTION_MODEL=deepseek-chat
PRODUCTION_BATCH_SIZE=20

# Streamlit auth
ADMIN_USERNAME=admin
ADMIN_PASSWORD_HASH=$2b$12$...  # see below
```

### 3. Apply database schema

Run the schema files in order via the Supabase dashboard or MCP:

```
database/01_tenants.sql
database/02_bronze_layer.sql
database/03_silver_layer.sql
database/04_rls_policies.sql
database/05_functions.sql
database/06_webhook_logging.sql
database/07_gold_layer.sql
database/08_grants.sql
```
The grants.sql file is mainly for self-hosted Supabase installations because self-hosted instances do not grant automatic access the API.

### 4. Seed classifier configs

Run this **once** after the schema is applied to populate v1 classifier prompts for all active tenants:

```bash
python scripts/seed_classifier_configs.py
```


## Running the dashboard

```bash
streamlit run app/Home.py
```

Opens at `http://localhost:8501`.


## Scripts

### Import contacts

Fetches all contacts from the Wati API for a tenant and writes them to `silver.contacts`.

```bash
python scripts/batch_contact_imports.py --tenant-id YOUR_TENANT_ID
```

### Messages batch import

Fetches full message history per contact. Resumable — safe to re-run, skips already-synced contacts.

```bash
python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID
python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --limit 100
python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --dry-run
python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --no-resume   # re-fetch from scratch
python scripts/batch_messages_import.py --tenant-id YOUR_TENANT_ID --from-file phones.txt
```

### Classify contacts

Classifies all unclassified (or stale) contacts for a tenant and writes results to `silver.journey_intent_results`.

```bash
python -m scripts.classify_worker --tenant YOUR_TENANT_ID
python -m scripts.classify_worker --tenant all
python -m scripts.classify_worker --tenant YOUR_TENANT_ID --provider openai --model gpt-4o-mini
python -m scripts.classify_worker --tenant YOUR_TENANT_ID --batch-size 50
```

A contact is re-classified when:
- It has never been classified
- A new inbound message arrived after the last classification
- The active classifier config version is newer than the version used for the last classification


## Dashboard pages

### Home

- Run and monitor message backfill jobs (background subprocess, resumable)
- Re-import contacts
- View import progress and logs

### Journey Analytics (`/1_Journey_Analytics`)

- Journey stage distribution across all contacts
- Active contacts by time window (7 / 30 / 90 days)
- Engagement tier breakdown
- Export contact segments as CSV for Wati campaigns

### Settings (`/2_Settings`)

- Edit Wati API credentials
- Manage classifier configuration: edit master prompt and journey stage descriptions, test against live contacts (without writing to DB), activate a new version
- View classifier version history and restore previous versions
- Reclassify stale contacts (those classified with an older config version)

## Classifier configuration

Each tenant has a versioned classifier config stored in `public.tenant_classifier_configs`. A config consists of:

- **Master prompt** — the system instructions sent to the LLM
- **Journey stages** — ordered list of stages with descriptions, stored in `public.tenant_journey_stages`

The orchestrator composes the final prompt as:

```
{master_prompt}

— (separator) —

{master_prompt}        ← repeated for non-reasoning models

VALID STAGES:
• stage_name: stage_description
…

Valid labels: stage_name, …
```

To iterate on the classifier without affecting production:

1. Open Settings → Classifier Configuration
2. Create a draft from the active version
3. Edit the prompt and stages
4. Test with 5 or 20 contacts (read-only, no DB writes)
5. Activate when satisfied — atomic swap via `activate_classifier_config()` RPC

## Multi-tenancy

All tenant-scoped tables use Postgres Row-Level Security (RLS) keyed on `app.tenant_id`. The Supabase client sets this context automatically on every connection. No data from one tenant is ever visible to another.

## Webhook

The Wati webhook handler is a Supabase Edge Function at `supabase/functions/wati-webhook/`.

### Deploy

```bash
supabase login
supabase link --project-ref <project-ref>
supabase functions deploy wati-webhook
```

### Configure Wati

1. Go to your Wati dashboard → Settings → Webhooks
2. Set the webhook URL:
   ```
   https://<project-ref>.supabase.co/functions/v1/wati-webhook/<tenant-id>
   ```
3. Select the events to receive and save

### Test locally

```bash
supabase start
supabase functions serve wati-webhook

# In another terminal
cd supabase/functions/wati-webhook
./test.sh <tenant-id>
```

## Troubleshooting

**Edge Function won't deploy**
- Ensure you're logged in: `supabase login`
- Check the project is linked: `supabase link --project-ref <project-ref>`
- Verify you have permissions on the Supabase project

**Webhook received but not processed**
- Check the `error` column in `public.webhook_logs`
- Verify triggers are enabled in the database
- Check `public.webhook_processing_log` for details

**Can't connect to the database**
- Verify `SUPABASE_URL` and `SUPABASE_KEY` in `.env`
- Ensure the Supabase project is not paused

## Tests

```bash
pytest tests/unit/
pytest tests/
```

## Docs

| Doc | Purpose |
|-----|---------|
| `Home.py` | Streamlit page entry point and batch import functionality |
| `auth.py` | Authentication and authorization logic |
| `database.py` | Database connection and utility database functions |
| `1_Journey_Analytics.py` | Journey analytics page and campaign imports for Wati |
| `2_Settings.py` | Settings page and classifier configuration |
| `database/` | Database schema and table files, and migration files |
| `AGENTS.md` | Agent workflow and coding standards |
| `scripts/BATCH_IMPORT_README.md` | Detailed batch import documentation |
| `scripts/wati_client.py` | API client to establish connection to Wati API |
| `scripts/batch_contact_imports.py` | Script to import contacts from Wati to Supabase |
| `scripts/batch_messages_import.py` | Script to import messages from Wati to Supabase |
| `scripts/supabase_client.py` | Supabase API client for performing database operations |
| `scripts/classify_worker.py` | Background worker for classifying converstaions |
| `scripts/classifiers` | Classes, methods and types for the LLM classifier |