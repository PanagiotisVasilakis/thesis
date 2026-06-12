# Διπλωματική Εργασία Βελτιστοποίησης Δικτύου 5G

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()

Αυτό το αποθετήριο περιέχει ένα ερευνητικό σύστημα λήψης αποφάσεων handover βασισμένο σε μηχανική μάθηση για δίκτυα 5G. Πριν χρησιμοποιηθούν αριθμητικά αποτελέσματα σε αναφορά ή παρουσίαση, εκτελέστε νέο πείραμα και ελέγξτε τα παραγόμενα `thesis_results/<run>/`.

## 🎓 Στόχοι Πειραματικής Αξιολόγησης

Η βασική θέση της αξιολόγησης είναι: **η ML δεν αντικαθιστά τον A3 παντού. Η ML βελτιώνει τις αποφάσεις handover όταν υπάρχουν πολλοί βιώσιμοι υποψήφιοι, ενώ ο A3 παραμένει κατάλληλος σε sparse/simple καθεστώτα.** Η πειραματική ροή συγκρίνει fixed/tuned A3, κλασικά baselines, καθαρή ML και `complexity_aware_ml_a3` και μετρά:

- ping-pong handovers
- πλήθος handovers
- dwell time ανά cell
- QoS compliance
- ML confidence, fallback και latency metrics

Τα παλιά ή checked-in αποτελέσματα θεωρούνται ιστορικά μέχρι να παραχθεί νέο run με καθαρά logs, metadata και metrics.

## 🚀 Γρήγορη Εκκίνηση

```bash
# Εγκατάσταση εξαρτήσεων
./scripts/install_system_deps.sh
./scripts/install_deps.sh

# Πριν το πείραμα, ορίστε τα runtime URLs και τα NEF credentials στο shell.
# Το Docker Compose διαβάζει το 5g-network-optimization/.env, αλλά το script
# πειράματος ελέγχει επίσης shell environment variables.
export NEF_SCHEME=http
export NEF_HOST=localhost
export NEF_PORT=8080
export ML_BASE_URL=http://localhost:5050
export PROMETHEUS_URL=http://localhost:9090
export FIRST_SUPERUSER='<set-nef-admin-user>'
export FIRST_SUPERUSER_PASSWORD='<set-nef-admin-password>'

# Εκτέλεση smoke πειράματος σύγκρισης για 10 λεπτά
./scripts/run_thesis_experiment.sh 10 my_experiment

# Εκτέλεση tests
pytest
```

Τα αποτελέσματα παράγονται στο `thesis_results/my_experiment/` με οπτικοποιήσεις, μετρικές και ανάλυση. Τα checked-in αποτελέσματα είναι ιστορικά, όχι thesis-final, εκτός αν περάσουν το τρέχον validation.

## Experiment Scenarios And Readiness

Run the readiness check before every fresh experiment. It validates the env file, Docker Compose config, selected scenario, ML profile, and the planned output path without starting the experiment.

```bash
RUN_NAME="highway_fresh_$(date +%Y%m%d_%H%M%S)"
./scripts/check_experiment_readiness.sh \
  --scenario highway \
  --output "thesis_results/${RUN_NAME}" \
  --policies ml,fixed_a3_baseline
```

The env template is `5g-network-optimization/.env.example`. Copy it to `5g-network-optimization/.env`, replace placeholder credentials/secrets, and keep the real `.env` uncommitted. Required runtime values are `NEF_SCHEME`, `NEF_HOST`, `NEF_PORT`, `ML_BASE_URL`, `PROMETHEUS_URL`, `FIRST_SUPERUSER`, and `FIRST_SUPERUSER_PASSWORD`.

The experiment architecture keeps three service-level concerns separate: the existing NEF emulator/exposure layer in `5g-network-optimization/services/nef-emulator/`, the existing ML implementation in `5g-network-optimization/services/ml-service/`, and the standards-inspired non-ML handover baseline in `5g-network-optimization/services/handover-baseline-service/`. Both ML and A3-style baselines must consume the same NEF topology, mobility, measurements, and metrics; a second NEF would make the comparison less fair.

