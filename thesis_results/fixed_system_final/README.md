# Thesis Experiment Results: fixed_system_final

**Generated**: Wed Nov 12 13:23:00 EET 2025
**Duration**: 10 minutes per mode

## Quick Access

- **Executive Summary**: COMPARISON_SUMMARY.txt
- **Key Visualization**: 07_comprehensive_comparison.png
- **All Metrics**: comparison_metrics.csv
- **Experiment Details**: EXPERIMENT_SUMMARY.md

## File Structure

```
fixed_system_final/
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
```

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

```bash
./scripts/run_thesis_experiment.sh 10 fixed_system_final
```

All configuration is captured in experiment_metadata.json.

