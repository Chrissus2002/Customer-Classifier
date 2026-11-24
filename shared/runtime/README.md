# Shared Runtime

Neutral home for non-UI runtime and data-access code that both products may
import.

## Intended First Moves

Phase A connector cleanup is expected to start moving code here from:

- `app/database.py`
- script-local Supabase client setup
- any connector/runtime helper that should not live in Streamlit modules

## Guardrails

- no Streamlit caching or UI imports
- no Wati-only business logic here
- no Journey Builder UX code here

If both products need it and it is runtime-oriented, it probably belongs here.
