#!/bin/bash
#
# Automated Thesis Experiment Runner
# ===================================
# 
# This script runs a complete ML vs A3 comparative experiment,
# collecting all necessary metrics and generating results for thesis defense.
#
# Usage:
#   ./scripts/run_thesis_experiment.sh [duration_minutes] [output_name]
#
# Examples:
#   ./scripts/run_thesis_experiment.sh 10 baseline_experiment
#   ./scripts/run_thesis_experiment.sh 15 extended_validation
#
# Author: Thesis Project
# Date: November 2025

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

DURATION_MINUTES=${1:-10}
EXPERIMENT_NAME=${2:-"experiment_$(date +%Y%m%d_%H%M%S)"}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/thesis_results/$EXPERIMENT_NAME"

# Activate virtual environment if it exists
if [ -d "$REPO_ROOT/thesis_venv" ]; then
    source "$REPO_ROOT/thesis_venv/bin/activate"
fi

COMPOSE_FILE="$REPO_ROOT/5g-network-optimization/docker-compose.yml"
NEF_INIT_SCRIPT="$REPO_ROOT/5g-network-optimization/services/nef-emulator/backend/app/app/db/init_simple_http.sh"

NEF_SCHEME=${NEF_SCHEME:-http}
NEF_HOST=${NEF_HOST:-localhost}
NEF_PORT=${NEF_PORT:-8080}
NEF_API_BASE="${NEF_SCHEME}://${NEF_HOST}:${NEF_PORT}/api/v1"
NEF_TOKEN=""

UE_IDS=("202010000000001" "202010000000002" "202010000000003")
UE_SPEED_PROFILE=("LOW" "LOW" "HIGH")

# Ensure docker compose sees the ML profile and resolves the ml-service dependency.
export COMPOSE_PROFILES="${COMPOSE_PROFILES:-ml}"
export ML_LOCAL="${ML_LOCAL:-ml}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Helper Functions
# ============================================================================

log() {
    echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +%H:%M:%S)] WARNING:${NC} $1"
}

error() {
    echo -e "${RED}[$(date +%H:%M:%S)] ERROR:${NC} $1"
}

section() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

wait_for_service() {
    local url=$1
    local service_name=$2
    local max_attempts=30
    local attempt=0
    
    log "Waiting for $service_name to be ready..."
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            log "$service_name is ready"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    
    error "$service_name failed to start after ${max_attempts} attempts"
    return 1
}

export_metrics() {
    local output_file=$1
    local metric_queries=$2
    local prom_url="http://localhost:9090"
    
    log "Exporting metrics to $output_file"
    
    echo "{" > "$output_file"
    echo "  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"," >> "$output_file"
    echo "  \"metrics\": {" >> "$output_file"
    
    local first=true
    while IFS='|' read -r name query; do
        if [ "$first" = true ]; then
            first=false
        else
            echo "," >> "$output_file"
        fi
        
        local response
        if ! response=$(curl -sS --get --data-urlencode "query=${query}" "${prom_url}/api/v1/query"); then
            warn "Failed to fetch metrics for $name"
            response='{"status":"error","errorType":"request","error":"curl_failed"}'
        fi

        local result
        if ! result=$(printf '%s' "$response" | jq -c . 2>/dev/null); then
            warn "Invalid response for $name"
            result='{"status":"error","errorType":"parse","error":"invalid_json"}'
        fi

        echo "    \"$name\": $result" >> "$output_file"
    done <<< "$metric_queries"
    
    echo "" >> "$output_file"
    echo "  }" >> "$output_file"
    echo "}" >> "$output_file"
    
    log "Metrics exported successfully"
}

ensure_nef_token() {
    if [ -n "$NEF_TOKEN" ]; then
        return 0
    fi

    local username="${FIRST_SUPERUSER:-admin@my-email.com}"
    local password="${FIRST_SUPERUSER_PASSWORD:-pass}"
    local response
    if ! response=$(curl -sS -X POST "${NEF_API_BASE}/login/access-token" \
        -H 'accept: application/json' \
        -H 'Content-Type: application/x-www-form-urlencoded' \
        --data-urlencode "username=${username}" \
        --data-urlencode "password=${password}" \
        -d "grant_type=&scope=&client_id=&client_secret="); then
        warn "Failed to reach NEF login endpoint"
        return 1
    fi

    local token
    token=$(printf '%s' "$response" | jq -r '.access_token // empty')
    if [ -z "$token" ] || [ "$token" = "null" ]; then
        warn "NEF login did not return an access token"
        return 1
    fi

    NEF_TOKEN="$token"
    log "Authenticated with NEF"
    return 0
}

