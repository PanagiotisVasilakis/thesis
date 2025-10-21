from prometheus_client import Counter, Histogram, CollectorRegistry

REGISTRY = CollectorRegistry()

# Count how many handover decisions were made
HANDOVER_DECISIONS = Counter(
    'nef_handover_decisions_total',
    'Number of handover decisions taken',
    ['outcome'],
    registry=REGISTRY
)

# Count how many times ML predictions were discarded due to low confidence
HANDOVER_FALLBACKS = Counter(
    'nef_handover_fallback_total',
    'Number of ML predictions falling back to the A3 rule',
    registry=REGISTRY
)

# Record compliance outcomes of ML predictions when QoS checks are applied
HANDOVER_COMPLIANCE = Counter(
    'nef_handover_compliance_total',
    'Number of ML predictions evaluated for QoS compliance',
    ['outcome'],
    registry=REGISTRY,
)

# Observe request processing time for each endpoint
REQUEST_DURATION = Histogram(
    'nef_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY
)
