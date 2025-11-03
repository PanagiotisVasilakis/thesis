# Results Generation Checklist
## Step-by-Step Guide for Producing Thesis Results

This checklist ensures you generate all necessary data, visualizations, and metrics for your thesis presentation.

---

## Pre-Experiment Setup

### ☐ Environment Preparation

```bash
# 1. Verify all dependencies installed
cd ~/thesis
./scripts/install_deps.sh

# 2. Confirm Docker resources
docker info | grep "Total Memory"
# Should show at least 8GB

# 3. Clean previous runs
docker compose -f 5g-network-optimization/docker-compose.yml down -v
rm -rf output/* presentation_assets/*
mkdir -p output/{coverage,trajectory,mobility,metrics}
mkdir -p presentation_assets
```

### ☐ Configuration Validation

```bash
# Create results configuration
cat > ~/thesis/.env.results << 'EOF'
# ML Configuration for Results
ML_HANDOVER_ENABLED=1
MODEL_TYPE=lightgbm
LIGHTGBM_TUNE=1
LIGHTGBM_TUNE_N_ITER=20
LIGHTGBM_TUNE_CV=5
NEIGHBOR_COUNT=3

# QoS Settings
ML_CONFIDENCE_THRESHOLD=0.5
AUTO_RETRAIN=true
RETRAIN_THRESHOLD=0.08

# A3 Parameters (for comparison)
A3_HYSTERESIS_DB=2.0
A3_TTT_S=0.0

# Authentication
AUTH_USERNAME=admin
AUTH_PASSWORD=admin
JWT_SECRET=thesis-experiment-secret-key

# Logging
LOG_LEVEL=INFO

# Performance
ASYNC_MODEL_WORKERS=4
RATE_LIMIT_PER_MINUTE=200
EOF

# Use this configuration
cp ~/thesis/.env.results ~/thesis/.env
```

---

## Phase 1: Data Generation

### ☐ Generate Synthetic QoS Datasets

```bash
cd ~/thesis

# 1. Balanced dataset (general purpose)
python scripts/data_generation/synthetic_generator.py \
  --records 20000 \
  --profile balanced \
  --output output/qos_balanced_20k.csv \
  --format csv \
  --seed 42

# 2. URLLC-heavy (low latency focus)
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile urllc-heavy \
  --output output/qos_urllc_10k.csv \
  --format csv \
  --seed 123

# 3. eMBB-heavy (high throughput focus)
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile embb-heavy \
  --output output/qos_embb_10k.csv \
  --format csv \
  --seed 456

# 4. mMTC-heavy (IoT focus)
python scripts/data_generation/synthetic_generator.py \
  --records 10000 \
  --profile mmtc-heavy \
  --output output/qos_mmtc_10k.csv \
  --format csv \
  --seed 789

# Verify generation
wc -l output/qos_*.csv
```

**Expected Output:**
- 4 CSV files with QoS data
- ~20,000 total records for balanced
- ~10,000 each for specialized profiles

### ☐ Validate Synthetic Data Quality

```bash
# Run statistical tests
pytest tests/data_generation/test_synthetic_generator.py -v

# Verify distributions
python -c "
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv('output/qos_balanced_20k.csv')
print('Service Type Distribution:')
print(df['service_type'].value_counts())
print('\nLatency Statistics:')
print(df['latency_ms'].describe())
print('\nThroughput Statistics:')
print(df['throughput_mbps'].describe())

# Quick visualization
fig, axes = plt.subplots(2, 2, figsize=(12, 10))
df['service_type'].value_counts().plot(kind='bar', ax=axes[0,0], title='Service Type Distribution')
df['latency_ms'].hist(bins=50, ax=axes[0,1], title='Latency Distribution')
df['throughput_mbps'].hist(bins=50, ax=axes[1,0], title='Throughput Distribution')
df['reliability_pct'].hist(bins=50, ax=axes[1,1], title='Reliability Distribution')
plt.tight_layout()
plt.savefig('output/synthetic_data_validation.png', dpi=300)
print('Saved validation plot to output/synthetic_data_validation.png')
"
```

---

## Phase 2: ML Mode Experiment

### ☐ Start System with ML Enabled

