#!/bin/bash
# Quick Win: Run Realistic Stress Test Experiment
# Time: 3-4 hours (60 min ML + 60 min A3 + setup/analysis)
# Impact: Get REAL statistics with ping-pong scenarios

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Configuration
DURATION_MINUTES=60
EXPERIMENT_NAME="stress_test_$(date +%Y%m%d_%H%M%S)"
RESULTS_DIR="$REPO_ROOT/thesis_results/$EXPERIMENT_NAME"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

section() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}========================================${NC}"
}

log() {
    echo -e "${GREEN}[$(date +%H:%M:%S)]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[$(date +%H:%M:%S)] WARNING:${NC} $1"
}

section "REALISTIC STRESS TEST EXPERIMENT"
echo "Duration: $DURATION_MINUTES minutes per mode (2 hours total)"
echo "UEs: 20 (stationary, walking, driving slow, driving fast)"
echo "Goal: Validate ping-pong prevention under realistic stress"
echo "Results: $RESULTS_DIR"
echo ""

# Ensure docker compose is running
section "Step 1: Ensure system is running"
cd 5g-network-optimization

if ! docker compose ps | grep -q "Up"; then
    warn "Starting docker compose services..."
    docker compose --profile ml up -d
    sleep 30
fi

cd "$REPO_ROOT"

# Create results directory
mkdir -p "$RESULTS_DIR"
mkdir -p "$RESULTS_DIR/logs"
mkdir -p "$RESULTS_DIR/metrics"

# Generate UE configuration script for NEF
section "Step 2: Generate realistic UE scenario"

cat > "$RESULTS_DIR/ue_scenario.json" <<'EOF'
{
  "experiment": "stress_test",
  "duration_minutes": 60,
  "ues": [
    {"id": "202010000000001", "speed_mps": 0.1, "pattern": "stationary", "area": "center"},
    {"id": "202010000000002", "speed_mps": 0.1, "pattern": "stationary", "area": "north"},
    {"id": "202010000000003", "speed_mps": 0.1, "pattern": "stationary", "area": "south"},
    {"id": "202010000000004", "speed_mps": 0.1, "pattern": "stationary", "area": "east"},
    {"id": "202010000000005", "speed_mps": 0.1, "pattern": "stationary", "area": "west"},
    
    {"id": "202010000000006", "speed_mps": 1.5, "pattern": "walking", "path": "north_to_south"},
    {"id": "202010000000007", "speed_mps": 2.0, "pattern": "walking", "path": "east_to_west"},
    {"id": "202010000000008", "speed_mps": 1.8, "pattern": "walking", "path": "diagonal_ne_sw"},
    {"id": "202010000000009", "speed_mps": 1.2, "pattern": "walking", "path": "diagonal_nw_se"},
    {"id": "202010000000010", "speed_mps": 1.5, "pattern": "walking", "path": "circular"},
    
    {"id": "202010000000011", "speed_mps": 7.5, "pattern": "driving_slow", "path": "grid_pattern"},
    {"id": "202010000000012", "speed_mps": 8.0, "pattern": "driving_slow", "path": "grid_pattern"},
    {"id": "202010000000013", "speed_mps": 6.5, "pattern": "driving_slow", "path": "grid_pattern"},
    {"id": "202010000000014", "speed_mps": 9.0, "pattern": "driving_slow", "path": "grid_pattern"},
    {"id": "202010000000015", "speed_mps": 7.0, "pattern": "driving_slow", "path": "grid_pattern"},
    
    {"id": "202010000000016", "speed_mps": 20.0, "pattern": "driving_fast", "path": "diagonal_rapid", "note": "PING-PONG TARGET"},
    {"id": "202010000000017", "speed_mps": 18.0, "pattern": "driving_fast", "path": "diagonal_rapid", "note": "PING-PONG TARGET"},
    {"id": "202010000000018", "speed_mps": 22.0, "pattern": "driving_fast", "path": "diagonal_rapid", "note": "PING-PONG TARGET"},
    {"id": "202010000000019", "speed_mps": 25.0, "pattern": "driving_fast", "path": "horizontal_rapid", "note": "PING-PONG TARGET"},
    {"id": "202010000000020", "speed_mps": 15.0, "pattern": "driving_fast", "path": "erratic", "note": "PING-PONG TARGET"}
  ]
}
EOF

log "UE scenario saved to $RESULTS_DIR/ue_scenario.json"

# Run ML mode experiment
section "Step 3: Run ML Mode (60 minutes)"
log "Starting ML mode with handover enabled..."
log "Expected: 20-40 handovers, minimal ping-pong"

cd "$REPO_ROOT"

# Export ML mode environment
export ML_HANDOVER_ENABLED=1
export EXPERIMENT_MODE="ml"

# Run using existing experiment script
./scripts/run_thesis_experiment.sh $DURATION_MINUTES "${EXPERIMENT_NAME}_ml" 2>&1 | tee "$RESULTS_DIR/logs/ml_mode.log"

