#!/usr/bin/env bash
# Install dependencies and run tests with coverage
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$SCRIPT_DIR/install_system_deps.sh"
"$SCRIPT_DIR/install_deps.sh"

TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
REPORT_DIR="$REPO_ROOT/CI-CD_reports"
mkdir -p "$REPORT_DIR"

cd "$REPO_ROOT"
pytest --cov | tee "$REPORT_DIR/coverage_${TIMESTAMP}.txt"