```bash
cd ~/thesis

# Start with ML configuration
ML_HANDOVER_ENABLED=1 \
LIGHTGBM_TUNE=1 \
docker compose -f 5g-network-optimization/docker-compose.yml up --build -d

# Wait for startup (check logs)
docker compose -f 5g-network-optimization/docker-compose.yml logs -f ml-service \
  | grep "Model trained successfully"
# Press Ctrl+C after seeing training complete

# Verify services
curl http://localhost:5050/api/health | jq
curl http://localhost:8080/metrics | head -20
```

### ☐ Initialize Network Topology

```bash
cd ~/thesis/5g-network-optimization/services/nef-emulator

export DOMAIN=localhost
export NGINX_HTTPS=8080
export FIRST_SUPERUSER=admin@my-email.com
export FIRST_SUPERUSER_PASSWORD=pass

# Initialize with demo data
./backend/app/app/db/init_simple.sh

# Verify initialization
curl "http://localhost:8080/api/v1/Cells" | jq length
# Should show 4 cells

curl "http://localhost:8080/api/v1/UEs" | jq length
# Should show 3 UEs
```

### ☐ Collect ML Training Data

```bash
cd ~/thesis/5g-network-optimization/services/ml-service

# Start UE movement first (via NEF web UI or API)
curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -d '{"supi": "202010000000001", "speed": 10.0}'

curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -d '{"supi": "202010000000002", "speed": 5.0}'

curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -d '{"supi": "202010000000003", "speed": 15.0}'

# Collect data for 10 minutes
python collect_training_data.py \
  --url http://localhost:8080 \
  --username admin \
  --password admin \
  --duration 600 \
  --interval 1 \
  --output ~/thesis/output/ml_training_data_run1.json \
  --train

# Record timestamp
echo "ML Training Run 1 completed at $(date)" >> ~/thesis/output/experiment_log.txt
```

### ☐ Run ML Performance Tests

```bash
cd ~/thesis

# Get auth token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Test batch of predictions
for i in {1..100}; do
  curl -s -X POST http://localhost:5050/api/predict-with-qos \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{
      \"ue_id\": \"perf-test-$i\",
      \"latitude\": $((100 + i * 5)),
      \"longitude\": $((50 + i * 3)),
      \"connected_to\": \"antenna_1\",
      \"service_type\": \"urllc\",
      \"service_priority\": 9,
      \"rf_metrics\": {
        \"antenna_1\": {\"rsrp\": $((- 80 - i % 20)), \"sinr\": $((15 + i % 10))},
        \"antenna_2\": {\"rsrp\": $((- 85 - i % 15)), \"sinr\": $((12 + i % 8))},
        \"antenna_3\": {\"rsrp\": $((- 90 - i % 25)), \"sinr\": $((10 + i % 12))}
      }
    }" >> /dev/null
  
  if [ $((i % 10)) -eq 0 ]; then
    echo "Completed $i predictions..."
  fi
done

echo "ML Performance Test completed at $(date)" >> output/experiment_log.txt
```

### ☐ Export ML Metrics

```bash
cd ~/thesis

# Wait a few seconds for Prometheus to scrape
sleep 30

# Export key metrics
curl -s "http://localhost:9090/api/v1/query?query=ml_prediction_requests_total" \
  | jq > output/metrics/ml_prediction_requests.json

curl -s "http://localhost:9090/api/v1/query?query=ml_prediction_confidence_avg" \
  | jq > output/metrics/ml_confidence.json

curl -s "http://localhost:9090/api/v1/query?query=nef_handover_decisions_total" \
  | jq > output/metrics/ml_handover_decisions.json

curl -s "http://localhost:9090/api/v1/query?query=nef_handover_fallback_total" \
  | jq > output/metrics/ml_fallbacks.json

curl -s "http://localhost:9090/api/v1/query?query=nef_handover_compliance_total" \
  | jq > output/metrics/ml_qos_compliance.json

# Export time series (last hour)
END=$(date +%s)
START=$((END - 3600))

curl -s "http://localhost:9090/api/v1/query_range?query=ml_prediction_latency_seconds&start=$START&end=$END&step=60" \
  | jq > output/metrics/ml_latency_timeseries.json

echo "ML Metrics exported at $(date)" >> output/experiment_log.txt
```

### ☐ Stop ML Mode