The consolidated comparison guide is [docs/THESIS_COMPARISON_GUIDE.md](/home/pvs/thesis/docs/THESIS_COMPARISON_GUIDE.md).

The offline comparison foundation lives in `scripts/policy_comparison/`. It converts the existing NEF feature-vector shape from `/api/v1/ml/state/{ue_id}` into a policy-free canonical trace, then replays identical snapshots through ML, fixed A3, tuned A3, strongest-signal, load-aware A3, velocity-adaptive A3, and `complexity_aware_ml_a3` adapters. The A3 adapters delegate to `handover-baseline-service`; they do not duplicate A3 logic. The ML adapter calls the existing ML service endpoint and fails visibly instead of silently falling back to A3.

To prepare a full multi-seed command plan without executing it:

```bash
.venv/bin/python -m scripts.policy_comparison.prepare_comparison_campaign \
  --campaign-name highway_validation_<timestamp> \
  --output-root thesis_results/campaign_highway_<timestamp> \
  --primary-scenario highway \
  --evaluation-seed 42,43,44 \
  --ue-id 202010000002001 \
  --ue-id 202010000002002 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --calibration-seed 41 \
  --tuned-a3-config thesis_results/<calibration_run>/tuned_a3_config.json \
  --duration 10
```

The existing NEF mode API also recognizes live baseline modes: `fixed_a3_baseline`, `tuned_a3_baseline`, and `complexity_aware_ml_a3`. They run inside the existing NEF process as imported policy modules, not as a second NEF or a new HTTP daemon. For Compose runs, the baseline package is mounted at `/opt/handover-baseline-service` and exposed through `HANDOVER_BASELINE_SERVICE_PATH`.

If you select `tuned_a3_baseline` or `complexity_aware_ml_a3` in readiness or live mode, provide a real tuned parameter JSON with `--tuned-a3-config` or `TUNED_A3_CONFIG_PATH`. For thesis comparison, use the artifact produced by `python -m scripts.policy_comparison.calibrate_tuned_a3`; it must contain `selected_parameters`, calibration metadata, and evaluated configuration scores. During live runs, `scripts/run_enhanced_experiment.py` stages the tuned config into the fresh output directory and mounts that staged copy read-only into the existing NEF container. Do not fabricate or reuse tuning results from the evaluation trace.

Offline trace replay can be exercised without running the full thesis experiment:

```bash
.venv/bin/python -m scripts.policy_comparison.prepare_trace_plan \
  --scenario highway \
  --ue-id 202010000002001 \
  --ue-id 202010000002002 \
  --calibration-seed 41 \
  --evaluation-seed 42 \
  --output-root thesis_results/trace_plan_highway_<timestamp> \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3

.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway \
  --seed 41 \
  --output-dir thesis_results/highway_calibration_seed41_<timestamp> \
  --samples 300 \
  --interval-s 1.0

.venv/bin/python -m scripts.policy_comparison.calibrate_tuned_a3 \
  --calibration-trace thesis_results/highway_calibration_seed41_<timestamp>/trace.jsonl \
  --output thesis_results/highway_calibration_seed41_<timestamp>/tuned_a3_config.json

.venv/bin/python -m scripts.policy_comparison.capture_scenario_trace \
  --scenario highway \
  --seed 42 \
  --output-dir thesis_results/highway_evaluation_seed42_<timestamp> \
  --samples 300 \
  --interval-s 1.0

.venv/bin/python -m scripts.policy_comparison.run_offline_replay \
  --trace thesis_results/highway_evaluation_seed42_<timestamp>/trace.jsonl \
  --tuned-a3-config thesis_results/highway_calibration_seed41_<timestamp>/tuned_a3_config.json \
  --output-dir thesis_results/offline_replay_<timestamp> \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --ml-base-url "${ML_BASE_URL}"
```

Capture evaluation traces with `capture_scenario_trace` using disjoint seeds such as `42`, `43`, and `44` before replay. The replay command refuses to tune and evaluate on the same trace, seed, or mismatched topology.

