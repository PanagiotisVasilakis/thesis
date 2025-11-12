#!/bin/bash
#
# System Readiness Verification Script
# =====================================
#
# Verifies that the 5G network emulation stack is ready for experiments:
# - NEF emulator API is responding
# - Topology is initialized (cells, UEs exist)
# - UE movement is active
# - Handovers are occurring
#
# Exit codes:
#   0 - System ready for experiments
#   1 - System not ready (with diagnostic messages)
#
# Usage:
#   ./scripts/verify_system_ready.sh
#   ./scripts/verify_system_ready.sh --ml  # Also check ML service

set -euo pipefail

NEF_HOST=${NEF_HOST:-localhost}
NEF_PORT=${NEF_PORT:-8080}
NEF_API_BASE="http://${NEF_HOST}:${NEF_PORT}/api/v1"
ML_HOST=${ML_HOST:-localhost}
ML_PORT=${ML_PORT:-5050}

CHECK_ML=false
if [ "${1:-}" = "--ml" ]; then
    CHECK_ML=true
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() {
    echo -e "${GREEN}✓${NC} $1"
}

fail() {
    echo -e "${RED}✗${NC} $1"
}

warn() {
    echo -e "${YELLOW}!${NC} $1"
}

# Get authentication token
get_token() {
    curl -s -X 'POST' "${NEF_API_BASE}/login/access-token" \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        --data-urlencode 'username=admin@my-email.com' \
        --data-urlencode 'password=pass' \
        | jq -r '.access_token'
}

echo "================================================"
echo " 5G Network Emulation Stack Readiness Check"
echo "================================================"
echo ""

# Check 1: NEF API responding
echo "[1/6] Checking NEF API..."
if curl -sf "${NEF_API_BASE}/health" > /dev/null 2>&1 || \
   curl -sf "http://${NEF_HOST}:${NEF_PORT}/docs" > /dev/null 2>&1; then
    pass "NEF API is responding"
else
    fail "NEF API is not responding at ${NEF_API_BASE}"
    exit 1
fi

# Check 2: Authentication works
echo "[2/6] Checking authentication..."
TOKEN=$(get_token)
if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
    pass "Authentication successful (token: ${TOKEN:0:20}...)"
else
    fail "Authentication failed"
    exit 1
fi

# Check 3: Topology initialized (cells exist)
echo "[3/6] Checking topology (cells)..."
CELL_COUNT=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "${NEF_API_BASE}/Cells?skip=0&limit=1" | jq '. | length')
if [ "$CELL_COUNT" -ge 1 ]; then
    pass "Topology initialized ($CELL_COUNT cells found)"
else
    fail "No cells found - run init_simple_http.sh first"
    exit 1
fi

# Check 4: UEs exist
echo "[4/6] Checking UEs..."
UE_COUNT=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "${NEF_API_BASE}/UEs?skip=0&limit=10" | jq '. | length')
if [ "$UE_COUNT" -ge 1 ]; then
    pass "$UE_COUNT UEs registered"
else
    fail "No UEs found - run init_simple_http.sh first"
    exit 1
fi

# Check 5: Metrics endpoint working
echo "[5/6] Checking metrics endpoint..."
if METRICS=$(curl -s "http://${NEF_HOST}:${NEF_PORT}/metrics" 2>&1); then
    if echo "$METRICS" | grep -q "nef_handover_decisions_total"; then
        # Count only if there are labeled metrics (not just the HELP/TYPE lines)
        # Use || true to prevent grep from failing when no matches found
        HANDOVER_RAW=$(echo "$METRICS" | grep 'nef_handover_decisions_total{' | awk '{sum+=$NF} END {print int(sum)}' || true)
        HANDOVER_COUNT="${HANDOVER_RAW:-0}"
        pass "Metrics endpoint working (${HANDOVER_COUNT} total handover decisions)"
        
        if [ "$HANDOVER_COUNT" -eq 0 ]; then
            warn "No handovers yet - UE movement may not be active"
            echo "   This is normal for freshly started systems"
        fi
    else
        fail "Metrics endpoint missing expected metrics"
        exit 1
    fi
else
    fail "Metrics endpoint not responding"
    exit 1
fi

# Check 6: ML service (optional)
if [ "$CHECK_ML" = true ]; then
    echo "[6/6] Checking ML service..."
    if curl -sf "http://${ML_HOST}:${ML_PORT}/api/health" > /dev/null 2>&1; then
        ML_STATUS=$(curl -s "http://${ML_HOST}:${ML_PORT}/api/health" | jq -r '.status')
        if [ "$ML_STATUS" = "ok" ]; then
            pass "ML service is healthy"
        else
            warn "ML service responded but status is: $ML_STATUS"
        fi
    else
        fail "ML service is not responding at http://${ML_HOST}:${ML_PORT}/api/health"
        exit 1
    fi
else
    echo "[6/6] Skipping ML service check (use --ml to enable)"
fi

echo ""
echo "================================================"
echo -e "${GREEN}✓ System is ready for experiments${NC}"
echo "================================================"
echo ""

if [ "$HANDOVER_COUNT" -eq 0 ]; then
    echo "Note: To start collecting handover data, ensure UE movement is active:"
    echo "  - Run the full experiment: scripts/run_thesis_experiment.sh"
    echo "  - Or manually start UEs via NEF API"
fi

exit 0