```bash
cd ~/thesis

# Stop services but keep data
docker compose -f 5g-network-optimization/docker-compose.yml stop

echo "ML Mode stopped at $(date)" >> output/experiment_log.txt
```

---

## Phase 3: A3-Only Mode Experiment

### ☐ Start System with A3 Only

```bash
cd ~/thesis

# Clear Prometheus data for clean comparison
docker compose -f 5g-network-optimization/docker-compose.yml down -v

# Start with A3-only configuration
ML_HANDOVER_ENABLED=0 \
docker compose -f 5g-network-optimization/docker-compose.yml up --build -d

# Wait for startup
sleep 30

# Verify A3 mode
docker compose -f 5g-network-optimization/docker-compose.yml logs nef-emulator \
  | grep -i "a3\|handover" | tail -10
```

### ☐ Re-initialize Topology

```bash
cd ~/thesis/5g-network-optimization/services/nef-emulator

# Use same configuration as ML mode for fair comparison
export DOMAIN=localhost
export NGINX_HTTPS=8080
export FIRST_SUPERUSER=admin@my-email.com
export FIRST_SUPERUSER_PASSWORD=pass

./backend/app/app/db/init_simple.sh

echo "A3 Mode topology initialized at $(date)" >> ~/thesis/output/experiment_log.txt
```

### ☐ Run A3 Performance Tests

```bash
# Start same UE movements
curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -d '{"supi": "202010000000001", "speed": 10.0}'

curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -d '{"supi": "202010000000002", "speed": 5.0}'

curl -X POST "http://localhost:8080/api/v1/ue_movement/start" \
  -d '{"supi": "202010000000003", "speed": 15.0}'

# Let run for same duration (10 minutes)
sleep 600

echo "A3 Performance Test completed at $(date)" >> ~/thesis/output/experiment_log.txt
```

### ☐ Export A3 Metrics

```bash
cd ~/thesis

# Export A3 metrics
curl -s "http://localhost:9090/api/v1/query?query=nef_handover_decisions_total" \
  | jq > output/metrics/a3_handover_decisions.json

curl -s "http://localhost:9090/api/v1/query?query=nef_request_duration_seconds" \
  | jq > output/metrics/a3_request_duration.json

# Time series
END=$(date +%s)
START=$((END - 3600))

curl -s "http://localhost:9090/api/v1/query_range?query=nef_handover_decisions_total&start=$START&end=$END&step=60" \
  | jq > output/metrics/a3_handover_timeseries.json

echo "A3 Metrics exported at $(date)" >> output/experiment_log.txt
```

---

## Phase 4: Visualization Generation

### ☐ Generate Coverage Maps

```bash
cd ~/thesis

# Restart ML mode for visualization
ML_HANDOVER_ENABLED=1 docker compose -f 5g-network-optimization/docker-compose.yml up -d
sleep 30

# Get token
TOKEN=$(curl -s -X POST http://localhost:5050/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}' | jq -r .access_token)

# Generate coverage map
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5050/api/visualization/coverage-map" \
  --output output/coverage/ml_coverage_map.png

# Verify
ls -lh output/coverage/
```

### ☐ Generate Trajectory Visualizations

```bash
# Via presentation assets script
python scripts/generate_presentation_assets.py

# Verify outputs
ls -lh presentation_assets/
ls -lh output/trajectory/
ls -lh output/mobility/
```

### ☐ Generate Mobility Model Examples

```bash
# Run mobility tests to generate trajectory plots
pytest 5g-network-optimization/services/nef-emulator/tests/test_mobility_models.py \
  -v --tb=short

# Check outputs
ls -lh output/mobility/
```

---

## Phase 5: Statistical Analysis

### ☐ Compare ML vs A3 Performance

