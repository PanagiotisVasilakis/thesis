# QoS Validation Inventory

This note summarises the components that validate Quality-of-Service (QoS) payloads
and feature ranges across the ingestion and prediction stacks. Use it when adding
new safeguards or tracing how existing checks flow through the pipeline.

## Validation modules and responsibilities

### `mlops/data_pipeline/nef_collector.py`
- `QoSRequirements.from_payload` normalises NEF payload variants, coerces
  numeric thresholds, and enforces the presence of QoS fields when
  `required_thresholds` are provided. Non-dict payloads or missing metrics raise
  `QoSValidationError` to keep downstream collectors from persisting bad
  records.
- `NEFQoSCollector.collect_for_ue` wraps the NEF client call, surfaces
  validation errors via logging, and drops records that fail schema or range
  checks before converting them into timestamped dictionaries ready for storage
  or model training.

### `ml_service/app/data/nef_collector.py`
- `_normalize_qos_payload` mirrors the NEF validation logic used in offline
  pipelines, coercing mixed-case fields and numeric thresholds before updating
  running collectors. It guards against malformed payloads during live data
  collection.
- `NEFDataCollector.collect_training_data` relies on shared validators such as
  `validate_ue_sample_data` to enforce UE IDs, position bounds, and NEF response
  sanity while fetching labelled samples for training.

### `ml_service/app/utils/common_validators.py`
- `NumericValidator`, `StringValidator`, and `GeospatialValidator` provide
  reusable min/max, positivity, and formatting checks used throughout the
  service.
- `UEDataValidator`, `DataCollectionValidator`, and helpers like
  `validate_ue_sample_data` compose the primitive checks into end-to-end
  validation steps for ingestion routines.

### `ml_service/app/config/feature_specs.py`
- `_load_specs` parses `features.yaml`, capturing per-feature `min`/`max` bounds
  and categorical allow-lists.
- `validate_feature_ranges` enforces those specs against feature dictionaries,
  raising descriptive errors when metrics sit outside their permitted range.

### `ml_service/app/models/base_model_mixin.py` and `app/models/antenna_selector.py`
- Both call `validate_feature_ranges` prior to dataset creation or prediction,
  ensuring every sample complies with the configuration-driven QoS envelopes
  before it reaches model code.

### API- and schema-level guards
- Pydantic schemas such as `CollectDataRequest` and
  `PredictionRequestWithQoS` ensure request payloads respect field types and
  value ranges before hitting the collectors or prediction service.
- Flask route decorators (`validate_json_input`, `validate_request_size`, etc.)
  automatically apply these schemas during ingestion via `/collect-data` and
  feedback endpoints.

## Wiring through ingestion and deployment

1. **Inbound NEF collection (offline)** – The `NEFQoSCollector` class pulls raw
   QoS documents, transforms them with `QoSRequirements.from_payload`, and only
   forwards validated, timestamped records into storage or feature generation.
2. **Live training data collection** – REST handlers call `CollectDataRequest`
   for early range enforcement, then `NEFDataCollector.collect_training_data`
   for asynchronous NEF polling. Each UE sample flows through
   `validate_ue_sample_data`, `_normalize_qos_payload`, and feature range checks
   before being persisted.
3. **Model training and prediction** – `BaseModelMixin.build_dataset` and
   `AntennaSelector.predict` both gate model access with `validate_feature_ranges`.
   When QoS metrics enter the feature dictionary, they must already respect the
   bounds declared in `features.yaml` or they raise immediately.

## Patterns for extending QoS range validation

1. **Declare the range** – Add the metric to `features.yaml` with `min`/`max`
   (or `categories` for categorical fields). `_load_specs` automatically exposes
   the bound through `FEATURE_SPECS` for every consumer.
2. **Normalise upstream payloads** – Extend the key map inside
   `QoSRequirements.from_payload` (and `_normalize_qos_payload` if live
   collectors need the same field) so the new metric is pulled from NEF payloads
   regardless of naming conventions.
3. **Require its presence where critical** – Pass the metric name into the
   `required_thresholds` argument when constructing `NEFQoSCollector` or related
   services to fail fast if NEF omits it.
4. **Cover API contracts** – Update the relevant Pydantic schema (e.g.
   `PredictionRequestWithQoS`) with field bounds so external clients receive
   immediate validation feedback.
5. **Add regression tests** – Mirror existing tests in
   `tests/mlops/test_nef_collector.py` or schema suites to lock the behaviour and
   prevent regressions during ingestion or deployment changes.

Following this flow keeps QoS range constraints consistent from NEF ingestion,
through data preparation, and into online prediction paths.
