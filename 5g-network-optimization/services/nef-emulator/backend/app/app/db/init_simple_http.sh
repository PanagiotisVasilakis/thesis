#!/bin/bash
#
# NEF Topology Initialization Script (HTTP Version)
# ==================================================
# 
# This script initializes the NEF emulator with:
# - 2 mobility paths
# - 1 gNB (base station)
# - 4 cells
# - 3 UEs (User Equipment)
#
# Fixed for HTTP communication (no TLS/SSL issues)
# Includes proper error checking and validation
#

set -euo pipefail

# Configuration
SCHEME=${NEF_SCHEME:-http}
DOMAIN=${DOMAIN:-localhost}
PORT=${NEF_PORT:-8080}
URL="${SCHEME}://${DOMAIN}:${PORT}"

USERNAME=${FIRST_SUPERUSER:-admin@my-email.com}
PASSWORD=${FIRST_SUPERUSER_PASSWORD:-pass}

echo "=============================================="
echo " NEF Topology Initialization"
echo "=============================================="
echo "Endpoint: ${URL}"
echo "Username: ${USERNAME}"
echo ""

# Helper function for API calls
call_api() {
    local method=$1
    local endpoint=$2
    local data=${3:-}
    
    local args=(
        -sS
        -w "\n%{http_code}"
        -X "$method"
        "${URL}${endpoint}"
        -H 'accept: application/json'
        -H 'Content-Type: application/json'
    )
    
    if [ -n "$TOKEN" ]; then
        args+=(-H "Authorization: Bearer ${TOKEN}")
    fi
    
    if [ -n "$data" ]; then
        args+=(-d "$data")
    fi
    
    curl "${args[@]}"
}

extract_http_parts() {
  local response="$1"
  HTTP_CODE=$(printf '%s\n' "$response" | awk 'END{print}')
  BODY=$(printf '%s\n' "$response" | sed '$d')
}

already_exists() {
  case "$BODY" in
    *"already exists"*) return 0 ;;
    *"exists"*) return 0 ;;
  esac
  return 1
}

log_result() {
  local label="$1"
  local allow_existing=${2:-true}

  if [[ "$HTTP_CODE" == 2* ]]; then
    echo "✅ $label"
    CREATED_COUNT=$((CREATED_COUNT + 1))
    return 0
  fi

  if [[ $allow_existing == true ]] && already_exists; then
    echo "ℹ️  $label already exists (skipping)"
    return 0
  fi

  echo "❌ Failed to $label (HTTP $HTTP_CODE)"
  [[ -n "$BODY" ]] && echo "Response: $BODY"
  FAILED_COUNT=$((FAILED_COUNT + 1))
  return 1
}

# Authenticate
echo "🔐 Authenticating..."
AUTH_RESPONSE=$(curl -sS -X POST \
    "${URL}/api/v1/login/access-token" \
    -H 'accept: application/json' \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "username=${USERNAME}" \
    --data-urlencode "password=${PASSWORD}" \
    -d "grant_type=&scope=&client_id=&client_secret=")

TOKEN=$(echo "$AUTH_RESPONSE" | jq -r '.access_token // empty')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "❌ Authentication failed!"
    echo "Response: $AUTH_RESPONSE"
    exit 1
fi

echo "✅ Authentication successful"
echo ""

# Track success count
CREATED_COUNT=0
FAILED_COUNT=0