```bash
cd ~/thesis

# Create analysis script
cat > scripts/statistical_analysis.py << 'PYTHON'
#!/usr/bin/env python3
import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 8)

# Load metrics
with open('output/metrics/ml_handover_decisions.json') as f:
    ml_data = json.load(f)

with open('output/metrics/a3_handover_decisions.json') as f:
    a3_data = json.load(f)

# Extract values
ml_applied = float([r for r in ml_data['data']['result'] 
                    if r['metric'].get('outcome') == 'applied'][0]['value'][1])
ml_skipped = float([r for r in ml_data['data']['result'] 
                    if r['metric'].get('outcome') == 'skipped'][0]['value'][1])

a3_applied = float([r for r in a3_data['data']['result'] 
                    if r['metric'].get('outcome') == 'applied'][0]['value'][1])
a3_skipped = float([r for r in a3_data['data']['result'] 
                    if r['metric'].get('outcome') == 'skipped'][0]['value'][1])

# Calculate metrics
ml_total = ml_applied + ml_skipped
a3_total = a3_applied + a3_skipped
ml_success_rate = ml_applied / ml_total * 100
a3_success_rate = a3_applied / a3_total * 100

# Load fallback data
with open('output/metrics/ml_fallbacks.json') as f:
    fallback_data = json.load(f)
ml_fallbacks = float(fallback_data['data']['result'][0]['value'][1])

# Print summary
print("=" * 60)
print("ML vs A3 Handover Comparison")
print("=" * 60)
print(f"\nML Mode:")
print(f"  Total Decisions: {ml_total}")
print(f"  Applied: {ml_applied} ({ml_success_rate:.2f}%)")
print(f"  Skipped: {ml_skipped}")
print(f"  Fallbacks to A3: {ml_fallbacks}")
print(f"  ML Success Rate: {(ml_applied - ml_fallbacks) / ml_total * 100:.2f}%")

print(f"\nA3 Mode:")
print(f"  Total Decisions: {a3_total}")
print(f"  Applied: {a3_applied} ({a3_success_rate:.2f}%)")
print(f"  Skipped: {a3_skipped}")

print(f"\nImprovement:")
improvement = ((ml_applied - a3_applied) / a3_applied * 100)
print(f"  Handover Increase: {ml_applied - a3_applied} (+{improvement:.2f}%)")

# Create comparison visualizations
fig, axes = plt.subplots(2, 2, figsize=(15, 12))

# 1. Handover decisions comparison
categories = ['ML Mode', 'A3 Mode']
applied_counts = [ml_applied, a3_applied]
skipped_counts = [ml_skipped, a3_skipped]

x = np.arange(len(categories))
width = 0.35

axes[0, 0].bar(x - width/2, applied_counts, width, label='Applied', color='green', alpha=0.7)
axes[0, 0].bar(x + width/2, skipped_counts, width, label='Skipped', color='red', alpha=0.7)
axes[0, 0].set_ylabel('Count')
axes[0, 0].set_title('Handover Decisions: ML vs A3')
axes[0, 0].set_xticks(x)
axes[0, 0].set_xticklabels(categories)
axes[0, 0].legend()
axes[0, 0].grid(True, alpha=0.3)

# 2. Success rate comparison
axes[0, 1].bar(categories, [ml_success_rate, a3_success_rate], color=['blue', 'orange'], alpha=0.7)
axes[0, 1].set_ylabel('Success Rate (%)')
axes[0, 1].set_title('Handover Success Rate')
axes[0, 1].set_ylim([0, 100])
axes[0, 1].grid(True, alpha=0.3)

# 3. ML fallback analysis
ml_categories = ['ML Decisions', 'A3 Fallbacks']
ml_breakdown = [ml_applied - ml_fallbacks, ml_fallbacks]
colors = ['green', 'orange']
axes[1, 0].pie(ml_breakdown, labels=ml_categories, autopct='%1.1f%%', 
               colors=colors, startangle=90)
axes[1, 0].set_title('ML Decision Breakdown')

# 4. Summary table
summary_data = {
    'Metric': ['Total Decisions', 'Applied', 'Success Rate (%)', 'Improvement'],
    'ML Mode': [f'{ml_total:.0f}', f'{ml_applied:.0f}', 
                f'{ml_success_rate:.2f}', f'+{improvement:.2f}%'],
    'A3 Mode': [f'{a3_total:.0f}', f'{a3_applied:.0f}', 
                f'{a3_success_rate:.2f}', 'baseline']
}
df_summary = pd.DataFrame(summary_data)

axes[1, 1].axis('tight')
axes[1, 1].axis('off')
table = axes[1, 1].table(cellText=df_summary.values, colLabels=df_summary.columns,
                          cellLoc='center', loc='center', colWidths=[0.4, 0.3, 0.3])
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1, 2)
axes[1, 1].set_title('Performance Summary', pad=20)

plt.tight_layout()
plt.savefig('output/ml_vs_a3_comparison.png', dpi=300, bbox_inches='tight')
print(f"\nSaved comparison chart to output/ml_vs_a3_comparison.png")

# Export CSV
df_summary.to_csv('output/comparison_summary.csv', index=False)
print(f"Saved summary to output/comparison_summary.csv")
PYTHON

# Run analysis
python3 scripts/statistical_analysis.py
```

