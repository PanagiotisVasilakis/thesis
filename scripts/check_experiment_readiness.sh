#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_ENV_FILE="$ROOT_DIR/5g-network-optimization/.env"
COMPOSE_FILE="$ROOT_DIR/5g-network-optimization/docker-compose.yml"
SCENARIO="highway"
OUTPUT_DIR=""
ENV_FILE="$DEFAULT_ENV_FILE"
POLICIES="ml,fixed_a3_baseline"
TUNED_A3_CONFIG=""
FINAL_MODE=0
FAILURES=0
WARNINGS=0

usage() {
    cat <<'EOF'
Usage:
  ./scripts/check_experiment_readiness.sh --scenario highway --output thesis_results/highway_fresh_<timestamp>

Options:
  --scenario NAME       Enhanced scenario to validate: highway or smart_city.
  --output PATH         Fresh output directory planned for the next run.
  --env-file PATH       Env file to load before checks. Default: 5g-network-optimization/.env
  --compose-file PATH   Compose file to validate. Default: 5g-network-optimization/docker-compose.yml
  --policies LIST       Comma-separated policies to validate. Default: ml,fixed_a3_baseline
  --tuned-a3-config PATH
                        Required when LIST includes tuned_a3_baseline or
                        complexity_aware_ml_a3.
  --final               Enforce final-thesis artifact gates. Requires explicit
                        MODEL_PATH, model metadata, scaler, and feature config.
  -h, --help            Show this help.

This preflight does not start the stack and does not run the thesis experiment.
For container runs, set MODEL_PATH to /app/final-models/<artifact>.joblib and
set ML_MODEL_HOST_DIR or MODEL_PATH_HOST so this script can hash the host file.
EOF
}

pass() {
    printf '[PASS] %s\n' "$1"
}

warn() {
    WARNINGS=$((WARNINGS + 1))
    printf '[WARN] %s\n' "$1"
}

fail() {
    FAILURES=$((FAILURES + 1))
    printf '[FAIL] %s\n' "$1"
}

is_placeholder() {
    local value="${1:-}"
    local lower
    lower="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"

    [ -z "$value" ] && return 0
    case "$lower" in
        *change-me*|*changeme*|*"<set-"*|*"<"*">"*|your-*|*example-password*|password|secret|token)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