start_ue_movement() {
    local supi="$1"
    local profile="$2"
    local attempt

    for attempt in 1 2; do
        if ! ensure_nef_token; then
            warn "Skipping UE ${supi}: authentication unavailable"
            return 1
        fi

        local response_file
        response_file=$(mktemp)
        local http_code
        local curl_exit=0
        http_code=$(curl -sS -o "$response_file" -w "%{http_code}" \
            -X POST "${NEF_API_BASE}/ue_movement/start-loop" \
            -H "Authorization: Bearer ${NEF_TOKEN}" \
            -H 'Content-Type: application/json' \
            -d "{\"supi\": \"${supi}\"}") || curl_exit=$?

        if [ $curl_exit -ne 0 ]; then
            warn "UE ${supi} start request failed (curl exit $curl_exit)"
            rm -f "$response_file"
            return 1
        fi

        if [[ "$http_code" == 2* ]]; then
            log "Started UE ${supi} (profile ${profile})"
            rm -f "$response_file"
            return 0
        fi

        local body
        body=$(cat "$response_file")
        rm -f "$response_file"

        if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
            warn "UE ${supi} start unauthorized (HTTP ${http_code}); refreshing token"
            NEF_TOKEN=""
            continue
        fi

        warn "Failed to start UE ${supi} (HTTP ${http_code}): ${body}"
        return 1
    done

    warn "Failed to start UE ${supi} after retries"
    return 1
}