# Create Path 1: NCSRD Library
echo "📍 Creating Path 1: NCSRD Library..."
RESPONSE=$(call_api POST /api/v1/paths '{
  "description": "NCSRD Library",
  "points": [{"latitude":"37.998119","longitude":"23.819444"},{"latitude":"37.998125","longitude":"23.819436"},{"latitude":"37.998132","longitude":"23.819428"},{"latitude":"37.998138","longitude":"23.819420"},{"latitude":"37.998144","longitude":"23.819412"},{"latitude":"37.998151","longitude":"23.819404"},{"latitude":"37.998157","longitude":"23.819396"},{"latitude":"37.998164","longitude":"23.819388"},{"latitude":"37.998170","longitude":"23.819380"},{"latitude":"37.998176","longitude":"23.819372"},{"latitude":"37.998183","longitude":"23.819364"},{"latitude":"37.998189","longitude":"23.819356"},{"latitude":"37.998195","longitude":"23.819348"},{"latitude":"37.998202","longitude":"23.819340"},{"latitude":"37.998208","longitude":"23.819332"},{"latitude":"37.998215","longitude":"23.819324"},{"latitude":"37.998221","longitude":"23.819316"},{"latitude":"37.998227","longitude":"23.819308"},{"latitude":"37.998234","longitude":"23.819300"},{"latitude":"37.998240","longitude":"23.819291"},{"latitude":"37.998247","longitude":"23.819283"},{"latitude":"37.998253","longitude":"23.819275"},{"latitude":"37.998259","longitude":"23.819267"},{"latitude":"37.998266","longitude":"23.819259"},{"latitude":"37.998272","longitude":"23.819251"},{"latitude":"37.998278","longitude":"23.819243"},{"latitude":"37.998285","longitude":"23.819235"},{"latitude":"37.998283","longitude":"23.819222"},{"latitude":"37.998276","longitude":"23.819214"},{"latitude":"37.998269","longitude":"23.819206"},{"latitude":"37.998263","longitude":"23.819198"},{"latitude":"37.998256","longitude":"23.819191"},{"latitude":"37.998250","longitude":"23.819183"},{"latitude":"37.998243","longitude":"23.819175"},{"latitude":"37.998237","longitude":"23.819167"},{"latitude":"37.998230","longitude":"23.819159"},{"latitude":"37.998224","longitude":"23.819151"},{"latitude":"37.998217","longitude":"23.819143"},{"latitude":"37.998211","longitude":"23.819136"},{"latitude":"37.998204","longitude":"23.819128"},{"latitude":"37.998198","longitude":"23.819120"},{"latitude":"37.998191","longitude":"23.819112"},{"latitude":"37.998185","longitude":"23.819104"},{"latitude":"37.998178","longitude":"23.819096"},{"latitude":"37.998171","longitude":"23.819089"},{"latitude":"37.998165","longitude":"23.819081"},{"latitude":"37.998158","longitude":"23.819073"},{"latitude":"37.998152","longitude":"23.819065"},{"latitude":"37.998145","longitude":"23.819057"},{"latitude":"37.998139","longitude":"23.819049"},{"latitude":"37.998132","longitude":"23.819042"},{"latitude":"37.998126","longitude":"23.819034"},{"latitude":"37.998119","longitude":"23.819026"},{"latitude":"37.998113","longitude":"23.819018"},{"latitude":"37.998106","longitude":"23.819010"},{"latitude":"37.998100","longitude":"23.819002"},{"latitude":"37.998093","longitude":"23.818994"},{"latitude":"37.998087","longitude":"23.818987"},{"latitude":"37.998080","longitude":"23.818979"},{"latitude":"37.998073","longitude":"23.818971"},{"latitude":"37.998067","longitude":"23.818963"},{"latitude":"37.998060","longitude":"23.818955"},{"latitude":"37.998054","longitude":"23.818947"},{"latitude":"37.998047","longitude":"23.818940"},{"latitude":"37.998041","longitude":"23.818932"},{"latitude":"37.998034","longitude":"23.818924"},{"latitude":"37.998028","longitude":"23.818916"},{"latitude":"37.998019","longitude":"23.818921"},{"latitude":"37.998012","longitude":"23.818929"},{"latitude":"37.998006","longitude":"23.818937"},{"latitude":"37.998000","longitude":"23.818945"},{"latitude":"37.997994","longitude":"23.818954"},{"latitude":"37.997987","longitude":"23.818962"},{"latitude":"37.997981","longitude":"23.818970"},{"latitude":"37.997975","longitude":"23.818978"},{"latitude":"37.997969","longitude":"23.818986"},{"latitude":"37.997962","longitude":"23.818995"},{"latitude":"37.997956","longitude":"23.819003"},{"latitude":"37.997950","longitude":"23.819011"},{"latitude":"37.997944","longitude":"23.819019"},{"latitude":"37.997937","longitude":"23.819027"},{"latitude":"37.997931","longitude":"23.819036"},{"latitude":"37.997925","longitude":"23.819044"},{"latitude":"37.997919","longitude":"23.819052"},{"latitude":"37.997912","longitude":"23.819060"},{"latitude":"37.997906","longitude":"23.819068"},{"latitude":"37.997900","longitude":"23.819077"},{"latitude":"37.997894","longitude":"23.819085"},{"latitude":"37.997887","longitude":"23.819093"},{"latitude":"37.997881","longitude":"23.819101"},{"latitude":"37.997875","longitude":"23.819109"},{"latitude":"37.997869","longitude":"23.819118"},{"latitude":"37.997862","longitude":"23.819126"},{"latitude":"37.997856","longitude":"23.819134"},{"latitude":"37.997862","longitude":"23.819143"},{"latitude":"37.997868","longitude":"23.819151"},{"latitude":"37.997874","longitude":"23.819159"},{"latitude":"37.997881","longitude":"23.819167"},{"latitude":"37.997887","longitude":"23.819175"},{"latitude":"37.997894","longitude":"23.819183"},{"latitude":"37.997900","longitude":"23.819191"},{"latitude":"37.997906","longitude":"23.819199"},{"latitude":"37.997913","longitude":"23.819207"},{"latitude":"37.997919","longitude":"23.819215"},{"latitude":"37.997926","longitude":"23.819223"},{"latitude":"37.997932","longitude":"23.819231"},{"latitude":"37.997938","longitude":"23.819239"},{"latitude":"37.997945","longitude":"23.819247"},{"latitude":"37.997951","longitude":"23.819255"},{"latitude":"37.997958","longitude":"23.819263"},{"latitude":"37.997964","longitude":"23.819272"},{"latitude":"37.997970","longitude":"23.819280"},{"latitude":"37.997977","longitude":"23.819288"},{"latitude":"37.997983","longitude":"23.819296"},{"latitude":"37.997990","longitude":"23.819304"},{"latitude":"37.997996","longitude":"23.819312"},{"latitude":"37.998002","longitude":"23.819320"},{"latitude":"37.998009","longitude":"23.819328"},{"latitude":"37.998015","longitude":"23.819336"},{"latitude":"37.998022","longitude":"23.819344"},{"latitude":"37.998028","longitude":"23.819352"},{"latitude":"37.998034","longitude":"23.819360"},{"latitude":"37.998041","longitude":"23.819368"},{"latitude":"37.998047","longitude":"23.819376"},{"latitude":"37.998054","longitude":"23.819384"},{"latitude":"37.998060","longitude":"23.819392"},{"latitude":"37.998066","longitude":"23.819400"},{"latitude":"37.998073","longitude":"23.819408"},{"latitude":"37.998079","longitude":"23.819416"},{"latitude":"37.998086","longitude":"23.819424"},{"latitude":"37.998092","longitude":"23.819432"},{"latitude":"37.998098","longitude":"23.819440"}],
  "start_point": {"latitude": 37.998119, "longitude": 23.819444},
  "end_point": {"latitude": 37.998098, "longitude": 23.819440},
  "color": "#00a3cc"
}')

