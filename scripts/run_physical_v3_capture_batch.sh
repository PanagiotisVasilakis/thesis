#!/usr/bin/env bash
set -uo pipefail

if [ "$#" -lt 3 ] || [ "$#" -gt 4 ]; then
    echo "Usage: $0 RESULT_ROOT PHASE SEEDS_CSV [MAX_WORKERS]" >&2
    exit 2
fi

RESULT_ROOT="$1"
PHASE="$2"
SEEDS_CSV="$3"
MAX_WORKERS="${4:-3}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
COMPOSE_FILE="$REPO_ROOT/5g-network-optimization/docker-compose.yml"
PROTOCOL_PATH="$REPO_ROOT/configs/thesis_v3_protocol.json"
JOB_FILE="$RESULT_ROOT/batch_logs/${PHASE}_jobs.tsv"

case "$PHASE" in
    training|tuning|final) ;;
    *)
        echo "PHASE must be training, tuning, or final" >&2
        exit 2
        ;;
esac

if ! [[ "$MAX_WORKERS" =~ ^[1-9][0-9]*$ ]]; then
    echo "MAX_WORKERS must be a positive integer" >&2
    exit 2
fi

mkdir -p "$RESULT_ROOT/batch_logs"
: > "$JOB_FILE"

IFS=',' read -r -a SEEDS <<< "$SEEDS_CSV"
SCENARIOS=(highway_sparse_v2 highway_moderate_v2 highway_dense_v2)
job_index=0
for raw_seed in "${SEEDS[@]}"; do
    seed="${raw_seed//[[:space:]]/}"
    if ! [[ "$seed" =~ ^[0-9]+$ ]]; then
        echo "Invalid seed: $raw_seed" >&2
        exit 2
    fi
    for scenario in "${SCENARIOS[@]}"; do
        job_index=$((job_index + 1))
        printf '%s\t%s\t%s\n' "$job_index" "$scenario" "$seed" >> "$JOB_FILE"
    done
done

run_capture_job() {
    local index="$1"
    local scenario="$2"
    local seed="$3"
    local output_dir="$RESULT_ROOT/$PHASE/$scenario/seed$seed"
    local trace="$output_dir/trace.jsonl"
    local validation="$output_dir/physical_validation.json"
    local log="$RESULT_ROOT/batch_logs/${PHASE}_${scenario}_seed${seed}.log"
    local port=$((18080 + index))
    local project="pv3_${PHASE}_${scenario}_${seed}"
    local require_complexity=()

    if [ "$scenario" != "highway_sparse_v2" ]; then
        require_complexity=(--require-complexity)
    fi

    if [ -f "$trace" ]; then
        if "$PYTHON_BIN" -m scripts.policy_comparison.validate_physical_trace \
            "$trace" "${require_complexity[@]}" > "$validation.tmp" 2>> "$log"; then
            mv "$validation.tmp" "$validation"
            echo "[SKIP valid] $phase_label $scenario seed=$seed"
            return 0
        fi
        rm -f "$validation.tmp"
        echo "[FAIL stale-invalid] $output_dir" | tee -a "$log" >&2
        return 1
    fi

    if [ -e "$output_dir" ] && [ -n "$(find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]; then
        echo "[FAIL nonempty-without-trace] $output_dir" | tee -a "$log" >&2
        return 1
    fi

    echo "[START] $phase_label $scenario seed=$seed port=$port"
    if ! COMPOSE_PROJECT_NAME="$project" \
        NEF_HTTP_PORT="$port" \
        NEF_PORT="$port" \
        "$PYTHON_BIN" -m scripts.policy_comparison.capture_scenario_trace \
            --scenario "$scenario" \
            --seed "$seed" \
            --samples 360 \
            --interval-s 1 \
            --protocol-path "$PROTOCOL_PATH" \
            --compose-file "$COMPOSE_FILE" \
            --output-dir "$output_dir" > "$log" 2>&1; then
        echo "[FAIL capture] $phase_label $scenario seed=$seed log=$log" >&2
        return 1
    fi

    if ! "$PYTHON_BIN" -m scripts.policy_comparison.validate_physical_trace \
        "$trace" "${require_complexity[@]}" > "$validation.tmp" 2>> "$log"; then
        mv "$validation.tmp" "$validation"
        echo "[FAIL validation] $phase_label $scenario seed=$seed report=$validation" >&2
        return 1
    fi
    mv "$validation.tmp" "$validation"
    echo "[PASS] $phase_label $scenario seed=$seed"
}

export RESULT_ROOT PHASE REPO_ROOT PYTHON_BIN COMPOSE_FILE PROTOCOL_PATH
export -f run_capture_job
phase_label="$PHASE"
export phase_label

cd "$REPO_ROOT"
xargs -P "$MAX_WORKERS" -n 3 bash -c 'run_capture_job "$1" "$2" "$3"' _ < "$JOB_FILE"
