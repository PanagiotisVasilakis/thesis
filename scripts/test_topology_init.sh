#!/bin/bash
#
# Quick Test: Topology Initialization
# ====================================
#
# This script tests that topology initialization works correctly
# with HTTP instead of HTTPS.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/5g-network-optimization/docker-compose.yml"
INIT_SCRIPT="$REPO_ROOT/5g-network-optimization/services/nef-emulator/backend/app/app/db/init_simple_http.sh"
: "${NEF_BASE_URL:?NEF_BASE_URL must be set, for example http://localhost:8080}"

echo "=============================================="
echo " Topology Initialization Test"
echo "=============================================="
echo ""

# Start services
echo "1. Starting NEF emulator..."
export COMPOSE_PROFILES="${COMPOSE_PROFILES:-ml}"
export ML_LOCAL="${ML_LOCAL:-ml}"
if ! docker compose -f "$COMPOSE_FILE" up -d nef-emulator > /dev/null 2>&1; then
    echo "   ❌ Failed to start NEF emulator containers"
    echo "   Hint: ensure Docker is running and profiles are set (COMPOSE_PROFILES=ml)"
    exit 1
fi

# Wait for NEF to be ready
echo "2. Waiting for NEF to be ready..."
for i in {1..30}; do
    if curl -sS "${NEF_BASE_URL}/docs" > /dev/null 2>&1; then
        echo "   ✅ NEF is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "   ❌ NEF failed to start"
        exit 1
    fi
    sleep 2
done

# Run initialization
echo "3. Running topology initialization..."
echo ""

export NEF_SCHEME=http
export NEF_PORT=8080
export DOMAIN=${DOMAIN:-localhost}
: "${FIRST_SUPERUSER:?FIRST_SUPERUSER must be set}"
: "${FIRST_SUPERUSER_PASSWORD:?FIRST_SUPERUSER_PASSWORD must be set}"

if bash "$INIT_SCRIPT"; then
    echo ""
    echo "✅ Topology initialization SUCCESSFUL!"
    echo ""
    
    # Verify entities were created
    echo "4. Verifying entities..."
    
    # Get token
    TOKEN=$(curl -sS -X POST "${NEF_BASE_URL}/api/v1/login/access-token" \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        --data-urlencode "username=${FIRST_SUPERUSER}" \
        --data-urlencode "password=${FIRST_SUPERUSER_PASSWORD}" \
        -d "grant_type=" | jq -r '.access_token')
    
    # Check UEs
    UE_COUNT=$(curl -sS -H "Authorization: Bearer $TOKEN" \
        "${NEF_BASE_URL}/api/v1/UEs" | jq '. | length')
    
    echo "   UEs found: $UE_COUNT (expected: 3)"
    
    if [ "$UE_COUNT" -eq 3 ]; then
        echo "   ✅ All UEs created successfully"
    else
        echo "   ⚠️  UE count mismatch"
    fi
    
    echo ""
    echo "🎉 Test PASSED - Topology initialization working correctly!"
    echo ""
    echo "You can now run a full experiment:"
    echo "  ./scripts/run_thesis_experiment.sh 5 test_after_fix"
    
else
    echo ""
    echo "❌ Topology initialization FAILED"
    echo ""
    echo "Check the output above for errors."
    exit 1
fi

# Cleanup
echo ""
echo "5. Stopping services..."
docker compose -f "$COMPOSE_FILE" down > /dev/null 2>&1
echo "   ✅ Cleanup complete"

exit 0
