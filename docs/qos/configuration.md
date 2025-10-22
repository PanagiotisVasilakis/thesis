# QoS Configuration Overrides

The QoS classifier consumes the shared `features.yaml` file in
`5g-network-optimization/services/ml-service/ml_service/app/config` to discover service-specific
scoring profiles.  Each profile now supports a `metric_defaults` section that
captures the canonical weight/threshold pairs for the metrics associated with a
service type.  These defaults allow downstream tooling to surface recommended
values, provide UI hints, or seed API payloads without duplicating the scoring
configuration.

```yaml
qos_profiles:
  embb:
    metrics:
      latency_requirement_ms:
        weight: 0.5
        objective: min
        threshold: 30.0
    metric_defaults:
      latency_requirement_ms:
        weight: 0.5
        threshold: 30.0
```

## Using defaults programmatically

The `QoSServiceClassifier` exposes a
`get_metric_defaults(service_type: Optional[str]) -> Dict[str, Dict[str, float]]`
helper that returns the parsed defaults.  When the requested service type is
missing the classifier falls back to the configured default profile.

```python
from ml_service.app.qos import QoSServiceClassifier

classifier = QoSServiceClassifier()
embb_defaults = classifier.get_metric_defaults("embb")
# {"latency_requirement_ms": {"weight": 0.5, "threshold": 30.0}, ...}
```

## Overriding defaults

To override a value, update the relevant `metric_defaults` entry in
`features.yaml`.  Values are coerced to floats during loading, so strings such
as `"99.9"` are accepted.  Omitting a key leaves the corresponding value
undefined, allowing consumers to detect missing guidance.  Invalid values raise
`ValueError` during configuration load, failing fast during service startup.
