<!-- molds
id: dialo-3
stage: closed
resume_stage: 
parent: 
deps: 
priority: P2
created_at: 2026-04-15T07:55:34Z
updated_at: 2026-04-15T08:50:56Z
closed_at: 2026-04-15T08:50:56Z
defer_until: 
code_branch: 
-->


# Drift scan button — compare Wati vs DB contact counts

## TL;DR

Add a "Scan for drift" button to Admin > Operations that makes one lightweight Wati API call (`/getContacts?pageSize=1`), reads `link.total`, compares with `silver.contacts` count, and displays the delta.

## Problem

No way to know if the DB is behind Wati without SSHing in. As of today: Wati has 9,442 contacts, silver has 8,884 — 558 contacts of drift with zero visibility in the UI.

## Solution

1. Add `get_contact_count()` to `wati_client.py` — single API call with `pageSize=1`, returns `link.total`
2. Add scan button + delta display to Admin > Operations tab
3. Show: `Wati: 9,442 | DB: 8,884 | Delta: +558 new contacts`
4. If delta > 0, show actionable message: "Run contact import to sync"

## Files to Modify
| File | Action | Purpose |
|------|--------|---------|
| `scripts/wati_client.py` | edit | Add `get_contact_count()` method |
| `app/pages/2_Admin.py` | edit | Add scan button + delta display to Operations tab |

## Verification

1. Click "Scan for drift" — shows Wati count, DB count, delta in < 3 seconds
2. Delta >= 0 (Wati always has >= imported)
3. After contact import, delta shrinks to 0

## Implementation Notes

- `/getContacts?pageSize=1` returns `{"link": {"total": 9442}}` — one request, one number
- No message-level drift — that requires per-contact calls (expensive), deferred to dialo-4
- Scan result is ephemeral (not stored). dialo-4 adds persistent tracking