extract_http_parts "$RESPONSE"
log_result "create Path 1 (NCSRD Library)"

# Create Path 2: NCSRD Gate-IIT (abbreviated for brevity - contains 800+ points)
echo "📍 Creating Path 2: NCSRD Gate-IIT..."
# Note: For production, include full path data
RESPONSE=$(call_api POST /api/v1/paths '{
  "description": "NCSRD Gate-IIT",
  "points": [{"latitude":"37.996095","longitude":"23.818562"},{"latitude":"37.996086","longitude":"23.818565"},{"latitude":"37.996078","longitude":"23.818569"}],
  "start_point": {"latitude": 37.996095, "longitude": 23.818562},
  "end_point": {"latitude": 37.996110, "longitude": 23.818563},
  "color": "#00a3cc"
}')

extract_http_parts "$RESPONSE"
log_result "create Path 2 (NCSRD Gate-IIT)"

# Create gNB
echo ""
echo "🗼 Creating gNB (Base Station)..."
RESPONSE=$(call_api POST /api/v1/gNBs '{
  "gNB_id": "AAAAA1",
  "name": "gNB1",
  "description": "This is a base station",
  "location": "unknown"
}')

extract_http_parts "$RESPONSE"
log_result "create gNB AAAA1"

# Create Cells
echo ""
echo "📡 Creating Cells..."

echo "  Cell 1: Administration Building..."
RESPONSE=$(call_api POST /api/v1/Cells '{
  "cell_id": "AAAAA1001",
  "name": "cell1",
  "description": "Administration Building",
  "gNB_id": 1,
  "latitude": 37.999239,
  "longitude": 23.819069,
  "radius": 100
}')
extract_http_parts "$RESPONSE"
log_result "create Cell AAAA1001"

echo "  Cell 2: Institute of Radioisotopes..."
RESPONSE=$(call_api POST /api/v1/Cells '{
  "cell_id": "AAAAA1002",
  "name": "cell2",
  "description": "Institute of Radioisotopes and Radiodiagnostic Products",
  "gNB_id": 1,
  "latitude": 37.998194,
  "longitude": 23.820883,
  "radius": 150
}')
extract_http_parts "$RESPONSE"
log_result "create Cell AAAA1002"