### ☐ Analyze QoS Compliance

```bash
cat > scripts/qos_analysis.py << 'PYTHON'
#!/usr/bin/env python3
import json
import matplotlib.pyplot as plt
import seaborn as sns

# Load QoS compliance metrics
with open('output/metrics/ml_qos_compliance.json') as f:
    qos_data = json.load(f)

# Extract data
compliance_ok = float([r for r in qos_data['data']['result'] 
                       if r['metric'].get('outcome') == 'ok'][0]['value'][1])
compliance_failed = float([r for r in qos_data['data']['result'] 
                           if r['metric'].get('outcome') == 'failed'][0]['value'][1])

total = compliance_ok + compliance_failed
compliance_rate = compliance_ok / total * 100

print(f"\nQoS Compliance Analysis:")
print(f"  Total QoS Checks: {total}")
print(f"  Passed: {compliance_ok} ({compliance_rate:.2f}%)")
print(f"  Failed: {compliance_failed} ({100 - compliance_rate:.2f}%)")

# Visualization
fig, ax = plt.subplots(figsize=(10, 6))
categories = ['Passed', 'Failed']
values = [compliance_ok, compliance_failed]
colors = ['green', 'red']

ax.bar(categories, values, color=colors, alpha=0.7)
ax.set_ylabel('Count')
ax.set_title(f'QoS Compliance (Success Rate: {compliance_rate:.2f}%)')
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('output/qos_compliance.png', dpi=300)
print("Saved QoS compliance chart to output/qos_compliance.png")
PYTHON

python3 scripts/qos_analysis.py
```

---

## Phase 6: Test Execution

### ☐ Run Complete Test Suite

```bash
cd ~/thesis

# Run all tests with coverage
./scripts/run_tests.sh

# Extract coverage percentage
COVERAGE=$(grep "TOTAL" CI-CD_reports/coverage_*.txt | tail -1 | awk '{print $NF}')
echo "Test Coverage: $COVERAGE" >> output/experiment_log.txt

# Run specific critical tests
pytest tests/mlops/test_qos_feature_ranges.py -v
pytest tests/data_generation/test_synthetic_generator.py -v
pytest 5g-network-optimization/services/ml-service/tests/test_antenna_selector.py -v
```

---

## Phase 7: Final Deliverables

### ☐ Compile All Results

```bash
cd ~/thesis

# Create results package
mkdir -p thesis_results/{data,metrics,visualizations,analysis}

# Copy data
cp output/qos_*.csv thesis_results/data/
cp output/ml_training_data_run1.json thesis_results/data/

# Copy metrics
cp output/metrics/*.json thesis_results/metrics/

# Copy visualizations
cp output/coverage/*.png thesis_results/visualizations/
cp output/trajectory/*.png thesis_results/visualizations/
cp output/mobility/*.png thesis_results/visualizations/
cp presentation_assets/*.png thesis_results/visualizations/

# Copy analysis
cp output/ml_vs_a3_comparison.png thesis_results/analysis/
cp output/qos_compliance.png thesis_results/analysis/
cp output/comparison_summary.csv thesis_results/analysis/
cp output/synthetic_data_validation.png thesis_results/analysis/

# Copy logs
cp output/experiment_log.txt thesis_results/
cp CI-CD_reports/coverage_*.txt thesis_results/ 2>/dev/null || true

# Create archive
tar -czf thesis_results_$(date +%Y%m%d_%H%M%S).tar.gz thesis_results/

echo "Results package created!"
ls -lh thesis_results_*.tar.gz
```

### ☐ Generate Final Report