# Copy ML results
if [ -d "thesis_results/${EXPERIMENT_NAME}_ml" ]; then
    cp -r "thesis_results/${EXPERIMENT_NAME}_ml"/* "$RESULTS_DIR/ml_results/"
    log "ML results saved to $RESULTS_DIR/ml_results/"
fi

# Wait a bit before A3 mode
log "Waiting 60 seconds before A3 mode..."
sleep 60

# Run A3 mode experiment
section "Step 4: Run A3 Baseline Mode (60 minutes)"
log "Starting A3 mode with ML disabled..."
log "Expected: 80-150 handovers, significant ping-pong"

# Export A3 mode environment
export ML_HANDOVER_ENABLED=0
export EXPERIMENT_MODE="a3_baseline"

# Run A3 experiment
./scripts/run_thesis_experiment.sh $DURATION_MINUTES "${EXPERIMENT_NAME}_a3" 2>&1 | tee "$RESULTS_DIR/logs/a3_mode.log"

# Copy A3 results
if [ -d "thesis_results/${EXPERIMENT_NAME}_a3" ]; then
    cp -r "thesis_results/${EXPERIMENT_NAME}_a3"/* "$RESULTS_DIR/a3_results/"
    log "A3 results saved to $RESULTS_DIR/a3_results/"
fi

# Analysis
section "Step 5: Analyze Results"

# Count handovers from logs
ml_handovers=$(grep -c "HANDOVER_APPLIED" "$RESULTS_DIR/logs/ml_mode.log" || echo "0")
a3_handovers=$(grep -c "HANDOVER_APPLIED" "$RESULTS_DIR/logs/a3_mode.log" || echo "0")

# Count ping-pong events (handover to same antenna within 60s)
ml_pingpong=$(grep -c "ping.*pong.*detected" "$RESULTS_DIR/logs/ml_mode.log" || echo "0")
a3_pingpong=$(grep -c "ping.*pong.*detected" "$RESULTS_DIR/logs/a3_mode.log" || echo "0")

# Calculate reduction
if [ "$a3_handovers" -gt 0 ]; then
    reduction=$(awk "BEGIN {printf \"%.1f\", (($a3_handovers - $ml_handovers) / $a3_handovers) * 100}")
else
    reduction="N/A"
fi

# Generate summary report
cat > "$RESULTS_DIR/SUMMARY.md" <<EOF
# Stress Test Experiment Results

**Date**: $(date)
**Duration**: $DURATION_MINUTES minutes per mode
**UEs**: 20 (5 stationary, 5 walking, 5 driving slow, 5 driving fast)

## Results

### ML Mode
- Handovers: **$ml_handovers**
- Ping-pong events: **$ml_pingpong**

### A3 Baseline Mode
- Handovers: **$a3_handovers**
- Ping-pong events: **$a3_pingpong**

### Comparison
- Handover reduction: **${reduction}%**
- Ping-pong reduction: **$(awk "BEGIN {printf \"%.1f\", (($a3_pingpong - $ml_pingpong) / ($a3_pingpong + 1)) * 100}")%**

## Interpretation

EOF

if [ "$ml_handovers" -lt "$a3_handovers" ] && [ "$ml_handovers" -gt 10 ]; then
    echo "✅ **SUCCESS**: ML reduced handovers significantly while maintaining connectivity" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - ML performed $ml_handovers handovers (reasonable for 20 UEs)" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - A3 performed $a3_handovers handovers (excessive ping-pong)" >> "$RESULTS_DIR/SUMMARY.md"
elif [ "$ml_handovers" -eq 0 ]; then
    echo "⚠️  **WARNING**: Zero ML handovers suggests model is too conservative" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - Check if model is working correctly" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - Review UE mobility patterns" >> "$RESULTS_DIR/SUMMARY.md"
elif [ "$ml_handovers" -ge "$a3_handovers" ]; then
    echo "❌ **ISSUE**: ML performed MORE handovers than A3" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - Model may need retraining" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - Check ping-pong prevention logic" >> "$RESULTS_DIR/SUMMARY.md"
else
    echo "📊 **PARTIAL SUCCESS**: Some improvement but limited" >> "$RESULTS_DIR/SUMMARY.md"
    echo "   - ML: $ml_handovers vs A3: $a3_handovers" >> "$RESULTS_DIR/SUMMARY.md"
fi

# Display summary
section "EXPERIMENT COMPLETE"
cat "$RESULTS_DIR/SUMMARY.md"

echo ""
echo "Full results available in: $RESULTS_DIR"
echo ""
echo "Next steps:"
echo "1. Review logs in $RESULTS_DIR/logs/"
echo "2. Check metrics in $RESULTS_DIR/metrics/"
echo "3. Run comparison analysis: ./scripts/compare_ml_vs_a3_visual.py --ml $RESULTS_DIR/ml_results/ --a3 $RESULTS_DIR/a3_results/"
echo ""
