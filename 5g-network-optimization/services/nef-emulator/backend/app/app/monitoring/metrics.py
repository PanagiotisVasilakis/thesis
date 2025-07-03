from prometheus_client import Counter, Histogram, CollectorRegistry

REGISTRY = CollectorRegistry()

# Count how many handover decisions were made
HANDOVER_DECISIONS = Counter(
    'nef_handover_decisions_total',
    'Number of handover decisions taken',
    ['outcome'],
    registry=REGISTRY
)

# Observe request processing time for each endpoint
REQUEST_DURATION = Histogram(
    'nef_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
    registry=REGISTRY
)