load_env_file() {
    local file="$1"
    local line key value

    if [ ! -f "$file" ]; then
        warn "Env file not found: $file; using shell environment only."
        return
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
            ''|'#'*) continue ;;
        esac
        [[ "$line" != *=* ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        key="$(printf '%s' "$key" | tr -d '[:space:]')"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
        if [ -z "${!key+x}" ]; then
            export "$key=$value"
        fi
    done < "$file"

    pass "Loaded env values from $file without printing secrets."
}

check_command() {
    local command_name="$1"
    if command -v "$command_name" >/dev/null 2>&1; then
        pass "Command available: $command_name"
    else
        fail "Command missing: $command_name"
    fi
}

check_required_var() {
    local name="$1"
    local value="${!name-}"
    if is_placeholder "$value"; then
        fail "Required env var $name is missing or still a placeholder."
    else
        pass "Required env var $name is set."
    fi
}

apply_local_endpoint_defaults() {
    if [ -z "${NEF_SCHEME-}" ]; then
        export NEF_SCHEME="http"
        warn "NEF_SCHEME was not set; using documented local Compose default: http."
    fi
    if [ -z "${NEF_PORT-}" ]; then
        export NEF_PORT="${NGINX_HTTP:-8080}"
        warn "NEF_PORT was not set; using documented local Compose HTTP port."
    fi
    if [ -z "${ML_BASE_URL-}" ]; then
        export ML_BASE_URL="http://localhost:5050"
        warn "ML_BASE_URL was not set; using documented local ML service port."
    fi
    if [ -z "${PROMETHEUS_URL-}" ]; then
        export PROMETHEUS_URL="http://localhost:9090"
        warn "PROMETHEUS_URL was not set; using documented local Prometheus port."
    fi
}

resolve_relative_host_path() {
    local candidate="${1:-}"

    case "$candidate" in
        /*)
            printf '%s\n' "$candidate"
            ;;
        *)
            printf '%s/%s\n' "$ENV_DIR" "${candidate#./}"
            ;;
    esac
}

resolve_final_artifact_host_path() {
    local container_path="${1:-}"
    local host_override="${2:-}"
    local model_host_dir

    if ! is_placeholder "$host_override"; then
        resolve_relative_host_path "$host_override"
        return 0
    fi

    if is_placeholder "$container_path"; then
        return 1
    fi

    case "$container_path" in
        /app/final-models/*)
            model_host_dir="$(resolve_relative_host_path "${ML_MODEL_HOST_DIR:-./services/ml-service/ml_service/app/models}")"
            printf '%s/%s\n' "$model_host_dir" "${container_path#/app/final-models/}"
            ;;
        /app/ml_service/app/models/*|/app/ml_service/app/config/*)
            printf '%s/5g-network-optimization/services/ml-service/%s\n' "$ROOT_DIR" "${container_path#/app/}"
            ;;
        /*)
            printf '%s\n' "$container_path"
            ;;
        *)
            resolve_relative_host_path "$container_path"
            ;;
    esac
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --scenario)
            SCENARIO="${2:-}"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="${2:-}"
            shift 2
            ;;
        --env-file)
            ENV_FILE="${2:-}"
            shift 2
            ;;
        --compose-file)
            COMPOSE_FILE="${2:-}"
            shift 2
            ;;
        --policies)
            POLICIES="${2:-}"
            shift 2
            ;;
        --tuned-a3-config)
            TUNED_A3_CONFIG="${2:-}"
            shift 2
            ;;
        --final)
            FINAL_MODE=1
            export THESIS_FINAL_RUN=1
            export REQUIRE_PRETRAINED_MODEL=1
            export DISABLE_SYNTHETIC_MODEL_BOOTSTRAP=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Unknown argument: $1"
            usage
            exit 2
            ;;
    esac
done

ENV_DIR="$(cd "$(dirname "$ENV_FILE")" 2>/dev/null && pwd || printf '%s/5g-network-optimization' "$ROOT_DIR")"

printf 'Experiment readiness preflight\n'
printf 'Scenario: %s\n' "$SCENARIO"
printf 'Output: %s\n' "${OUTPUT_DIR:-<missing>}"
printf '\n'

load_env_file "$ENV_FILE"
apply_local_endpoint_defaults

check_command docker

if docker compose version >/dev/null 2>&1; then
    pass "Docker Compose v2 is available."
else
    fail "Docker Compose v2 is unavailable via 'docker compose'."
fi

if docker info >/dev/null 2>&1; then
    pass "Docker daemon is reachable."
else
    fail "Docker daemon is not reachable."
fi

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    PYTHON_BIN=""
fi

if [ -n "$PYTHON_BIN" ]; then
    pass "Python available: $PYTHON_BIN"
else
    fail "No Python interpreter found (.venv/bin/python or python3)."
fi

if [ -f "$COMPOSE_FILE" ]; then
    pass "Compose file exists: $COMPOSE_FILE"
else
    fail "Compose file missing: $COMPOSE_FILE"
fi

check_required_var NEF_SCHEME
check_required_var NEF_HOST
check_required_var NEF_PORT
check_required_var ML_BASE_URL
check_required_var PROMETHEUS_URL
check_required_var FIRST_SUPERUSER
check_required_var FIRST_SUPERUSER_PASSWORD

if is_placeholder "${NEF_USERNAME-}" && ! is_placeholder "${FIRST_SUPERUSER-}"; then
    export NEF_USERNAME="$FIRST_SUPERUSER"
    pass "Effective NEF_USERNAME resolved from FIRST_SUPERUSER."
fi
if is_placeholder "${NEF_PASSWORD-}" && ! is_placeholder "${FIRST_SUPERUSER_PASSWORD-}"; then
    export NEF_PASSWORD="$FIRST_SUPERUSER_PASSWORD"
    pass "Effective NEF_PASSWORD resolved from FIRST_SUPERUSER_PASSWORD."
fi
check_required_var NEF_USERNAME
check_required_var NEF_PASSWORD

if [ "${NEF_USERNAME-}" = "${FIRST_SUPERUSER-}" ] \
    && [ -n "${NEF_PASSWORD-}" ] \
    && [ -n "${FIRST_SUPERUSER_PASSWORD-}" ] \
    && [ "$NEF_PASSWORD" != "$FIRST_SUPERUSER_PASSWORD" ]; then
    fail "NEF_PASSWORD differs from FIRST_SUPERUSER_PASSWORD while NEF_USERNAME equals FIRST_SUPERUSER."
else
    pass "Effective NEF credentials are internally consistent."
fi

case "${NEF_SCHEME-}" in
    http|https) pass "NEF_SCHEME is http or https." ;;
    *) fail "NEF_SCHEME must be http or https." ;;
esac

if [[ "${NEF_PORT-}" =~ ^[0-9]+$ ]]; then
    pass "NEF_PORT is numeric."
else
    fail "NEF_PORT must be numeric."
fi

case "${ML_BASE_URL-}" in
    http://*|https://*) pass "ML_BASE_URL is an HTTP(S) URL." ;;
    *) fail "ML_BASE_URL must start with http:// or https://." ;;
esac

case "${PROMETHEUS_URL-}" in
    http://*|https://*) pass "PROMETHEUS_URL is an HTTP(S) URL." ;;
    *) fail "PROMETHEUS_URL must start with http:// or https://." ;;
esac

if [ -n "${NEF_SCHEME-}" ] && [ -n "${NEF_HOST-}" ] && [ -n "${NEF_PORT-}" ]; then
    export NEF_URL="${NEF_URL:-${NEF_SCHEME}://${NEF_HOST}:${NEF_PORT}}"
fi
export ML_URL="${ML_URL:-${ML_BASE_URL-}}"
export NEF_USERNAME="${NEF_USERNAME:-${FIRST_SUPERUSER-}}"
export NEF_PASSWORD="${NEF_PASSWORD:-${FIRST_SUPERUSER_PASSWORD-}}"

if [ -n "$PYTHON_BIN" ]; then
    if "$PYTHON_BIN" -m py_compile "$ROOT_DIR/scripts/run_enhanced_experiment.py" "$ROOT_DIR/scripts/scenarios/base_scenario.py"; then
        pass "Experiment runner and base scenario compile."
    else
        fail "Experiment runner or base scenario failed Python compilation."
    fi

    if "$PYTHON_BIN" -m py_compile "$ROOT_DIR"/scripts/policy_comparison/*.py; then
        pass "Policy comparison capture/replay modules compile."
    else
        fail "Policy comparison capture/replay modules failed Python compilation."
    fi

    if scenario_info="$("$PYTHON_BIN" - "$SCENARIO" <<'PY' 2>/tmp/thesis_scenario_registry.err
import sys
from scripts.run_enhanced_experiment import SCENARIOS

scenario = sys.argv[1]
if scenario not in SCENARIOS:
    print(f"unknown scenario: {scenario}")
    sys.exit(2)

info = SCENARIOS[scenario]
print(f"{scenario}: {info['description']} ({info['recommended_duration']} min)")
PY
)"; then
        pass "Scenario is registered: $scenario_info"
    else
        fail "Scenario is not registered in scripts/run_enhanced_experiment.py: $SCENARIO"
    fi

    if "$PYTHON_BIN" - "$ROOT_DIR" <<'PY' >/tmp/thesis_baseline_import.out 2>/tmp/thesis_baseline_import.err
import sys
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from scripts.policy_comparison.policy_adapters import (  # noqa: E402
    FixedA3PolicyAdapter,
    ensure_baseline_service_importable,
)

ensure_baseline_service_importable()
adapter = FixedA3PolicyAdapter()
print(adapter.name)
PY
    then
        imported_policy="$(cat /tmp/thesis_baseline_import.out)"
        pass "Baseline comparison package imports cleanly: $imported_policy"
    else
        fail "Baseline comparison package import failed."
    fi
fi

if [ "$FINAL_MODE" -eq 1 ]; then
    MODEL_HOST_PATH=""
    FEATURE_CONFIG_HOST_PATH=""

    if is_placeholder "${MODEL_PATH-}"; then
        fail "--final requires explicit MODEL_PATH for the pretrained thesis model artifact."
    elif ! MODEL_HOST_PATH="$(resolve_final_artifact_host_path "$MODEL_PATH" "${MODEL_PATH_HOST-}")"; then
        fail "Could not resolve MODEL_PATH to a host artifact path: $MODEL_PATH"
    elif [ ! -f "$MODEL_HOST_PATH" ]; then
        fail "MODEL_PATH does not point to an existing host model artifact: $MODEL_PATH -> $MODEL_HOST_PATH"
    else
        pass "Final model artifact exists on host: $MODEL_HOST_PATH"
    fi

    if is_placeholder "${FEATURE_CONFIG_PATH-}"; then
        FEATURE_CONFIG_PATH="$ROOT_DIR/5g-network-optimization/services/ml-service/ml_service/app/config/features.yaml"
        export FEATURE_CONFIG_PATH
        warn "FEATURE_CONFIG_PATH was not set; using repository feature config for validation."
    fi

    if ! FEATURE_CONFIG_HOST_PATH="$(resolve_final_artifact_host_path "$FEATURE_CONFIG_PATH" "${FEATURE_CONFIG_PATH_HOST-}")"; then
        fail "Could not resolve FEATURE_CONFIG_PATH to a host path: ${FEATURE_CONFIG_PATH-<missing>}"
    elif [ ! -f "$FEATURE_CONFIG_HOST_PATH" ]; then
        fail "Feature config does not exist on host: ${FEATURE_CONFIG_PATH-<missing>} -> $FEATURE_CONFIG_HOST_PATH"
    else
        pass "Feature config exists on host: $FEATURE_CONFIG_HOST_PATH"
    fi

    if [ -n "${MODEL_HOST_PATH-}" ]; then
        if [ ! -f "${MODEL_HOST_PATH}.meta.json" ]; then
            fail "Final model metadata is missing: ${MODEL_HOST_PATH}.meta.json"
        elif [ ! -f "${MODEL_HOST_PATH}.scaler" ]; then
            fail "Final model scaler is missing: ${MODEL_HOST_PATH}.scaler"
        elif [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" - "$MODEL_HOST_PATH" "$FEATURE_CONFIG_HOST_PATH" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

model_path = Path(sys.argv[1])
feature_config = Path(sys.argv[2])
meta_path = Path(f"{model_path}.meta.json")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

data = json.loads(meta_path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit("metadata must be a JSON object")
required = {
    "model_type",
    "trained_at",
    "version",
    "training_data_source",
    "scenario_seeds",
    "dataset_size",
    "selected_features",
    "validation_metrics",
    "calibration_state",
    "git_commit",
    "feature_config_sha256",
}
missing = sorted(key for key in required if not data.get(key))
if missing:
    raise SystemExit("metadata missing: " + ", ".join(missing))
feature_hash = sha256(feature_config)
if data["feature_config_sha256"] != feature_hash:
    raise SystemExit("metadata feature_config_sha256 does not match feature config file")
if not isinstance(data["scenario_seeds"], list) or not data["scenario_seeds"]:
    raise SystemExit("scenario_seeds must be a non-empty list")
if not isinstance(data["selected_features"], list) or not data["selected_features"]:
    raise SystemExit("selected_features must be a non-empty list")
if not isinstance(data["validation_metrics"], dict) or not data["validation_metrics"]:
    raise SystemExit("validation_metrics must be a non-empty object")
if int(data["dataset_size"]) <= 0:
    raise SystemExit("dataset_size must be positive")
print(json.dumps({
    "model_sha256": sha256(model_path),
    "metadata_sha256": sha256(meta_path),
    "scaler_sha256": sha256(Path(f"{model_path}.scaler")),
    "feature_config_sha256": sha256(feature_config),
}, sort_keys=True))
PY
        then
            pass "Final model metadata, scaler, and artifact hashes are valid."
        else
            fail "Final model metadata, scaler, or artifact hashes are invalid."
        fi
    fi
fi

if [ -z "$POLICIES" ]; then
    fail "--policies must not be empty."
else
    IFS=',' read -r -a POLICY_LIST <<< "$POLICIES"
    tuned_required=0
    for policy in "${POLICY_LIST[@]}"; do
        policy="$(printf '%s' "$policy" | tr -d '[:space:]')"
        case "$policy" in
            ml|a3|hybrid|fixed_a3_baseline)
                pass "Policy is recognized: $policy"
                ;;
            tuned_a3_baseline)
                pass "Policy is recognized: $policy"
                tuned_required=1
                ;;
            complexity_aware_ml_a3)
                pass "Policy is recognized: $policy"
                tuned_required=1
                ;;
            *)
                fail "Unknown policy selected: $policy"
                ;;
        esac
    done

    if [ "$tuned_required" -eq 1 ]; then
        if [ -z "$TUNED_A3_CONFIG" ] && [ -n "${TUNED_A3_CONFIG_PATH-}" ]; then
            TUNED_A3_CONFIG="$TUNED_A3_CONFIG_PATH"
        fi

        if [ -z "$TUNED_A3_CONFIG" ]; then
            fail "A tuned-A3-backed policy was selected but --tuned-a3-config or TUNED_A3_CONFIG_PATH was not provided."
        elif [ ! -f "$TUNED_A3_CONFIG" ]; then
            fail "Tuned A3 config does not exist: $TUNED_A3_CONFIG"
        elif [ -n "$PYTHON_BIN" ] && "$PYTHON_BIN" - "$TUNED_A3_CONFIG" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit("config must be a JSON object")
params = data.get("selected_parameters") or data.get("parameters")
if not isinstance(params, dict):
    raise SystemExit("config must contain selected_parameters")
required = {"a3_offset_db", "hysteresis_db", "time_to_trigger_s", "cooldown_s"}
missing = sorted(required.difference(params))
if missing:
    raise SystemExit("selected_parameters missing: " + ", ".join(missing))
PY
        then
            pass "Tuned A3 config exists and contains selected A3 parameters."
        else
            fail "Tuned A3 config is invalid or missing selected parameters: $TUNED_A3_CONFIG"
        fi
    fi
fi

case "$SCENARIO" in
    highway)
        pass "Scenario is marked strong enough for the next handover-focused thesis run."
        ;;
    smart_city)
        warn "Scenario smart_city is useful but partial; prefer highway for the next handover-focused run."
        ;;
    *)
        fail "Scenario $SCENARIO is not approved for thesis-readiness preflight."
        ;;
esac

if [ -z "$OUTPUT_DIR" ]; then
    fail "Missing --output. Choose a unique fresh thesis_results/<name> path."
else
    case "$OUTPUT_DIR" in
        /*) OUTPUT_ABS="$OUTPUT_DIR" ;;
        *) OUTPUT_ABS="$ROOT_DIR/$OUTPUT_DIR" ;;
    esac

    if [ -d "$OUTPUT_ABS" ] && [ -n "$(find "$OUTPUT_ABS" -mindepth 1 -print -quit)" ]; then
        fail "Output directory exists and is not empty: $OUTPUT_ABS"
    else
        pass "Output directory is fresh or empty: $OUTPUT_ABS"
    fi
fi

if [ -f "$ROOT_DIR/scripts/run_enhanced_experiment.py" ]; then
    pass "Enhanced experiment runner exists and can be called through Python."
else
    fail "Enhanced experiment runner is missing."
fi

if [ -x "$ROOT_DIR/scripts/run_thesis_experiment.sh" ]; then
    pass "Legacy thesis experiment script is executable."
else
    fail "Legacy thesis experiment script is not executable."
fi

if grep -q 'COMPOSE_PROFILES=ml' "$ROOT_DIR/README.md"; then
    pass "README documents the ML Compose profile."
else
    fail "README does not document the ML Compose profile."
fi

if [ -f "$COMPOSE_FILE" ] && docker compose version >/dev/null 2>&1; then
    COMPOSE_CONFIG="$(mktemp)"
    COMPOSE_ARGS=()
    if [ -f "$ENV_FILE" ]; then
        COMPOSE_ARGS+=(--env-file "$ENV_FILE")
    fi
    COMPOSE_ARGS+=(-f "$COMPOSE_FILE")

    if COMPOSE_PROFILES=ml docker compose "${COMPOSE_ARGS[@]}" config >"$COMPOSE_CONFIG" 2>/tmp/thesis_compose_config.err; then
        pass "Docker Compose config renders with COMPOSE_PROFILES=ml."
        if grep -q '^  ml-service:' "$COMPOSE_CONFIG"; then
            pass "ML service is included when COMPOSE_PROFILES=ml is selected."
        else
            fail "ML service is absent from rendered Compose config with COMPOSE_PROFILES=ml."
        fi
    else
        fail "Docker Compose config failed with COMPOSE_PROFILES=ml."
    fi
    rm -f "$COMPOSE_CONFIG"
fi

printf '\n'
if [ "$FAILURES" -gt 0 ]; then
    printf 'Readiness: NOT READY (%s failure(s), %s warning(s))\n' "$FAILURES" "$WARNINGS"
    exit 1
fi

printf 'Readiness: READY (%s warning(s))\n' "$WARNINGS"
printf 'Next command can use the validated scenario and fresh output path.\n'
