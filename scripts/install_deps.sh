#!/usr/bin/env bash
# Install Python dependencies for local development and CI
set -euo pipefail

usage() {
    echo "Usage: $0 [--skip-if-present]" >&2
    exit 1
}

SKIP_IF_PRESENT=false
for arg in "$@"; do
    case "$arg" in
        --skip-if-present)
            SKIP_IF_PRESENT=true
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $arg" >&2
            usage
            ;;
    esac
done

check_installed() {
    while read -r line; do
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        pkg=$(echo "$line" | cut -d= -f1 | cut -d'[' -f1 | cut -d'>' -f1 | cut -d'<' -f1)
        python -m pip show "$pkg" >/dev/null 2>&1 || return 1
    done < requirements.txt
    python -m pip show ml_service >/dev/null 2>&1 || return 1
    return 0
}

if [ "$SKIP_IF_PRESENT" = true ] && { [ -n "${VIRTUAL_ENV:-}" ] || [ -d .venv ]; }; then
    if check_installed; then
        echo "Dependencies already installed, skipping installation." >&2
        exit 0
    fi
fi

echo "Installing Python dependencies..." >&2
python -m pip install -r requirements.txt
rc=$?
if [ $rc -ne 0 ]; then
    echo "Error: 'pip install -r requirements.txt' failed with exit code $rc" >&2
    exit $rc
fi

echo "Installing ml_service package..." >&2
python -m pip install -e 5g-network-optimization/services/ml-service
rc=$?
if [ $rc -ne 0 ]; then
    echo "Error: 'pip install -e ml_service' failed with exit code $rc" >&2
    exit $rc
fi