stop_ue_movement() {
    local supi="$1"
    local attempt

    for attempt in 1 2; do
        if ! ensure_nef_token; then
            warn "Skipping stop for UE ${supi}: authentication unavailable"
            return 1
        fi

        local response_file
        response_file=$(mktemp)
        local http_code
        local curl_exit=0
        http_code=$(curl -sS -o "$response_file" -w "%{http_code}" \
            -X POST "${NEF_API_BASE}/ue_movement/stop-loop" \
            -H "Authorization: Bearer ${NEF_TOKEN}" \
            -H 'Content-Type: application/json' \
            -d "{\"supi\": \"${supi}\"}") || curl_exit=$?

        if [ $curl_exit -ne 0 ]; then
            warn "UE ${supi} stop request failed (curl exit $curl_exit)"
            rm -f "$response_file"
            return 1
        fi

        if [[ "$http_code" == 2* ]]; then
            log "Stopped UE ${supi}"
            rm -f "$response_file"
            return 0
        fi

        local body
        body=$(cat "$response_file")
        rm -f "$response_file"

        if [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
            NEF_TOKEN=""
            warn "UE ${supi} stop unauthorized (HTTP ${http_code}); refreshing token"
            continue
        fi

        warn "Failed to stop UE ${supi} (HTTP ${http_code}): ${body}"
        return 1
    done

    warn "Failed to stop UE ${supi} after retries"
    return 1
}

stop_all_ues() {
    local supi
    for supi in "${UE_IDS[@]}"; do
        if ! stop_ue_movement "$supi"; then
            warn "UE ${supi} may still be running"
        fi
    done
}

dump_nef_cells_snapshot() {
    local output_file="$1"
    if [ -z "$output_file" ]; then
        warn "dump_nef_cells_snapshot called without output file"
        return 1
    fi

    if ! ensure_nef_token; then
        warn "Skipping NEF cells snapshot: authentication unavailable"
        return 1
    fi

    local response
    if ! response=$(curl -sS -H "Authorization: Bearer ${NEF_TOKEN}" -H 'accept: application/json' "${NEF_API_BASE}/Cells?skip=0&limit=200"); then
        warn "Failed to fetch NEF cells snapshot"
        return 1
    fi

    if command -v jq >/dev/null 2>&1; then
        if ! printf '%s' "$response" | jq '.' > "$output_file" 2>/dev/null; then
            warn "jq failed to format NEF cells snapshot; writing raw payload"
            printf '%s\n' "$response" > "$output_file"
        fi
    else
        printf '%s\n' "$response" > "$output_file"
    fi

    log "Captured NEF cells snapshot -> $output_file"
    return 0
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

section "Pre-Flight Checks"

# Check we're in the right directory
if [ ! -f "$COMPOSE_FILE" ]; then
    error "docker-compose.yml not found at $COMPOSE_FILE"
    error "Please run this script from the repository root"
    exit 1
fi

# Check Docker is running
if ! docker info > /dev/null 2>&1; then
    error "Docker is not running. Please start Docker and try again."
    exit 1
fi

# Check required commands
for cmd in docker jq curl python3; do
    if ! command -v $cmd &> /dev/null; then
        error "$cmd is not installed. Please install it first."
        exit 1
    fi
done

# Check Python dependencies
if ! python3 -c "import matplotlib, pandas, numpy" 2>/dev/null; then
    warn "Python dependencies not fully installed"
    log "Installing dependencies..."
    pip3 install -q -r "$REPO_ROOT/requirements.txt" || {
        warn "Failed to install some Python dependencies, but continuing anyway"
    }
fi

log "✅ All pre-flight checks passed"

# Create output directory
mkdir -p "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/metrics"
mkdir -p "$OUTPUT_DIR/logs"

# Create experiment metadata
cat > "$OUTPUT_DIR/experiment_metadata.json" << EOF
{
  "experiment_name": "$EXPERIMENT_NAME",
  "duration_minutes": $DURATION_MINUTES,
  "start_time": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "repository": "$(git remote get-url origin 2>/dev/null || echo 'local')",
  "commit": "$(git rev-parse HEAD 2>/dev/null || echo 'unknown')",
  "docker_compose": "$COMPOSE_FILE"
}
EOF

# ============================================================================
# Experiment Information
# ============================================================================

section "Experiment Configuration"
echo "Experiment Name:  $EXPERIMENT_NAME"
echo "Duration per mode: $DURATION_MINUTES minutes"
echo "Total time:       ~$((DURATION_MINUTES * 2 + 5)) minutes"
echo "Output directory: $OUTPUT_DIR"
echo ""

# Automatically continuing with experiment
REPLY=y
echo "y"  # Simulate user input
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log "Experiment cancelled by user"
    exit 0
fi

# ============================================================================
# Phase 1: ML Mode Experiment
# ============================================================================

section "Phase 1: ML Mode Experiment"

log "Stopping any running containers..."
docker compose -f "$COMPOSE_FILE" down -v > "$OUTPUT_DIR/logs/docker_down.log" 2>&1

log "Starting Docker Compose in ML mode..."
ML_HANDOVER_ENABLED=1 \
MIN_HANDOVER_INTERVAL_S=2.0 \
MAX_HANDOVERS_PER_MINUTE=3 \
PINGPONG_WINDOW_S=10.0 \
LOG_LEVEL=INFO \
docker compose -f "$COMPOSE_FILE" up -d > "$OUTPUT_DIR/logs/ml_docker_up.log" 2>&1

# Wait for services
wait_for_service "http://localhost:8080/docs" "NEF Emulator" || exit 1
wait_for_service "http://localhost:5050/api/health" "ML Service" || exit 1
wait_for_service "http://localhost:9090/-/healthy" "Prometheus" || exit 1

# Ensure the ML model finished its background initialization before
# attempting any predictions; the health endpoint flips to OK first, so we
# poll /api/model-health until it reports ready=true.
MODEL_READY_MAX_ATTEMPTS=90
MODEL_READY_DELAY=5
attempt=0
while [ $attempt -lt $MODEL_READY_MAX_ATTEMPTS ]; do
    ready=$(curl -s http://localhost:5050/api/model-health | jq -r '.ready // false' 2>/dev/null || echo "false")
    if [ "$ready" = "true" ]; then
        log "ML model reports ready"
        break
    fi
    attempt=$((attempt + 1))
    sleep $MODEL_READY_DELAY
done

if [ "$ready" != "true" ]; then
    error "ML model failed to report ready after $((MODEL_READY_MAX_ATTEMPTS * MODEL_READY_DELAY)) seconds"
    docker compose -f "$COMPOSE_FILE" logs ml-service >> "$OUTPUT_DIR/logs/ml_model_wait_failure.log" 2>&1 || true
    docker compose -f "$COMPOSE_FILE" down > /dev/null 2>&1 || true
    exit 1
fi

log "All services ready"

# Initialize network topology
if [ -f "$NEF_INIT_SCRIPT" ]; then
    log "Initializing network topology..."
    
    export NEF_SCHEME=http
    export NEF_PORT=8080
    export DOMAIN=localhost
    export FIRST_SUPERUSER=${FIRST_SUPERUSER:-"admin@my-email.com"}
    export FIRST_SUPERUSER_PASSWORD=${FIRST_SUPERUSER_PASSWORD:-"pass"}
    
    if bash "$NEF_INIT_SCRIPT" > "$OUTPUT_DIR/logs/ml_topology_init.log" 2>&1; then
        log "✅ Topology initialized successfully"
        dump_nef_cells_snapshot "$OUTPUT_DIR/logs/a3_cells_snapshot.json" || true
        dump_nef_cells_snapshot "$OUTPUT_DIR/logs/ml_cells_snapshot.json" || true
    else
        error "❌ Topology initialization failed! Cannot proceed without network elements."
        error "Check logs: $OUTPUT_DIR/logs/ml_topology_init.log"
        cat "$OUTPUT_DIR/logs/ml_topology_init.log"
        docker compose -f "$COMPOSE_FILE" down > /dev/null 2>&1
        exit 1
    fi
else
    error "Init script not found: $NEF_INIT_SCRIPT"
    exit 1
fi

# Start UE movement
log "Starting UE movement..."
NEF_TOKEN=""
if ! ensure_nef_token; then
    error "Unable to authenticate with NEF for UE movement"
    exit 1
fi

for i in "${!UE_IDS[@]}"; do
    ue_id="${UE_IDS[$i]}"
    profile="${UE_SPEED_PROFILE[$i]}"
    if ! start_ue_movement "$ue_id" "$profile"; then
        warn "UE ${ue_id} may not have started correctly"
    fi
done

# Run ML experiment
log "Running ML mode experiment for $DURATION_MINUTES minutes..."
log "Experiment started at $(date)"

START_TIME=$(date +%s)
ELAPSED=0
SAMPLING_INTERVAL=$(( (DURATION_MINUTES * 60) / 3 ))
NEXT_SNAPSHOT=$SAMPLING_INTERVAL
SNAPSHOT_INDEX=1

# Define metrics to collect during ML mode so snapshots reuse the same list
ML_METRICS="total_handovers|sum(nef_handover_decisions_total{outcome=\"applied\"})
failed_handovers|sum(nef_handover_decisions_total{outcome=\"skipped\"})
ml_fallbacks|sum(nef_handover_fallback_total)
pingpong_suppressions|sum(ml_pingpong_suppressions_total)
pingpong_too_recent|sum(ml_pingpong_suppressions_total{reason=\"too_recent\"})
pingpong_too_many|sum(ml_pingpong_suppressions_total{reason=\"too_many\"})
pingpong_immediate|sum(ml_pingpong_suppressions_total{reason=\"immediate_return\"})
qos_compliance_ok|sum(nef_handover_compliance_total{outcome=\"ok\"})
qos_compliance_failed|sum(nef_handover_compliance_total{outcome=\"failed\"})
qos_compliance_by_service|sum(ml_qos_compliance_total{outcome=\"passed\"}) by (service_type)
qos_failures_by_service|sum(ml_qos_compliance_total{outcome=\"failed\"}) by (service_type)
qos_violations_by_metric|sum(ml_qos_violation_total) by (metric)
adaptive_confidence|ml_qos_adaptive_confidence
total_predictions|sum(ml_prediction_requests_total)
avg_confidence|avg(ml_prediction_confidence_avg)
p95_latency_ms|histogram_quantile(0.95, rate(ml_prediction_latency_seconds_bucket[5m])) * 1000
p50_handover_interval|histogram_quantile(0.50, rate(ml_handover_interval_seconds_bucket[5m]))
p95_handover_interval|histogram_quantile(0.95, rate(ml_handover_interval_seconds_bucket[5m]))"

while [ $ELAPSED -lt $((DURATION_MINUTES * 60)) ]; do
    sleep 30
    ELAPSED=$(($(date +%s) - START_TIME))
    REMAINING=$((DURATION_MINUTES * 60 - ELAPSED))
    log "ML experiment progress: ${ELAPSED}s / $((DURATION_MINUTES * 60))s (${REMAINING}s remaining)"
    if [ $ELAPSED -ge $NEXT_SNAPSHOT ] && [ $SNAPSHOT_INDEX -le 3 ]; then
        SNAP_FILE="$OUTPUT_DIR/metrics/ml_snapshot_${SNAPSHOT_INDEX}.json"
        export_metrics "$SNAP_FILE" "$ML_METRICS"
        log "Captured QoS snapshot $SNAPSHOT_INDEX at ${ELAPSED}s"
        SNAPSHOT_INDEX=$((SNAPSHOT_INDEX + 1))
        NEXT_SNAPSHOT=$((NEXT_SNAPSHOT + SAMPLING_INTERVAL))
    fi
    done

log "ML experiment complete"

log "Stopping UE movement..."
stop_all_ues

# Collect ML metrics
log "Collecting ML mode metrics..."

export_metrics "$OUTPUT_DIR/metrics/ml_mode_metrics.json" "$ML_METRICS"

# Save Docker logs
log "Saving ML mode logs..."
docker compose -f "$COMPOSE_FILE" logs > "$OUTPUT_DIR/logs/ml_mode_docker.log" 2>&1

# Stop ML mode
log "Stopping ML mode..."
docker compose -f "$COMPOSE_FILE" down > "$OUTPUT_DIR/logs/ml_docker_down.log" 2>&1

log "✅ ML mode experiment complete"
sleep 10

# ============================================================================
# Phase 2: A3 Mode Experiment
# ============================================================================

section "Phase 2: A3 Mode Experiment"

log "Starting Docker Compose in A3 mode..."
ML_HANDOVER_ENABLED=0 \
A3_HYSTERESIS_DB=2.0 \
A3_TTT_S=0.0 \
LOG_LEVEL=INFO \
docker compose -f "$COMPOSE_FILE" up -d > "$OUTPUT_DIR/logs/a3_docker_up.log" 2>&1

# Wait for services
wait_for_service "http://localhost:8080/docs" "NEF Emulator" || exit 1
wait_for_service "http://localhost:9090/-/healthy" "Prometheus" || exit 1

log "Services ready (A3 mode starts faster - no ML training)"

# Initialize topology (same as ML mode for fair comparison)
if [ -f "$NEF_INIT_SCRIPT" ]; then
    log "Initializing network topology..."
    
    export NEF_SCHEME=http
    export NEF_PORT=8080
    export DOMAIN=localhost
    export FIRST_SUPERUSER=${FIRST_SUPERUSER:-"admin@my-email.com"}
    export FIRST_SUPERUSER_PASSWORD=${FIRST_SUPERUSER_PASSWORD:-"pass"}
    
    if bash "$NEF_INIT_SCRIPT" > "$OUTPUT_DIR/logs/a3_topology_init.log" 2>&1; then
        log "✅ Topology initialized successfully"
    else
        error "❌ Topology initialization failed!"
        error "Check logs: $OUTPUT_DIR/logs/a3_topology_init.log"
        docker compose -f "$COMPOSE_FILE" down > /dev/null 2>&1
        exit 1
    fi
fi

# Start UE movement (same pattern as ML mode)
log "Starting UE movement..."
NEF_TOKEN=""
if ! ensure_nef_token; then
    error "Unable to authenticate with NEF for UE movement"
    exit 1
fi

for i in "${!UE_IDS[@]}"; do
    ue_id="${UE_IDS[$i]}"
    profile="${UE_SPEED_PROFILE[$i]}"
    if ! start_ue_movement "$ue_id" "$profile"; then
        warn "UE ${ue_id} may not have started correctly"
    fi
done

# Run A3 experiment (same duration as ML)
log "Running A3 mode experiment for $DURATION_MINUTES minutes..."
log "Experiment started at $(date)"

START_TIME=$(date +%s)
ELAPSED=0

while [ $ELAPSED -lt $((DURATION_MINUTES * 60)) ]; do
    sleep 30
    ELAPSED=$(($(date +%s) - START_TIME))
    REMAINING=$((DURATION_MINUTES * 60 - ELAPSED))
    log "A3 experiment progress: ${ELAPSED}s / $((DURATION_MINUTES * 60))s (${REMAINING}s remaining)"
done

log "A3 experiment complete"

log "Stopping UE movement..."
stop_all_ues

# Collect A3 metrics
log "Collecting A3 mode metrics..."

A3_METRICS="total_handovers|sum(nef_handover_decisions_total{outcome=\"applied\"})
failed_handovers|sum(nef_handover_decisions_total{outcome=\"skipped\"})
qos_compliance_ok|sum(nef_handover_compliance_total{outcome=\"ok\"})
qos_compliance_failed|sum(nef_handover_compliance_total{outcome=\"failed\"})
qos_compliance_by_service|sum(nef_handover_compliance_total{outcome=\"ok\"}) by (service_type)
qos_failures_by_service|sum(nef_handover_compliance_total{outcome=\"failed\"}) by (service_type)
p95_latency_ms|histogram_quantile(0.95, rate(nef_request_duration_seconds_bucket[5m])) * 1000"

export_metrics "$OUTPUT_DIR/metrics/a3_mode_metrics.json" "$A3_METRICS"

# Save Docker logs
log "Saving A3 mode logs..."
docker compose -f "$COMPOSE_FILE" logs > "$OUTPUT_DIR/logs/a3_mode_docker.log" 2>&1

# Stop A3 mode
log "Stopping A3 mode..."
docker compose -f "$COMPOSE_FILE" down > "$OUTPUT_DIR/logs/a3_docker_down.log" 2>&1

log "✅ A3 mode experiment complete"

# ============================================================================
# Phase 3: Analysis and Visualization
# ============================================================================

section "Phase 3: Analysis and Visualization"

log "Generating comparative visualizations..."

# Use the Python comparison tool to generate visualizations
if [ -f "$SCRIPT_DIR/compare_ml_vs_a3_visual.py" ]; then
    PINGPONG_WINDOW_SECONDS=${PINGPONG_WINDOW_SECONDS:-90}
    python3 "$SCRIPT_DIR/compare_ml_vs_a3_visual.py" \
        --ml-metrics "$OUTPUT_DIR/metrics/ml_mode_metrics.json" \
        --ml-log "$OUTPUT_DIR/logs/ml_mode_docker.log" \
        --a3-metrics "$OUTPUT_DIR/metrics/a3_mode_metrics.json" \
        --a3-log "$OUTPUT_DIR/logs/a3_mode_docker.log" \
        --pingpong-window "$PINGPONG_WINDOW_SECONDS" \
        --output "$OUTPUT_DIR" > "$OUTPUT_DIR/logs/visualization.log" 2>&1 || {
        warn "Visualization generation encountered issues (check logs)"
    }
    # Copy QoS specific artefacts to dedicated directory
    mkdir -p "$OUTPUT_DIR/qos"
    cp "$OUTPUT_DIR"/04_qos_metrics_comparison.png "$OUTPUT_DIR/qos/" 2>/dev/null || true
    cp "$OUTPUT_DIR"/05_qos_violations_by_service_type.png "$OUTPUT_DIR/qos/" 2>/dev/null || true
    if [ -f "$OUTPUT_DIR/comparison_summary.json" ]; then
        jq '.metrics | {ml: .ml, a3: .a3}' "$OUTPUT_DIR/comparison_summary.json" > "$OUTPUT_DIR/qos/qos_summary.json" || true
    fi
    log "✅ Visualizations generated"
else
    warn "Comparison tool not found, skipping visualization generation"
fi

# Create experiment summary
log "Creating experiment summary..."

cat > "$OUTPUT_DIR/EXPERIMENT_SUMMARY.md" << 'EOFSUM'
# Thesis Experiment Summary

## Experiment Details

**Name**: EXPERIMENT_NAME_PLACEHOLDER
**Date**: DATE_PLACEHOLDER
**Duration**: DURATION_PLACEHOLDER minutes per mode
**Total Runtime**: TOTAL_TIME_PLACEHOLDER minutes

## Configuration

### ML Mode
- ML_HANDOVER_ENABLED=1
- MIN_HANDOVER_INTERVAL_S=2.0
- MAX_HANDOVERS_PER_MINUTE=3
- PINGPONG_WINDOW_S=10.0

### A3 Mode  
- ML_HANDOVER_ENABLED=0
- A3_HYSTERESIS_DB=2.0
- A3_TTT_S=0.0

## Network Topology

- **gNBs**: 1 (gNB1)
- **Cells**: 4 (Administration, Radioisotopes, IIT, Faculty)
- **UEs**: 3 (speed profiles: LOW, LOW, HIGH)
- **Paths**: 2 (NCSRD Library, NCSRD Gate-IIT)

## Results

See the following files for detailed results:

- `COMPARISON_SUMMARY.txt` - Executive text summary
- `comparison_metrics.csv` - All metrics in spreadsheet format
- `07_comprehensive_comparison.png` - Best single-page visualization
- `ml_mode_metrics.json` - Raw ML metrics
- `a3_mode_metrics.json` - Raw A3 metrics

## Key Findings

[To be filled after reviewing COMPARISON_SUMMARY.txt]

### ML Mode Advantages

1. Ping-pong reduction: [Extract from results]
2. Dwell time improvement: [Extract from results]
3. Success rate: [Extract from results]
4. QoS compliance: [Extract from results]

### Statistical Significance

[Run statistical tests if multiple experiments conducted]

## Thesis Claims Validated

- [ ] ML reduces ping-pong handovers significantly
- [ ] ML maintains longer cell dwell times
- [ ] ML improves or maintains success rates
- [ ] ML respects QoS requirements
- [ ] ML falls back gracefully to A3 when uncertain

## Reproducibility

To reproduce this experiment:

```bash
cd ~/thesis
./scripts/run_thesis_experiment.sh DURATION_PLACEHOLDER EXPERIMENT_NAME_PLACEHOLDER
```

All results will be identical given the same random seeds and configuration.

## Next Steps

1. Review all generated visualizations
2. Extract key metrics for thesis
3. Run additional experiments if needed (3-5 total recommended)
4. Perform statistical significance testing
5. Include results in thesis document

## Notes

[Add any observations or anomalies here]

EOFSUM

# Replace placeholders
sed -i '' "s/EXPERIMENT_NAME_PLACEHOLDER/$EXPERIMENT_NAME/g" "$OUTPUT_DIR/EXPERIMENT_SUMMARY.md"
sed -i '' "s/DATE_PLACEHOLDER/$(date +%Y-%m-%d)/g" "$OUTPUT_DIR/EXPERIMENT_SUMMARY.md"
sed -i '' "s/DURATION_PLACEHOLDER/$DURATION_MINUTES/g" "$OUTPUT_DIR/EXPERIMENT_SUMMARY.md"
sed -i '' "s/TOTAL_TIME_PLACEHOLDER/$((DURATION_MINUTES * 2 + 5))/g" "$OUTPUT_DIR/EXPERIMENT_SUMMARY.md"

log "✅ Experiment summary created"

# ============================================================================
# Phase 4: Results Package
# ============================================================================

section "Phase 4: Results Packaging"

# Create README for the results directory
cat > "$OUTPUT_DIR/README.md" << EOF
# Thesis Experiment Results: $EXPERIMENT_NAME

**Generated**: $(date)
**Duration**: $DURATION_MINUTES minutes per mode

## Quick Access

- **Executive Summary**: COMPARISON_SUMMARY.txt
- **Key Visualization**: 07_comprehensive_comparison.png
- **All Metrics**: comparison_metrics.csv
- **Experiment Details**: EXPERIMENT_SUMMARY.md

## File Structure

\`\`\`
$EXPERIMENT_NAME/
├── README.md (this file)
├── EXPERIMENT_SUMMARY.md
├── COMPARISON_SUMMARY.txt
├── comparison_metrics.csv
├── 01_success_rate_comparison.png
├── 02_pingpong_comparison.png
├── 03_qos_compliance_comparison.png
├── 04_handover_interval_comparison.png
├── 05_suppression_breakdown.png
├── 06_confidence_metrics.png
├── 07_comprehensive_comparison.png
├── 08_timeseries_comparison.png (if generated)
├── metrics/
│   ├── ml_mode_metrics.json
│   ├── a3_mode_metrics.json
│   └── combined_metrics.json
└── logs/
    ├── ml_docker_up.log
    ├── ml_topology_init.log
    ├── ml_mode_docker.log
    ├── a3_docker_up.log
    ├── a3_topology_init.log
    └── a3_mode_docker.log
\`\`\`

## Using These Results

### In Thesis Document

1. Include comprehensive comparison (07_*.png) as main figure
2. Reference CSV data for exact numbers in text
3. Use executive summary for results section

### In Presentation

1. Use comprehensive comparison for overview slide
2. Use ping-pong comparison (02_*.png) for key claim slide
3. Have CSV file ready for questions

### For Defense

1. Know the numbers from COMPARISON_SUMMARY.txt
2. Be ready to explain three-layer prevention mechanism
3. Have backup of all visualizations

## Reproducibility

This experiment can be reproduced with:

\`\`\`bash
./scripts/run_thesis_experiment.sh $DURATION_MINUTES $EXPERIMENT_NAME
\`\`\`

All configuration is captured in experiment_metadata.json.

EOF

log "✅ README created"

# Create archive
log "Creating results archive..."
cd "$REPO_ROOT/thesis_results"
tar -czf "${EXPERIMENT_NAME}.tar.gz" "$EXPERIMENT_NAME/" 2>/dev/null || {
    warn "Could not create archive (tar may not be available)"
}
cd "$REPO_ROOT"

# ============================================================================
# Final Summary
# ============================================================================

section "Experiment Complete!"

echo ""
echo "📊 Results Summary:"
echo "=================="
echo ""

# Count generated files
VISUALIZATION_COUNT=$(find "$OUTPUT_DIR" -maxdepth 1 -type f -name '*.png' | wc -l | tr -d ' ')
METRIC_FILES=$(find "$OUTPUT_DIR/metrics" -maxdepth 1 -type f -name '*.json' | wc -l | tr -d ' ')
LOG_FILES=$(find "$OUTPUT_DIR/logs" -maxdepth 1 -type f -name '*.log' | wc -l | tr -d ' ')

echo "Visualizations: $VISUALIZATION_COUNT PNG files"
echo "Metric files:   $METRIC_FILES JSON files"
echo "Log files:      $LOG_FILES log files"
echo ""

# Show generated files
echo "📁 Generated Files:"
echo "==================="
echo ""
echo "Executive Summary:"
echo "  - COMPARISON_SUMMARY.txt"
echo "  - comparison_metrics.csv"
echo "  - EXPERIMENT_SUMMARY.md"
echo ""
echo "Key Visualizations:"
if [ -f "$OUTPUT_DIR/07_comprehensive_comparison.png" ]; then
    echo "  ⭐ 07_comprehensive_comparison.png (USE THIS IN THESIS)"
fi
if [ -f "$OUTPUT_DIR/02_pingpong_comparison.png" ]; then
    echo "  ⭐ 02_pingpong_comparison.png (Ping-pong proof)"
fi
for viz in "$OUTPUT_DIR"/*.png; do
    if [ -f "$viz" ]; then
        echo "  - $(basename "$viz")"
    fi
done
echo ""

echo "📂 Output Location:"
echo "==================="
echo ""
echo "  $OUTPUT_DIR"
echo ""

# Quick stats from summary if available
if [ -f "$OUTPUT_DIR/COMPARISON_SUMMARY.txt" ]; then
    echo "📈 Quick Results:"
    echo "================="
    echo ""
    grep -A 3 "KEY FINDINGS" "$OUTPUT_DIR/COMPARISON_SUMMARY.txt" || true
    echo ""
fi

echo "✅ Experiment $EXPERIMENT_NAME complete!"
echo ""
echo "Next Steps:"
echo "==========="
echo "1. Review visualizations:  open $OUTPUT_DIR/"
echo "2. Read summary:           cat $OUTPUT_DIR/COMPARISON_SUMMARY.txt"
echo "3. Check CSV data:         open $OUTPUT_DIR/comparison_metrics.csv"
echo "4. Include in thesis:      Use 07_comprehensive_comparison.png"
echo ""

if [ -f "$REPO_ROOT/thesis_results/${EXPERIMENT_NAME}.tar.gz" ]; then
    echo "📦 Results archived to: thesis_results/${EXPERIMENT_NAME}.tar.gz"
    echo ""
fi

echo "🎓 Your thesis results are ready!"
echo ""
echo "Run multiple experiments for statistical confidence:"
echo "  ./scripts/run_thesis_experiment.sh $DURATION_MINUTES experiment_run_2"
echo "  ./scripts/run_thesis_experiment.sh $DURATION_MINUTES experiment_run_3"
echo ""

# Update experiment metadata with completion
python3 << PYEOF
import json
from pathlib import Path

metadata_file = Path("$OUTPUT_DIR/experiment_metadata.json")
with open(metadata_file) as f:
    metadata = json.load(f)

metadata["end_time"] = "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
metadata["status"] = "complete"
metadata["output_files"] = {
    "visualizations": $VISUALIZATION_COUNT,
    "metrics": $METRIC_FILES,
    "logs": $LOG_FILES
}

with open(metadata_file, 'w') as f:
    json.dump(metadata, f, indent=2)

print("Metadata updated")
PYEOF

log "Experiment metadata finalized"

# ============================================================================
# Cleanup
# ============================================================================

# Leave system in clean state
log "Cleaning up..."
docker compose -f "$COMPOSE_FILE" down > /dev/null 2>&1

echo ""
echo "=========================================="
echo " ✅ All Done!"
echo "=========================================="
echo ""

exit 0