| Scenario | File/runner | Represents | Thesis use |
|---|---|---|---|
| `highway` | `scripts/scenarios/highway_handover.py` via `scripts/run_enhanced_experiment.py` | High-speed vehicle handovers across a linear 5G corridor | Recommended next fresh run for complexity-aware ML+A3 versus A3 baseline evidence |
| `smart_city` | `scripts/scenarios/smart_city_downtown.py` via `scripts/run_enhanced_experiment.py` | Dense urban deployment with mixed UE service classes and mobility profiles | Useful but partial; synthetic topology and simplified mobility/load assumptions should be described clearly |
| legacy simple run | `scripts/run_thesis_experiment.sh` and `init_simple_http.sh` | Small NCSRD-style topology smoke/regression run | Smoke-only; do not present as thesis-valid real-world evidence |
| synthetic request data | `scripts/data_generation/synthetic_generator.py` | Reproducible QoS request fixtures | Support/test data only; not a mobility or RF validation scenario |

After readiness passes, the recommended fresh experiment command is:

```bash
RUN_NAME="highway_fresh_$(date +%Y%m%d_%H%M%S)"
python scripts/run_enhanced_experiment.py \
  --env-file 5g-network-optimization/.env \
  --scenario highway \
  --seed 42 \
  --duration 10 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json \
  --output "thesis_results/${RUN_NAME}"
```

Before starting services, the same runner can write and validate the intended
live policy sequence without running any experiment:

```bash
RUN_NAME="highway_plan_$(date +%Y%m%d_%H%M%S)"
python scripts/run_enhanced_experiment.py \
  --env-file 5g-network-optimization/.env \
  --scenario highway \
  --seed 42 \
  --duration 10 \
  --policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --tuned-a3-config thesis_results/offline_highway_policyfree_20260610_105301/calibration_seed41_retry1/tuned_a3_config.json \
  --output "thesis_results/${RUN_NAME}" \
  --plan-only
```

For `tuned_a3_baseline` and `complexity_aware_ml_a3`, pass `--tuned-a3-config <path-to-real-tuning-json>`.
The runner rejects missing tuned-parameter files; output validation rejects tuned artifacts without evaluated configuration scores.

Use a new `RUN_NAME` for every execution. The experiment runners reject non-empty output directories to prevent stale artifacts from contaminating fresh results.

Live metric collection preserves missing Prometheus series as `null` and records
`policy_metric_warnings` in `experiment_summary.json`; missing series must not be
interpreted as real zero values.

After multiple completed runs exist, generate statistical summaries from the
saved run folders. Offline and live evidence must stay separated:

```bash
.venv/bin/python -m scripts.policy_comparison.summarize_policy_statistics \
  --run thesis_results/highway_seed_41 \
  --run thesis_results/highway_seed_42 \
  --evidence-type live_experiment \
  --reference-policy fixed_a3_baseline \
  --candidate-policy ml \
  --metrics total_handovers,qos_compliance_ok \
  --output-dir thesis_results/statistics_live_<timestamp>
```

The statistics command only reads existing `summary.json` or
`experiment_summary.json` files. It does not run scenarios or generate new
experiment measurements.

Before treating any completed output as evidence, validate the saved artifacts:

```bash
.venv/bin/python -m scripts.policy_comparison.validate_comparison_outputs \
  --path "thesis_results/${RUN_NAME}" \
  --expected-policies ml,fixed_a3_baseline,tuned_a3_baseline,complexity_aware_ml_a3 \
  --report-json "thesis_results/${RUN_NAME}_validation.json"
```

The validator exits non-zero for incomplete outputs, missing decision logs,
missing tuned A3 config references, invalid policy names, partial topology,
empty metrics/logs, missing ML Prometheus series, hidden ML fallback/override metadata, or geographic/model-not-ready behavior in ML evidence.

