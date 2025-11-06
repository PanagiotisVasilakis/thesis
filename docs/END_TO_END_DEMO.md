# End-to-End Demonstration Playbook

This guide captures the exact sequence for showcasing the thesis system in a live session. It walks through preparing the machine-learning (ML) artifacts, exercising the NEF emulator with multi-antenna mobility, capturing Prometheus evidence for both ML and rule-based (A3) modes, and generating the comparison assets used in the thesis.

> **Audience:** defence demo operators, reviewers, and teammates who need a repeatable, fully instrumented demonstration.

---

## 1. Prerequisites

- Docker Desktop running with at least 6 GB of free memory.
- Local clone of this repository at `~/thesis` (adjust paths if different).
- Python 3.10 virtual environment activated (`source thesis_venv/bin/activate`).
- Dependencies installed (`./scripts/install_system_deps.sh` and `./scripts/install_deps.sh`).
- `COMPOSE_PROFILES=ml` set in `5g-network-optimization/.env` (already committed).
- A trained model staged under `output/` (defaults produced by the integration tests).

```bash
# activate env and export a helper path variable
source ~/thesis/thesis_venv/bin/activate
export THESIS_ROOT=~/thesis
```

---

## 2. Stage ML Artifacts

The ML service expects its LightGBM bundle under `services/ml-service/ml_service/app/models/`. Copy the prepared artifact set before starting containers.

```bash
cd "$THESIS_ROOT"
cp output/test_model.joblib \
   5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_v1.0.0.joblib
cp output/test_model.joblib.meta.json \
   5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_v1.0.0.joblib.meta.json
cp output/test_model.joblib.scaler \
   5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_v1.0.0.joblib.scaler
```

Validate the files if needed:

```bash
ls -lh 5g-network-optimization/services/ml-service/ml_service/app/models/antenna_selector_v1.0.0.joblib*
```

---

## 3. Boot the Stack in ML Mode

Spin up NEF, ML service, Prometheus, and Grafana with ML handovers enabled.

```bash
cd "$THESIS_ROOT/5g-network-optimization"
COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose up -d
COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose ps
```

Health probes (retry until `200 OK`):

```bash
curl -s http://localhost:8080/docs > /dev/null && echo "NEF ready"
curl -s http://localhost:5050/api/health | jq
curl -s http://localhost:9090/-/healthy && echo "Prometheus ready"
```

---

## 4. Initialise Multi-Antenna Topology

The helper script seeds one gNB, four cells, and three UEs. Edit `services/nef-emulator/backend/app/app/db/init_simple_http.sh` if you need more antennas (see [`docs/MULTI_ANTENNA_TESTING.md`](MULTI_ANTENNA_TESTING.md) for patterns).

```bash
cd "$THESIS_ROOT/5g-network-optimization/services/nef-emulator/backend/app/app/db"
bash init_simple_http.sh
```

Expected output includes `associate UE* with Path *` confirmations.

---

## 5. Drive UE Mobility Loops

Authenticate with the NEF emulator and start UE loops for the three sample subscribers. Repeat this step after every container restart.

```bash
cd "$THESIS_ROOT/5g-network-optimization"
NEF_TOKEN=$(curl -sS -X POST http://localhost:8080/api/v1/login/access-token \
  -H "accept: application/json" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=admin@my-email.com" \
  --data-urlencode "password=pass" \
  -d "grant_type=&scope=&client_id=&client_secret=" | jq -r .access_token)

for supi in 202010000000001 202010000000002 202010000000003; do
  curl -sS -X POST http://localhost:8080/api/v1/ue_movement/start-loop \
    -H "accept: application/json" \
    -H "Authorization: Bearer $NEF_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"supi\":\"$supi\"}" | jq
done
```

> **Tip:** Stop the loops with the matching `/stop-loop` call before tearing down the stack.

---

## 6. Capture ML Observability Evidence

### 6.1 Standard ML Run (5xx labels)

With loops active, the NEF will occasionally deliver out-of-spec telemetry that triggers sanitisation and produces `ml_http_5xx` fallbacks. Wait ~2–3 minutes, then query Prometheus:

```bash
curl -sS --get --data-urlencode "query=nef_handover_fallback_service_total" \
  http://localhost:9090/api/v1/query | jq
```

