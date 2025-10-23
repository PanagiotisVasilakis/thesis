# Synthetic QoS Dataset Reference

This document captures the schema, probability distributions, and operational rationale behind `scripts/data_generation/synthetic_generator.py`. The generator underpins the thesis experiments by emitting reproducible Quality of Service (QoS) request records across enhanced Mobile Broadband (eMBB), Ultra-Reliable Low-Latency Communications (URLLC), massive Machine-Type Communications (mMTC), and a general-purpose fallback profile.

## Schema overview

All CSV and JSON payloads expose the same ordered fields:

| Field | Type | Notes |
| --- | --- | --- |
| `request_id` | string | Deterministic identifier in the form `req_000000`, enabling repeatable joins with labels and simulation traces. |
| `service_type` | string | Traffic class key (`embb`, `urllc`, `mmtc`, `default`). |
| `latency_ms` | float | Round-trip latency sampled in milliseconds. |
| `reliability_pct` | float | Delivery success probability expressed as a percentage (e.g., `99.995`). |
| `throughput_mbps` | float | User-plane throughput in megabits per second. |
| `priority` | integer | Scheduling priority bucket aligned with 5QI-inspired service differentiation. |

Triangular distributions are used for the continuous metrics because they maintain explicit minimum and maximum bounds while still biasing samples towards the documented operating points. This mirrors industry practice when precise empirical distributions are unavailable but planning ranges are published.

## Service profile distributions

The generator encodes the following bounded envelopes. Values reflect the minimum, most-likely (mode), and maximum parameters fed into Python's `random.triangular` function alongside integer ranges for the discrete `priority` field.

| Service | Latency ms (min/mode/max) | Reliability % (min/mode/max) | Throughput Mbps (min/mode/max) | Priority range |
| --- | --- | --- | --- | --- |
| URLLC | 1.0 / 2.0 / 10.0 | 99.95 / 99.995 / 99.999 | 0.5 / 1.5 / 5.0 | 9–10 |
| eMBB | 20.0 / 45.0 / 80.0 | 98.5 / 99.4 / 99.9 | 50.0 / 200.0 / 350.0 | 6–9 |
| mMTC | 100.0 / 600.0 / 1000.0 | 94.0 / 96.0 / 98.5 | 0.01 / 0.2 / 1.0 | 2–4 |
| default | 30.0 / 80.0 / 200.0 | 95.0 / 97.5 / 99.0 | 5.0 / 25.0 / 80.0 | 4–6 |

### Rationale and trade-offs

- **URLLC** targets sub-10 ms latency with five-nines reliability to emulate mission-critical control loops. The upper bound leaves space for realistic RAN congestion without violating the 3GPP TS 22.261 requirements for factory automation and remote surgery use cases.[^ts22261]
- **eMBB** emphasises sustained throughput with moderate latency. The selected throughput range aligns with the eMBB peak and user-experienced throughput expectations in 3GPP TR 38.913 while the reliability mode reflects mobile broadband service-level agreements for premium plans.[^tr38913]
- **mMTC** captures the high-device-count, low-throughput profile described in 3GPP TS 22.104. Latency tolerances are relaxed while the lower reliability bound acknowledges that battery-powered sensors often trade availability for energy efficiency.[^ts22104]
- **default** extends the dataset to cover mixed workloads and regression scenarios. Its mid-range values match the conversational and non-GBR classes listed around 5QI 6–8 in 3GPP TS 23.501 Annex E, providing a realistic fallback when traffic does not map cleanly to the headline slices.[^ts23501]

The `priority` ranges translate the Annex E 5QI groupings into coarse buckets so downstream schedulers can differentiate URLLC-style bearers (priority 9–10) from delay-tolerant telemetry (priority 2–4) without replicating the entire 5QI catalogue.

## Service mix presets and CLI overrides

`SERVICE_MIX_PROFILES` defines baseline traffic compositions used in the experiments:

| Profile | URLLC | eMBB | mMTC | default | Notes |
| --- | --- | --- | --- | --- | --- |
| `balanced` | 0.25 | 0.35 | 0.25 | 0.15 | Evenly exercises each model during benchmarking. |
| `embb-heavy` | 0.10 | 0.60 | 0.15 | 0.15 | Bias towards throughput-driven workloads. |
| `urllc-heavy` | 0.60 | 0.20 | 0.10 | 0.10 | Stress-tests low-latency scheduling policies. |
| `mmtc-heavy` | 0.10 | 0.20 | 0.60 | 0.10 | Highlights control-plane scalability. |
| `uniform` | 0.25 | 0.25 | 0.25 | 0.25 | Simplifies analytical proofs and baseline comparisons. |

CLI options `--embb-weight`, `--urllc-weight`, and `--mmtc-weight` accept raw (non-normalised) ratios for tailored scenarios. When supplied, the script merges the overrides with the selected profile, validates that all weights are non-negative, and renormalises the mix. Leaving all overrides at zero implicitly preserves the preset—useful when exploring the sensitivity of a single traffic slice without redefining the entire vector.

## Testing and reproducibility workflow

1. Install dependencies with `pip install -r requirements.txt`.
2. Generate datasets using the desired preset and random seed; record those parameters alongside the output path for auditability.
3. Run `pytest tests/data_generation/test_synthetic_generator.py` to verify:
   - Field presence and bounds across every profile.
   - Statistical adherence to the configured weight distributions via chi-squared tests.
   - Triangular mean convergence for latency, reliability, throughput, and priority values.
   - CLI validation paths for custom weight overrides, including negative-weight rejection and zero-weight fallbacks.
4. Store the resulting CSV/JSON artefacts with metadata (`seed`, mix profile, override weights) in the thesis appendix so reviewers can replicate the experiments byte-for-byte.

## References

[^ts22261]: 3GPP TS 22.261, *Service requirements for the 5G system (5GS); Stage 1*, v18.0.0, 2024.
[^tr38913]: 3GPP TR 38.913, *Study on Scenarios and Requirements for Next Generation Access Technologies*, v16.0.0, 2020.
[^ts22104]: 3GPP TS 22.104, *Service requirements for cyber-physical control applications in vertical domains*, v18.0.0, 2024.
[^ts23501]: 3GPP TS 23.501, *System Architecture for the 5G System (5GS)*, v18.4.0, 2024.
