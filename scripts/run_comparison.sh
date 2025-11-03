#!/bin/bash
# Quick wrapper for ML vs A3 comparison tool
# Usage: ./scripts/run_comparison.sh [duration_in_minutes]

set -euo pipefail

DURATION=${1:-10}
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_DIR="thesis_results/comparison_${TIMESTAMP}"

echo "=========================================="
echo " ML vs A3 Comparison Experiment"
echo "=========================================="
echo "Duration: $DURATION minutes per mode"
echo "Total time: ~$((DURATION * 2 + 5)) minutes"
echo "Output: $OUTPUT_DIR"
echo "=========================================="
echo ""

# Ensure we're in the right directory
cd "$(dirname "$0")/.."

# Check prerequisites
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker not found. Please install Docker first."
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 not found. Please install Python 3."
    exit 1
fi

# Check Docker Compose file exists
if [ ! -f "5g-network-optimization/docker-compose.yml" ]; then
    echo "❌ Error: docker-compose.yml not found"
    echo "Make sure you're running from the thesis repository root"
    exit 1
fi

# Install Python dependencies if needed
if ! python3 -c "import matplotlib" 2>/dev/null; then
    echo "📦 Installing Python dependencies..."
    pip3 install -r requirements.txt || {
        echo "⚠️  Could not install dependencies. Please run: pip3 install -r requirements.txt"
        exit 1
    }
fi

# Run the comparison tool
echo "🚀 Starting comparative experiment..."
echo ""

python3 scripts/compare_ml_vs_a3_visual.py \
    --duration "$DURATION" \
    --output "$OUTPUT_DIR" \
    --docker-compose "5g-network-optimization/docker-compose.yml"

EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "=========================================="
    echo " ✅ Experiment Complete!"
    echo "=========================================="
    echo "Results: $OUTPUT_DIR"
    echo ""
    echo "Generated files:"
    ls -1 "$OUTPUT_DIR"
    echo ""
    echo "View the text summary:"
    echo "  cat $OUTPUT_DIR/COMPARISON_SUMMARY.txt"
    echo ""
    echo "View visualizations:"
    echo "  open $OUTPUT_DIR/*.png"
    echo ""
    echo "CSV data for analysis:"
    echo "  $OUTPUT_DIR/comparison_metrics.csv"
    echo "=========================================="
else
    echo ""
    echo "❌ Experiment failed with exit code $EXIT_CODE"
    echo "Check logs above for errors"
    exit $EXIT_CODE
fi