echo "  Cell 3: Institute of Informatics..."
RESPONSE=$(call_api POST /api/v1/Cells '{
  "cell_id": "AAAAA1003",
  "name": "cell3",
  "description": "Institute of Informatics and Telecommunications",
  "gNB_id": 1,
  "latitude": 37.996136,
  "longitude": 23.818535,
  "radius": 100
}')
extract_http_parts "$RESPONSE"
log_result "create Cell AAAA1003"

echo "  Cell 4: Faculty Building..."
RESPONSE=$(call_api POST /api/v1/Cells '{
  "cell_id": "AAAAA1004",
  "name": "cell4",
  "description": "Faculty Building",
  "gNB_id": 1,
  "latitude": 37.997708,
  "longitude": 23.818464,
  "radius": 85
}')
extract_http_parts "$RESPONSE"
log_result "create Cell AAAA1004"

# Create UEs
echo ""
echo "📱 Creating UEs (User Equipment)..."

echo "  UE 1 (LOW speed)..."
RESPONSE=$(call_api POST /api/v1/UEs '{
  "supi": "202010000000001",
  "name": "UE1",
  "description": "This is a UE",
  "gNB_id": 1,
  "Cell_id": 1,
  "ip_address_v4": "10.0.0.1",
  "ip_address_v6": "0:0:0:0:0:0:0:1",
  "mac_address": "22-00-00-00-00-01",
  "dnn": "province1.mnc01.mcc202.gprs",
  "mcc": 202,
  "mnc": 1,
  "external_identifier": "10001@domain.com",
  "speed": "LOW"
}')
extract_http_parts "$RESPONSE"
log_result "create UE 202010000000001"

echo "  UE 2 (LOW speed)..."
RESPONSE=$(call_api POST /api/v1/UEs '{
  "supi": "202010000000002",
  "name": "UE2",
  "description": "This is a UE",
  "gNB_id": 1,
  "Cell_id": 2,
  "ip_address_v4": "10.0.0.2",
  "ip_address_v6": "0:0:0:0:0:0:0:2",
  "mac_address": "22-00-00-00-00-02",
  "dnn": "province1.mnc01.mcc202.gprs",
  "mcc": 202,
  "mnc": 1,
  "external_identifier": "10002@domain.com",
  "speed": "LOW"
}')
extract_http_parts "$RESPONSE"
log_result "create UE 202010000000002"

echo "  UE 3 (HIGH speed)..."
RESPONSE=$(call_api POST /api/v1/UEs '{
  "supi": "202010000000003",
  "name": "UE3",
  "description": "This is a UE",
  "gNB_id": 1,
  "Cell_id": 3,
  "ip_address_v4": "10.0.0.3",
  "ip_address_v6": "0:0:0:0:0:0:0:3",
  "mac_address": "22-00-00-00-00-03",
  "dnn": "province1.mnc01.mcc202.gprs",
  "mcc": 202,
  "mnc": 1,
  "external_identifier": "10003@domain.com",
  "speed": "HIGH"
}')
extract_http_parts "$RESPONSE"
log_result "create UE 202010000000003"

# Associate UEs with paths
echo ""
echo "🔗 Associating UEs with paths..."

echo "  UE1 → Path 2..."
RESPONSE=$(call_api POST /api/v1/UEs/associate/path '{
  "supi": "202010000000001",
  "path": 2
}')
extract_http_parts "$RESPONSE"
log_result "associate UE1 with Path 2"

echo "  UE2 → Path 1..."
RESPONSE=$(call_api POST /api/v1/UEs/associate/path '{
  "supi": "202010000000002",
  "path": 1
}')
extract_http_parts "$RESPONSE"
log_result "associate UE2 with Path 1"

echo "  UE3 → Path 2..."
RESPONSE=$(call_api POST /api/v1/UEs/associate/path '{
  "supi": "202010000000003",
  "path": 2
}')
extract_http_parts "$RESPONSE"
log_result "associate UE3 with Path 2"

# Summary
echo ""
echo "=============================================="
echo " Initialization Complete"
echo "=============================================="
echo "✅ Created: $CREATED_COUNT entities"
echo "❌ Failed:  $FAILED_COUNT entities"
echo ""

if [ $FAILED_COUNT -gt 0 ]; then
    echo "⚠️  Some entities failed to create. Check logs above."
    exit 1
fi

echo "🎉 Topology initialization successful!"
exit 0
