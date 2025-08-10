# Feature Ranges and Data Drift Alerts

This service validates incoming feature values using `ml_service/app/config/features.yaml`. Each feature specifies numeric min/max bounds or allowed categories. During prediction, `AntennaSelector` checks for missing features and rejects requests with values outside the defined ranges.

The `DataDriftMonitor` tracks mean values of numeric features over a rolling window. A baseline distribution can be supplied at initialization or is derived from the first full window. For each feature, an alert is logged when the absolute difference between the current mean and baseline exceeds its threshold (if provided) or a global threshold of `1.0`.

Configure per-feature thresholds when creating the monitor:

```python
monitor = DataDriftMonitor(window_size=100, thresholds={"speed": 5.0, "sinr_current": 2.0})
```

Alerts appear in the application logs with the feature name, drift amount, and threshold value.
