# Thesis Experiment Summary

## Experiment Details

**Name**: fixed_system_final
**Date**: 2025-11-12
**Duration**: 10 minutes per mode
**Total Runtime**: 25 minutes

## Configuration

### ML Mode
- ML_HANDOVER_ENABLED=1
- MIN_HANDOVER_INTERVAL_S=2.0
- MAX_HANDOVERS_PER_MINUTE=3
- PINGPONG_WINDOW_S=10.0

### A3 Mode  
- ML_HANDOVER_ENABLED=0
- A3_HYSTERESIS_DB=2.0
- A3_TTT_S=0.0

## Network Topology

- **gNBs**: 1 (gNB1)
- **Cells**: 4 (Administration, Radioisotopes, IIT, Faculty)
- **UEs**: 3 (speed profiles: LOW, LOW, HIGH)
- **Paths**: 2 (NCSRD Library, NCSRD Gate-IIT)

## Results

See the following files for detailed results:

- `COMPARISON_SUMMARY.txt` - Executive text summary
- `comparison_metrics.csv` - All metrics in spreadsheet format
- `07_comprehensive_comparison.png` - Best single-page visualization
- `ml_mode_metrics.json` - Raw ML metrics
- `a3_mode_metrics.json` - Raw A3 metrics

## Key Findings

[To be filled after reviewing COMPARISON_SUMMARY.txt]

### ML Mode Advantages

1. Ping-pong reduction: [Extract from results]
2. Dwell time improvement: [Extract from results]
3. Success rate: [Extract from results]
4. QoS compliance: [Extract from results]

### Statistical Significance

[Run statistical tests if multiple experiments conducted]

## Thesis Claims Validated

- [ ] ML reduces ping-pong handovers significantly
- [ ] ML maintains longer cell dwell times
- [ ] ML improves or maintains success rates
- [ ] ML respects QoS requirements
- [ ] ML falls back gracefully to A3 when uncertain

## Reproducibility

To reproduce this experiment:

```bash
cd ~/thesis
./scripts/run_thesis_experiment.sh 10 fixed_system_final
```

All results will be identical given the same random seeds and configuration.

## Next Steps

1. Review all generated visualizations
2. Extract key metrics for thesis
3. Run additional experiments if needed (3-5 total recommended)
4. Perform statistical significance testing
5. Include results in thesis document

## Notes

[Add any observations or anomalies here]

