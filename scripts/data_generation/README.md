# Synthetic QoS Dataset Generator

`scripts/data_generation/synthetic_generator.py` provides both a reusable Python
API and a command-line utility for producing labelled QoS request datasets.

## Usage

### Command line

```bash
python scripts/data_generation/synthetic_generator.py \
    --records 5000 \
    --profile embb-heavy \
    --seed 42 \
    --output output/embb-heavy.csv \
    --format csv
```

Key flags:

- `--records` – total number of synthetic requests to emit.
- `--profile` – service mix preset. Choose from `balanced`, `embb-heavy`,
  `urllc-heavy`, `mmtc-heavy`, or `uniform`. Presets normalise internally, so
  custom ratios need only sum to a positive value if you extend the module.
- `--seed` – optional RNG seed for reproducible datasets. Omit to use system
  entropy for exploratory runs.
- `--output` – destination file path. Directories are created automatically.
  Leave unset to stream the dataset to stdout.
- `--format` – output serialization: `csv` (default) or `json`.

### Python API

```python
from scripts.data_generation.synthetic_generator import generate_synthetic_requests

data = generate_synthetic_requests(100, profile="balanced", seed=7)
```

The API returns a list of dictionaries with the schema:

```text
request_id, service_type, latency_ms, reliability_pct, throughput_mbps, priority
```

All records share the same keys, so downstream consumers can rely on a stable
CSV header or JSON object structure. Use the optional `seed` argument to keep
experiments deterministic across runs.

## Interpreting the dataset

- **Service types**: URLLC, eMBB, mMTC, and `default` align with 3GPP-inspired
  profiles captured in the module's `SERVICE_PROFILES` map.
- **Latency/Throughput/ Reliability**: Samples are drawn from triangular
  distributions using the per-profile `min`, `max`, and `mode` values.
- **Priority**: Integer score sampled uniformly within the configured bounds.

When extending the generator, update `SERVICE_PROFILES` and (optionally)
`SERVICE_MIX_PROFILES`. New services are automatically normalised and sampled by
`generate_synthetic_requests`.
