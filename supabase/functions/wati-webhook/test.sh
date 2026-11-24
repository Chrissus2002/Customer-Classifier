#!/bin/bash
# Test script for wati-webhook Edge Function
# Usage: ./test.sh <tenant-id> [project-ref]

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0

# Check if tenant ID provided
if [ -z "$1" ]; then
    echo -e "${RED}Error: Tenant ID required${NC}"
    echo "Usage: ./test.sh <tenant-id> [project-ref]"
    echo ""
    echo "Examples:"
    echo "  ./test.sh 1              # local Supabase"
    echo "  ./test.sh 1 abcxyz123    # remote project"
    exit 1
fi

TENANT_ID=$1

# Determine if testing local or remote
if [ -z "$2" ]; then
    FUNCTION_URL="http://localhost:54321/functions/v1/wati-webhook/${TENANT_ID}"
    ENV="LOCAL"
else
    PROJECT_REF=$2
    FUNCTION_URL="https://${PROJECT_REF}.supabase.co/functions/v1/wati-webhook/${TENANT_ID}"
    ENV="REMOTE"
fi

echo -e "${YELLOW}Testing Wati Webhook Edge Function${NC}"
echo "Environment: $ENV"
echo "URL: $FUNCTION_URL"
echo ""

# ─── Helper ────────────────────────────────────────────────────────────────

send_request() {
    local payload="$1"
    curl -s -w "\n%{http_code}" -X POST "$FUNCTION_URL" \
      -H "Content-Type: application/json" \
      -d "$payload"
}

assert_status() {
    local test_name="$1"
    local response="$2"
    local expected="$3"

    local http_code body
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)

    if [ "$http_code" -eq "$expected" ]; then
        echo -e "  ${GREEN}✓ $test_name (HTTP $http_code)${NC}"
        PASS=$((PASS + 1))
    else
        echo -e "  ${RED}✗ $test_name — expected HTTP $expected, got $http_code${NC}"
        echo "    Response: $(echo "$body" | jq -c '.' 2>/dev/null || echo "$body")"
        FAIL=$((FAIL + 1))
    fi
}

# ─── Test 1: Inbound message (waId present) ────────────────────────────────

echo -e "${BLUE}[1] Inbound message (waId present)${NC}"

INBOUND_PAYLOAD=$(cat <<EOF
{
  "waId": "5215554146581",
  "name": "Test User",
  "text": "Hello! Inbound test from $(date)",
  "id": "inbound-$(date +%s)",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "type": "text",
  "owner": "false",
  "eventType": "message"
}
EOF
)

assert_status "inbound message accepted" "$(send_request "$INBOUND_PAYLOAD")" 200

echo "  SQL to verify:"
echo "    SELECT direction, text FROM silver.messages ORDER BY created_at DESC LIMIT 1;"
echo ""

# ─── Test 2: Outbound message (no waId) ────────────────────────────────────

echo -e "${BLUE}[2] Outbound message (no waId)${NC}"

OUTBOUND_PAYLOAD=$(cat <<EOF
{
  "name": "Business",
  "text": "Hello! Outbound test from $(date)",
  "id": "outbound-$(date +%s)-1",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "type": "text",
  "owner": "true",
  "eventType": "message"
}
EOF
)

assert_status "outbound message accepted" "$(send_request "$OUTBOUND_PAYLOAD")" 200

echo "  SQL to verify:"
echo "    SELECT direction, text FROM silver.messages ORDER BY created_at DESC LIMIT 1;"
echo "    -- direction should be 'outbound'; delivery receipts with no waId should resolve via existing conversation history"
echo ""

# ─── Test 3: Missing message ID → 400 ──────────────────────────────────────

echo -e "${BLUE}[3] Missing message id — expect 400${NC}"

NO_ID_PAYLOAD=$(cat <<EOF
{
  "waId": "5215554146581",
  "name": "Test User",
  "text": "This payload has no id field",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "type": "text",
  "owner": "false",
  "eventType": "message"
}
EOF
)

assert_status "missing id rejected" "$(send_request "$NO_ID_PAYLOAD")" 400

echo "  SQL to verify nothing was written:"
echo "    SELECT count(*) FROM public.webhook_logs ORDER BY created_at DESC LIMIT 5;"
echo ""

# ─── Summary ───────────────────────────────────────────────────────────────

echo "──────────────────────────────"
TOTAL=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All $TOTAL tests passed${NC}"
else
    echo -e "${RED}$FAIL/$TOTAL tests failed${NC}"
    exit 1
fi