Sample response:

```json
{
  "metric": {"reason": "ml_http_5xx", "service_type": "unknown"},
  "value": [ 1762462331.767, "229" ]
}
```

### 6.2 Induce 4xx Labels (credential edge case)

1. Temporarily break ML authentication.

   ```bash
   cd "$THESIS_ROOT/5g-network-optimization"
   sed -i'' 's/ML_SERVICE_PASSWORD=pass/ML_SERVICE_PASSWORD=wrongpass/' .env
   COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose up -d --force-recreate nef-emulator
   ```

2. Re-run the UE loops (Section 5). Within a minute Prometheus will record `ml_http_4xx` fallbacks.

   ```bash
   curl -sS --get --data-urlencode "query=nef_handover_fallback_service_total" \
     --data-urlencode "time=$(date -u +%s)" \
     http://localhost:9090/api/v1/query | jq
   ```

3. **Restore credentials immediately after the demo.**

   ```bash
   sed -i'' 's/ML_SERVICE_PASSWORD=wrongpass/ML_SERVICE_PASSWORD=pass/' .env
   COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose up -d --force-recreate nef-emulator
   ```

4. Restart UE loops once more so ML predictions resume normally.

---

## 7. Switch to A3 Baseline

Demonstrate the rule-based fallback for comparison.

```bash
cd "$THESIS_ROOT/5g-network-optimization"
COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose down
ML_HANDOVER_ENABLED=0 docker compose up -d
```

Re-run topology initialisation and UE loops (Sections 4–5). Collect the same Prometheus queries for the A3 window—`ml_http_*` labels should remain at zero while `nef_handover_decisions_total` continues to grow.

Return to ML mode with:

```bash
COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose down
COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose up -d
```

---

## 8. Automated ML vs A3 Comparison (Optional)

Instead of collecting metrics manually, run the thesis comparison script after completing the manual walk-through.

```bash
cd "$THESIS_ROOT"
./scripts/run_comparison.sh 10
```

Results land under `thesis_results/comparison_<timestamp>/` and include:

- `comparison_metrics.csv` – tabular KPI summary.
- `COMPARISON_SUMMARY.txt` – narrative suitable for the defence deck.
- `07_comprehensive_comparison.png` – the go-to slide when presenting.

---

## 9. Edge Cases and Multi-Antenna Variants

- **Additional antennas:** extend `init_simple_http.sh` or build a bespoke script using the REST calls shown there. Re-run the script after every Compose restart.
- **Ping-pong stress tests:** tweak `MIN_HANDOVER_INTERVAL_S`, `MAX_HANDOVERS_PER_MINUTE`, and `PINGPONG_WINDOW_S` in `.env` to emphasise oscillation scenarios.
- **QoS profiles:** modify the `service_type` in Section 5 requests or run `scripts/run_thesis_experiment.sh` for long-running scenarios with alternating QoS classes.

Cross-reference [`docs/MULTI_ANTENNA_TESTING.md`](MULTI_ANTENNA_TESTING.md) for regression cases that validate the wider antenna grid.

---

## 10. Cleanup Checklist

```bash
cd "$THESIS_ROOT/5g-network-optimization"
NEF_TOKEN=$(curl -sS -X POST http://localhost:8080/api/v1/login/access-token \
  -H "accept: application/json" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=admin@my-email.com" \
  --data-urlencode "password=pass" \
  -d "grant_type=&scope=&client_id=&client_secret=" | jq -r .access_token)

for supi in 202010000000001 202010000000002 202010000000003; do
  curl -sS -X POST http://localhost:8080/api/v1/ue_movement/stop-loop \
    -H "accept: application/json" \
    -H "Authorization: Bearer $NEF_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"supi\":\"$supi\"}" | jq
done

COMPOSE_PROFILES=ml ML_LOCAL=ml docker compose down -v
```

Confirm that `.env` once again contains `ML_SERVICE_PASSWORD=pass` before committing any changes.

---

By following these steps you deliver a full “show” of the thesis system: ML-driven handovers with clear observability, the induced edge cases that justify new Prometheus labels, and a repeatable baseline that proves how ML outperforms A3 in dense antenna deployments.
