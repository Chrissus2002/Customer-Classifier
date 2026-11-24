# Shared

Neutral home for code and contracts that should not belong to either product's
top-level boundary.

## Intended Use

Use `shared/` for things like:

- Supabase client/runtime helpers used by both products
- shared canonical-contract helpers
- common types and utility functions
- cross-product documentation that is not product-owned

Seeded starting point:

- `shared/runtime/` for non-UI runtime and data-access helpers

## Not For

- Wati-specific connector runtime code
- Journey Builder UX code
- product-specific operational scripts

## Near-Term Goal

Phase A connector work is expected to move the current non-UI shared database
logic out of `app/database.py` into a neutral location like this.
