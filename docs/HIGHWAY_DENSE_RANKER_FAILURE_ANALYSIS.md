# Highway Dense Ranker Failure Analysis

This note freezes `thesis_results/highway_dense_ranker_20260612_023651/` as diagnostic evidence, not thesis-final proof.

The dense highway trace generation and validation pipeline worked:

- Calibration seed `51` and held-out seeds `61-65` were captured from policy-free `trace_capture` mode.
- Trace-complexity preflight passed for thresholds `3` and `4`.
- Replay output validation reported no validation issues.
- The strict offline threshold sweep completed and produced `pass=false`.

The failure is a real controller/model failure:

- Threshold `3` failed with mean high-complexity improvement `-2.5075`.
- Threshold `4` failed with mean high-complexity improvement `-2.4405`.
- Threshold `5` had no high-complexity observations in this topology.
- On seed `61`, tuned A3 produced `600` handovers, ML everywhere produced `866`, and adaptive ML+A3 produced `1370`.

Main diagnosis:

- The ranker selected handover targets too often.
- The adaptive controller alternated between ML high-complexity decisions and sparse A3 decisions.
- ML handovers changed serving-cell state in a way that caused extra subsequent sparse-region A3 handovers.
- The old ranker validation had good RMSE but poor target-selection behavior, so RMSE alone was not a defensible promotion signal.

Live validation was correctly blocked. The current ranker artifact must not be promoted to the runtime ML service. The next valid step is offline model recovery: stay-aware labels, conservative ranker thresholds, replay-state features, dwell guards, A3 re-entry guards, and held-out replay before any live run.

## Recovery Attempt: `highway_dense_ranker_recovery_20260612_102052`

The recovery implementation added stay-aware labels, state-aware replay features, conservative ranker margins, an A3 re-entry guard, replay tuning on calibration seed `51`, and decision diagnostics.

Calibration replay tuning passed on seed `51` with:

- complexity threshold `4`
- ranker minimum margin `30.0`
- ML dwell guard `0.0s`
- A3 re-entry guard `3.0 dB`
- calibration high-complexity improvement `15.43%`

Held-out replay on seeds `61-65` still failed the strict gate:

- Threshold `3`: mean high-complexity improvement `-0.6225`.
- Threshold `4`: mean high-complexity improvement `-0.6126`.
- Threshold `5`: no high-complexity observations.
- Threshold `4` validation issues: none.
- Threshold `4` ping-pong increased to a mean of `67.2` versus tuned A3 mean `6.8`.
- Threshold `4` adaptive ML+A3 did not beat ML-everywhere or tuned-A3-everywhere overall.

Decision diagnostics for threshold `4` show the main remaining failure:

- Adaptive ML+A3 still alternates between `ml_high_complexity` and `a3_complexity_gate`.
- Sparse handovers after recent ML handovers remain high: `151-181` per held-out seed.
- ML-everywhere is sometimes lower cost than adaptive routing, which means the sparse A3 re-entry behavior is still damaging the mixed controller.

This recovery run is diagnostic only. Live ranker promotion remains blocked until a future held-out offline sweep passes the strict gate.
