# dialo-cx

Supabase-backed CX pipeline and analytics repo for Dialo.

## Quick Reference

**Task Tracking:** Use native molds in `.molds/`
**Schema Management:** Schema files in `database/` (numbered 01-07)
**Testing:** `pytest tests/`

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **Update mold state** - Update `.molds/` with progress notes if needed
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update mold state** - Move the active mold to the correct stage and add notes for follow-up work
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

## Supabase MCP Usage

**Investigation (Allowed):**
- `mcp__supabase__list_tables` - Explore schema
- `mcp__supabase__execute_sql` with SELECT queries - Read data

**DDL/DML (Requires User Approval):**
- `mcp__supabase__apply_migration` - Schema changes (CREATE, ALTER, DROP)
- `mcp__supabase__execute_sql` with INSERT/UPDATE/DELETE - Data modifications

## Schema-as-Code: No Migrations

**Core Principle:** Database schema files ALWAYS reflect the current actual state.

**Approach:**
- Schema files in `database/` are the source of truth
- When schema changes, update the schema file directly
- No migration files - schema files are versioned via git
- Fresh database = run all schema files in order

**File Structure:**
- `database/01_tenants.sql` - Tenant schema (always current)
- `database/02_bronze_layer.sql` - Bronze layer + triggers (always current)
- `database/03_silver_layer.sql` - Silver layer (always current)
- `database/04_rls_policies.sql` - RLS policies (always current)
- `database/05_functions.sql` - Processing functions (always current)
- `database/06_webhook_logging.sql` - Observability layer (always current)
- `database/07_gold_layer.sql` - Analytics views (always current)
- `claude_notepad/fix_*.sql` - One-time data fixes (temporary)

**Workflow:**
1. Update schema file to desired state
2. Apply to database: `mcp__supabase__apply_migration` (despite name, it's just executing SQL)
3. Test the change
4. Commit the updated schema file

**Never:** Execute SQL without updating the schema file first
**Never:** Create migration files that drift from source schema

## Test-Driven Development

1. Write test first (fails)
2. Implement feature
3. Run test (passes)
4. Run full test suite to check for regressions

**Run tests frequently:**
```bash
pytest tests/unit/test_specific.py
pytest tests/integration/
```

## Code Standards

- **Production-ready:** No shortcuts, handle edge cases
- **Error handling:** Explicit try/catch, meaningful error messages
- **Type safety:** Use TypeScript for Edge Functions, type hints for Python
- **Security:** Enable RLS on all tenant tables, validate tenant_id
- **Idempotency:** Use UPSERT patterns, safe to retry operations

## Atomic Commits

**Commit after:**
- Each schema change
- Each feature implementation
- Each test addition
- Each bug fix

**Commit messages:**
```bash
git commit -m "add tenants table with RLS policies"
git commit -m "implement contact deduplication with UPSERT"
git commit -m "add test for concurrent webhook race condition"
```

**Push frequently** - Every 3-5 commits maximum.

---

## Molds

This repo uses molds. Durable workflow state lives in `.molds/`.

Use these commands instead of assuming mode from this file:

```bash
molds config get mode
molds status
```

Detailed workflow guidance is loaded globally from `@MOLDS.md`.
