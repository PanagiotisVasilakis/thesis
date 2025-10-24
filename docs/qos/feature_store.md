# QoS Feature Store Enhancements

This document captures the schema and operational updates required to expose QoS
metrics through Feast.

## Schema updates

The UE metrics feature view now includes the following QoS columns in addition
to the existing mobility signals:

| Column             | Type    | Description                                        |
| ------------------ | ------- | -------------------------------------------------- |
| `latency_ms`       | Float32 | Observed round-trip latency in milliseconds.       |
| `throughput_mbps`  | Float32 | Effective user throughput measured in Mbps.        |
| `packet_loss_rate` | Float32 | Packet loss percentage reported for the UE link.   |

These fields are defined alongside the rest of the feature schema in
`mlops/feature_store/feature_repo/schema.py` and therefore flow to both the
offline Parquet source and the online SQLite store. The canonical offline file
is expected at `mlops/feast_repo/data/training_data.parquet`; however, binary
artifacts are not committed to the repository. Generate or export the dataset
locally before running Feast commands.

## Preparing the offline dataset

Use the synthetic QoS generator to produce source data and convert it to
Parquet:

```bash
python scripts/data_generation/synthetic_generator.py \
    --records 1000 \
    --profile balanced \
    --seed 7 \
    --output mlops/feast_repo/data/training_data.csv

python - <<'PY'
import pandas as pd

df = pd.read_csv("mlops/feast_repo/data/training_data.csv")
df.to_parquet("mlops/feast_repo/data/training_data.parquet", index=False)
PY
```

Ensure the resulting Parquet file includes the QoS fields described above prior
to materialising the feature view.

## Applying the changes

Run the following commands from the repository root to materialise the updated
schema locally:

```bash
pip install feast pandas>=2.0 pyarrow>=14 typeguard>=4 mypy-protobuf
cd mlops/feast_repo
PYTHONPATH=../.. feast apply
```

This registers the updated entity and feature view definitions and ensures the
registry (`data/registry.db`) reflects the QoS additions. Follow up with
`feast materialize` or `feast materialize-incremental` as needed to backfill the
online store.

## Validation coverage

Range enforcement for the new metrics is handled by the existing
`validate_feature_ranges` pipeline hook. Bounds have been declared in
`ml_service/app/config/features.yaml`, so any ingestion or prediction path that
loads these specs will now reject latency, throughput, or packet-loss values
outside their permitted ranges before they reach model code.