## Αρχιτεκτονική Συστήματος

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   Σύστημα Βελτιστοποίησης Δικτύου 5G                    │
│                                                                         │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │   NEF Emulator      │◄──────────►│    ML Service                │    │
│  │   (FastAPI :8080)    │  Ανταλλαγή │    (Flask :5050)             │    │
│  │   - Κανόνες 3GPP A3 │  Features  │    - Πρόβλεψη LightGBM      │    │
│  │   - Μοντέλα Κινητ.  │            │    - Αποφάσεις QoS-Aware    │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
│           │                                        │                    │
│           ▼                                        ▼                    │
│  ┌─────────────────────┐            ┌──────────────────────────────┐    │
│  │  Kinisis UI (:3001) │            │  Prometheus (:9090) +        │    │
│  │  React + Leaflet     │            │  Grafana (:3000)             │    │
│  └─────────────────────┘            └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

## Δομή Αποθετηρίου

```
thesis/
├── 5g-network-optimization/
│   ├── services/
│   │   ├── nef-emulator/          # NEF Emulator (FastAPI) — δείτε το README του
│   │   ├── ml-service/            # ML Service (Flask) — δείτε το README του
│   │   └── kinisis_ui/            # React UI — δείτε το README του
│   ├── deployment/kubernetes/     # K8s manifests — δείτε το README του
│   ├── monitoring/                # Prometheus + Grafana — δείτε το README του
│   └── docker-compose.yml         # Ενορχήστρωση πλήρους στοίβας
├── scripts/                       # Scripts πειράματος, ανάλυσης και βοηθητικά
├── tests/                         # Σουίτα tests
├── mlops/                         # Feature store Feast, αγωγός δεδομένων
├── docs/                          # Λεπτομερής τεκμηρίωση (βλ. παρακάτω)
├── requirements.lock              # Κλειδωμένες εξαρτήσεις Python
├── requirements.txt               # Συμβολικός σύνδεσμος → requirements.lock
└── pytest.ini                     # Ρύθμιση tests
```

## Εκτέλεση του Συστήματος

Και οι δύο υπηρεσίες εκτελούνται μέσω `docker compose`. Ορίστε `ML_HANDOVER_ENABLED` για εναλλαγή λειτουργιών.

```bash
# Λειτουργία ML (συνιστάται)
COMPOSE_PROFILES=ml ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# Λειτουργία A3 μόνο (βάση σύγκρισης)
COMPOSE_PROFILES="" ML_HANDOVER_ENABLED=0 docker compose -f 5g-network-optimization/docker-compose.yml up --build

# Λειτουργία Ενός Container (ML εντός NEF)
COMPOSE_PROFILES="" ML_LOCAL=1 ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up --build
```

## Δοκιμές

```bash
# Γρήγορα: δημιουργία venv, εγκατάσταση εξαρτήσεων, εκτέλεση tests
./scripts/setup_tests.sh

# Ή χειροκίνητα
pip install -r requirements.txt
pytest
```

## 📚 Τεκμηρίωση

| Οδηγός | Περιγραφή |
|--------|-----------|
| **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Πλήρης αρχιτεκτονική συστήματος — επίπεδα υπηρεσιών, ροές δεδομένων, αντιστοίχιση O-RAN, αναφορά API |
| **[MANUAL.md](docs/MANUAL.md)** | Οδηγός λειτουργίας — ανάπτυξη, ρύθμιση παραμέτρων, παρακολούθηση, αντιμετώπιση προβλημάτων |
| **[THESIS.md](docs/THESIS.md)** | Τεχνική εμβάθυνση — αλγόριθμοι, μεθοδολογία, αποτελέσματα επικύρωσης, αναπαραγωγιμότητα |

Κάθε υπηρεσία διαθέτει επίσης το δικό της README με ρύθμιση ανά στοιχείο:
- [`nef-emulator/README.md`](5g-network-optimization/services/nef-emulator/README.md)
- [`ml-service/README.md`](5g-network-optimization/services/ml-service/README.md)
- [`kinisis_ui/README.md`](5g-network-optimization/services/kinisis_ui/README.md)
- [`monitoring/README.md`](5g-network-optimization/monitoring/README.md)
- [`kubernetes/README.md`](5g-network-optimization/deployment/kubernetes/README.md)