```bash
cat > thesis_results/EXPERIMENT_SUMMARY.md << 'SUMMARY'
# Experiment Summary

## Experiment Details
- **Date**: [Generated automatically]
- **Duration**: [Total runtime]
- **System Configuration**: 
  - ML Model: LightGBM with hyperparameter tuning
  - UEs: 3 (varying speeds: 5, 10, 15 m/s)
  - Cells: 4 (overlapping coverage)
  - Mobility Models: Linear, L-shaped, Random Waypoint

## Data Generated
- Synthetic QoS datasets: 50,000 total records
- Live training data: 600 samples
- Test coverage: [Insert %]

## Key Findings
### ML Mode
- Total handover decisions: [From metrics]
- Applied handovers: [From metrics]
- Success rate: [Calculated]
- QoS compliance rate: [From analysis]
- Average fallback rate: [From metrics]

### A3 Mode
- Total handover decisions: [From metrics]
- Applied handovers: [From metrics]
- Success rate: [Calculated]

### Improvement
- Handover increase: [Percentage]
- QoS compliance improvement: [Percentage]
- Latency reduction: [If measured]

## Files Included
- `data/`: Synthetic and collected datasets
- `metrics/`: Exported Prometheus metrics
- `visualizations/`: Coverage maps, trajectories, mobility plots
- `analysis/`: Comparison charts and statistical summaries
- `experiment_log.txt`: Complete execution timeline

## Reproducibility
All experiments can be reproduced using:
```bash
cd ~/thesis
cat .env.results  # View configuration
./docs/COMPLETE_DEPLOYMENT_GUIDE.md  # Follow guide
```

## Next Steps
1. Statistical significance testing (t-tests)
2. Extended runtime experiments (24+ hours)
3. Additional mobility model variations
4. Real-world testbed validation
SUMMARY

# Fill in the summary with actual data
python3 << 'PYTHON'
import json
from datetime import datetime

# Load metrics and populate summary
with open('output/metrics/ml_handover_decisions.json') as f:
    ml_data = json.load(f)

# ... Add code to populate summary ...

print("Summary template created. Please fill in the specific metrics.")
PYTHON
```

---

## Verification Checklist

### Data Quality
- [ ] Synthetic datasets generated (4 profiles)
- [ ] Statistical validation passed
- [ ] Distribution plots created

### ML Experiment
- [ ] System started in ML mode
- [ ] Topology initialized (4 cells, 3 UEs)
- [ ] Training data collected (600+ samples)
- [ ] Model trained with tuning
- [ ] Performance tests completed (100 predictions)
- [ ] Metrics exported (6+ files)

### A3 Experiment
- [ ] System restarted in A3 mode
- [ ] Same topology used
- [ ] Same UE movements
- [ ] Performance tests completed
- [ ] Metrics exported

### Visualizations
- [ ] Coverage map generated
- [ ] Trajectory plots created (2+)
- [ ] Mobility model examples (8+ plots)
- [ ] Presentation assets complete

### Analysis
- [ ] Statistical comparison completed
- [ ] QoS compliance analyzed
- [ ] Comparison charts generated
- [ ] Summary CSV exported

### Testing
- [ ] Full test suite passed
- [ ] Coverage report generated (90%+)
- [ ] Critical tests verified

### Deliverables
- [ ] All data files archived
- [ ] All metrics exported
- [ ] All visualizations saved
- [ ] Analysis results compiled
- [ ] Experiment log complete
- [ ] Summary report drafted
- [ ] Results package created (.tar.gz)

---

## Troubleshooting

**Issue**: Metrics not showing in Prometheus  
**Solution**: Wait 30-60 seconds after tests, Prometheus scrapes every 15s

**Issue**: Coverage map generation fails  
**Solution**: Ensure ML service model is trained, check `/api/model-health`

**Issue**: Statistical analysis script errors  
**Solution**: Verify all metric files exist in `output/metrics/`

**Issue**: Low test coverage  
**Solution**: Re-run `./scripts/run_tests.sh`, check for skipped tests

---

## Timeline Estimate

- Phase 1 (Data Generation): 30 minutes
- Phase 2 (ML Experiment): 45 minutes
- Phase 3 (A3 Experiment): 30 minutes
- Phase 4 (Visualizations): 20 minutes
- Phase 5 (Analysis): 30 minutes
- Phase 6 (Testing): 20 minutes
- Phase 7 (Deliverables): 15 minutes

**Total**: ~3.5 hours for complete results generation

---

**Document Version**: 1.0  
**Last Updated**: November 2025

