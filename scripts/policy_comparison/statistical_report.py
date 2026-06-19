"""Statistical reporting for completed policy comparison runs.

This module reads existing offline replay or live experiment summaries. It does
not run scenarios, start Docker, call ML, or generate thesis results by itself.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
from scipy import stats  # type: ignore[import-untyped]


LOWER_IS_BETTER = {
    "handover_count",
    "total_handovers",
    "ping_pong_count",
    "pingpong_count",
    "low_quality_step_count",
    "low_quality_steps",
    "avg_decision_latency_ms",
    "decision_latency_ms",
    "qos_compliance_failed",
    "unnecessary_handover_count",
    "late_handover_proxy_count",
    "failed_handover_proxy_count",
    "rlf_proxy_count",
    "qos_violation_proxy_count",
    "load_balance_regression_count",
    "composite_cost",
    "complexity_sparse_composite_cost",
    "complexity_moderate_composite_cost",
    "complexity_high_composite_cost",
    "handovers_per_ue_minute",
    "ping_pongs_per_ue_minute",
    "qos_violations_per_ue_minute",
    "rlf_proxies_per_ue_minute",
    "sinr_outage_fraction",
    "handover_interruption_time_s",
    "poor_handover_target_sinr_count",
    "latency_budget_violation_count",
}
HIGHER_IS_BETTER = {
    "avg_dwell_time_s",
    "min_serving_rsrp_dbm",
    "avg_serving_rsrp_dbm",
    "avg_handover_target_rsrp_dbm",
    "min_serving_sinr_db",
    "avg_serving_sinr_db",
    "avg_handover_target_sinr_db",
    "qos_compliance_ok",
}


class StatisticalReportError(ValueError):
    """Raised when statistical reporting input is unsafe or incomplete."""


@dataclass(frozen=True)
class PolicyRunMetrics:
    """Metrics for one completed run and one evidence type."""

    path: str
    evidence_type: str
    scenario: str
    seed: int
    topology_hash: Optional[str]
    policy_metrics: Dict[str, Dict[str, float]]

    def pair_key(self) -> tuple[str, str, int, Optional[str]]:
        """Return the key used to pair policies within matched runs."""
        return (self.evidence_type, self.scenario, self.seed, self.topology_hash)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricPair:
    """One paired metric observation for a reference and candidate policy."""

    run_path: str
    evidence_type: str
    scenario: str
    seed: int
    topology_hash: Optional[str]
    reference_value: float
    candidate_value: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MetricComparison:
    """Paired statistical comparison for one metric and one evidence type."""

    metric_name: str
    evidence_type: str
    reference_policy: str
    candidate_policy: str
    n_pairs: int
    direction: str
    reference_mean: Optional[float]
    candidate_mean: Optional[float]
    mean_delta_candidate_minus_reference: Optional[float]
    mean_improvement: Optional[float]
    p_value_raw: Optional[float]
    p_value_corrected: Optional[float]
    is_significant: bool
    test_type: str
    cohens_dz: Optional[float]
    effect_size_interpretation: str
    ci_lower: Optional[float]
    ci_upper: Optional[float]
    pairs: List[MetricPair] = field(default_factory=list)
    warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["pairs"] = [pair.to_dict() for pair in self.pairs]
        return payload


@dataclass(frozen=True)
class PolicyStatisticalReport:
    """Full statistical report across evidence types and metrics."""

    reference_policy: str
    candidate_policy: str
    comparisons: Dict[str, List[MetricComparison]]
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference_policy": self.reference_policy,
            "candidate_policy": self.candidate_policy,
            "comparisons": {
                evidence_type: [
                    comparison.to_dict() for comparison in comparisons
                ]
                for evidence_type, comparisons in self.comparisons.items()
            },
            "warnings": self.warnings,
            "note": (
                "Offline and live evidence are reported separately. "
                "This report summarizes existing completed runs only."
            ),
        }


def load_run_metrics(path: Path) -> PolicyRunMetrics:
    """Load metrics from an offline replay or live experiment summary."""
    summary_path = _resolve_summary_path(path)
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise StatisticalReportError(f"summary must be a JSON object: {summary_path}")

    if "policy_results" in data:
        return _load_offline_replay_summary(summary_path, data)
    if "policy_metrics" in data:
        return _load_live_experiment_summary(summary_path, data)
    raise StatisticalReportError(
        f"unrecognized summary format: {summary_path}; expected policy_results "
        "or policy_metrics"
    )


def build_statistical_report(
    runs: Sequence[PolicyRunMetrics],
    *,
    reference_policy: str,
    candidate_policy: str,
    metrics: Optional[Sequence[str]] = None,
    evidence_type: str = "all",
    alpha: float = 0.05,
    bootstrap_iterations: int = 5000,
    seed: Optional[int] = None,
) -> PolicyStatisticalReport:
    """Build paired reports, keeping offline and live evidence separated."""
    if not runs:
        raise StatisticalReportError("at least one completed run summary is required")
    if reference_policy == candidate_policy:
        raise StatisticalReportError("reference and candidate policies must differ")

    selected_runs = [
        run for run in runs if evidence_type == "all" or run.evidence_type == evidence_type
    ]
    if not selected_runs:
        raise StatisticalReportError(f"no runs found for evidence type: {evidence_type}")

    by_evidence: Dict[str, List[PolicyRunMetrics]] = {}
    for run in selected_runs:
        by_evidence.setdefault(run.evidence_type, []).append(run)

    warnings: List[str] = []
    comparisons: Dict[str, List[MetricComparison]] = {}
    for current_evidence_type, evidence_runs in sorted(by_evidence.items()):
        metric_names = _select_metric_names(
            evidence_runs,
            reference_policy=reference_policy,
            candidate_policy=candidate_policy,
            metrics=metrics,
        )
        if not metric_names:
            warnings.append(
                f"{current_evidence_type}: no common numeric metrics for "
                f"{reference_policy} and {candidate_policy}"
            )
            comparisons[current_evidence_type] = []
            continue

        evidence_comparisons = [
            compare_metric(
                evidence_runs,
                metric_name=metric_name,
                reference_policy=reference_policy,
                candidate_policy=candidate_policy,
                evidence_type=current_evidence_type,
                n_comparisons=len(metric_names),
                alpha=alpha,
                bootstrap_iterations=bootstrap_iterations,
                seed=seed,
            )
            for metric_name in metric_names
        ]
        for comparison in evidence_comparisons:
            if comparison.warning:
                warnings.append(comparison.warning)
        comparisons[current_evidence_type] = evidence_comparisons

    return PolicyStatisticalReport(
        reference_policy=reference_policy,
        candidate_policy=candidate_policy,
        comparisons=comparisons,
        warnings=warnings,
    )


def compare_metric(
    runs: Sequence[PolicyRunMetrics],
    *,
    metric_name: str,
    reference_policy: str,
    candidate_policy: str,
    evidence_type: str,
    n_comparisons: int,
    alpha: float = 0.05,
    bootstrap_iterations: int = 5000,
    seed: Optional[int] = None,
) -> MetricComparison:
    """Compare one metric for matched policy runs."""
    pairs = collect_metric_pairs(
        runs,
        metric_name=metric_name,
        reference_policy=reference_policy,
        candidate_policy=candidate_policy,
        evidence_type=evidence_type,
    )
    direction = metric_direction(metric_name)
    if len(pairs) < 2:
        return MetricComparison(
            metric_name=metric_name,
            evidence_type=evidence_type,
            reference_policy=reference_policy,
            candidate_policy=candidate_policy,
            n_pairs=len(pairs),
            direction=direction,
            reference_mean=None,
            candidate_mean=None,
            mean_delta_candidate_minus_reference=None,
            mean_improvement=None,
            p_value_raw=None,
            p_value_corrected=None,
            is_significant=False,
            test_type="insufficient_pairs",
            cohens_dz=None,
            effect_size_interpretation="not_applicable",
            ci_lower=None,
            ci_upper=None,
            pairs=pairs,
            warning=(
                f"{evidence_type}/{metric_name}: need at least 2 paired runs, "
                f"got {len(pairs)}"
            ),
        )

    reference = np.array([pair.reference_value for pair in pairs], dtype=float)
    candidate = np.array([pair.candidate_value for pair in pairs], dtype=float)
    deltas = candidate - reference
    improvements = _improvement_values(reference, candidate, direction)

    p_value, test_type = _paired_test(reference, candidate)
    corrected = min(float(p_value) * max(1, n_comparisons), 1.0)
    effect, effect_label = _cohens_dz(improvements)
    ci_lower, ci_upper = _bootstrap_ci(
        improvements,
        iterations=bootstrap_iterations,
        seed=seed,
    )

    return MetricComparison(
        metric_name=metric_name,
        evidence_type=evidence_type,
        reference_policy=reference_policy,
        candidate_policy=candidate_policy,
        n_pairs=len(pairs),
        direction=direction,
        reference_mean=float(np.mean(reference)),
        candidate_mean=float(np.mean(candidate)),
        mean_delta_candidate_minus_reference=float(np.mean(deltas)),
        mean_improvement=float(np.mean(improvements)),
        p_value_raw=float(p_value),
        p_value_corrected=corrected,
        is_significant=corrected < alpha,
        test_type=test_type,
        cohens_dz=effect,
        effect_size_interpretation=effect_label,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        pairs=pairs,
    )


def collect_metric_pairs(
    runs: Sequence[PolicyRunMetrics],
    *,
    metric_name: str,
    reference_policy: str,
    candidate_policy: str,
    evidence_type: str,
) -> List[MetricPair]:
    """Collect matched observations for one metric."""
    pairs: List[MetricPair] = []
    seen_keys: set[tuple[str, str, int, Optional[str]]] = set()
    for run in sorted(runs, key=lambda item: item.pair_key()):
        if run.evidence_type != evidence_type:
            continue
        key = run.pair_key()
        if key in seen_keys:
            raise StatisticalReportError(
                "duplicate run key for paired comparison: "
                + ", ".join(str(part) for part in key)
            )
        seen_keys.add(key)

        reference_metrics = run.policy_metrics.get(reference_policy)
        candidate_metrics = run.policy_metrics.get(candidate_policy)
        if reference_metrics is None or candidate_metrics is None:
            continue
        if metric_name not in reference_metrics or metric_name not in candidate_metrics:
            continue
        pairs.append(
            MetricPair(
                run_path=run.path,
                evidence_type=run.evidence_type,
                scenario=run.scenario,
                seed=run.seed,
                topology_hash=run.topology_hash,
                reference_value=reference_metrics[metric_name],
                candidate_value=candidate_metrics[metric_name],
            )
        )
    return pairs


def metric_direction(metric_name: str) -> str:
    """Return the default direction used for improvement interpretation."""
    if metric_name in LOWER_IS_BETTER:
        return "lower_is_better"
    if metric_name in HIGHER_IS_BETTER:
        return "higher_is_better"
    return "neutral_delta"


def markdown_report(report: PolicyStatisticalReport) -> str:
    """Render a compact Markdown report for docs/artifacts."""
    lines = [
        "# Policy Statistical Report",
        "",
        f"Reference policy: `{report.reference_policy}`",
        f"Candidate policy: `{report.candidate_policy}`",
        "",
        "Offline and live evidence are intentionally reported separately.",
        "Positive mean improvement follows the metric direction when known; "
        "neutral metrics report candidate-reference delta.",
    ]
    if report.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in report.warnings)

    for evidence_type, comparisons in sorted(report.comparisons.items()):
        lines.extend(["", f"## {evidence_type}"])
        if not comparisons:
            lines.append("No comparable metrics.")
            continue
        lines.append(
            "| Metric | n | Direction | Reference mean | Candidate mean | "
            "Mean improvement | 95% CI | p corrected | Effect |"
        )
        lines.append("|---|---:|---|---:|---:|---:|---|---:|---|")
        for item in comparisons:
            ci = (
                "n/a"
                if item.ci_lower is None or item.ci_upper is None
                else f"[{item.ci_lower:.3f}, {item.ci_upper:.3f}]"
            )
            corrected = "n/a" if item.p_value_corrected is None else f"{item.p_value_corrected:.4f}"
            reference_mean = "n/a" if item.reference_mean is None else f"{item.reference_mean:.3f}"
            candidate_mean = "n/a" if item.candidate_mean is None else f"{item.candidate_mean:.3f}"
            improvement = "n/a" if item.mean_improvement is None else f"{item.mean_improvement:.3f}"
            effect = (
                "n/a"
                if item.cohens_dz is None
                else f"{item.cohens_dz:.3f} ({item.effect_size_interpretation})"
            )
            lines.append(
                f"| {item.metric_name} | {item.n_pairs} | {item.direction} | "
                f"{reference_mean} | {candidate_mean} | {improvement} | "
                f"{ci} | {corrected} | {effect} |"
            )
    return "\n".join(lines) + "\n"


def write_statistical_report(
    report: PolicyStatisticalReport,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write JSON and Markdown report artifacts to a fresh output directory."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise StatisticalReportError(
            f"output directory already exists and is not empty: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "policy_statistical_report.json"
    markdown_path = output_dir / "policy_statistical_report.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    markdown_path.write_text(markdown_report(report), encoding="utf-8")
    return json_path, markdown_path


def _resolve_summary_path(path: Path) -> Path:
    if path.is_dir():
        offline = path / "summary.json"
        live = path / "experiment_summary.json"
        if offline.is_file() and live.is_file():
            raise StatisticalReportError(
                f"directory contains both summary types; pass one file explicitly: {path}"
            )
        if offline.is_file():
            return offline
        if live.is_file():
            return live
        raise StatisticalReportError(
            f"directory does not contain summary.json or experiment_summary.json: {path}"
        )
    if not path.is_file():
        raise StatisticalReportError(f"summary path does not exist: {path}")
    return path


def _load_offline_replay_summary(
    path: Path,
    data: Mapping[str, Any],
) -> PolicyRunMetrics:
    scenario = str(data["scenario"])
    seed = int(data["seed"])
    topology_hash = (
        None if data.get("topology_hash") is None else str(data["topology_hash"])
    )
    policy_results = data.get("policy_results")
    if not isinstance(policy_results, Mapping):
        raise StatisticalReportError(f"policy_results must be a mapping: {path}")
    return PolicyRunMetrics(
        path=str(path),
        evidence_type="offline_replay",
        scenario=scenario,
        seed=seed,
        topology_hash=topology_hash,
        policy_metrics={
            str(policy): _numeric_mapping((payload or {}).get("summary") or {})
            for policy, payload in policy_results.items()
            if isinstance(payload, Mapping)
        },
    )


def _load_live_experiment_summary(
    path: Path,
    data: Mapping[str, Any],
) -> PolicyRunMetrics:
    experiment = data.get("experiment")
    if not isinstance(experiment, Mapping):
        raise StatisticalReportError(f"experiment must be a mapping: {path}")
    policy_metrics = data.get("policy_metrics")
    if not isinstance(policy_metrics, Mapping):
        raise StatisticalReportError(f"policy_metrics must be a mapping: {path}")
    return PolicyRunMetrics(
        path=str(path),
        evidence_type="live_experiment",
        scenario=str(experiment["scenario"]),
        seed=int(experiment.get("seed", 0)),
        topology_hash=(
            None
            if experiment.get("topology_hash") is None
            else str(experiment["topology_hash"])
        ),
        policy_metrics={
            str(policy): _numeric_mapping(metrics)
            for policy, metrics in policy_metrics.items()
            if isinstance(metrics, Mapping)
        },
    )


def _numeric_mapping(payload: Mapping[str, Any]) -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            metrics[str(key)] = float(value)
    return metrics


def _select_metric_names(
    runs: Sequence[PolicyRunMetrics],
    *,
    reference_policy: str,
    candidate_policy: str,
    metrics: Optional[Sequence[str]],
) -> List[str]:
    if metrics:
        return sorted(set(metrics))
    common: Optional[set[str]] = None
    for run in runs:
        reference = run.policy_metrics.get(reference_policy)
        candidate = run.policy_metrics.get(candidate_policy)
        if reference is None or candidate is None:
            continue
        current = set(reference).intersection(candidate)
        common = current if common is None else common.intersection(current)
    return sorted(common or set())


def _paired_test(reference: np.ndarray, candidate: np.ndarray) -> tuple[float, str]:
    differences = candidate - reference
    if len(differences) >= 2 and np.allclose(differences, differences[0]):
        if float(differences[0]) == 0.0:
            return 1.0, "paired_t_degenerate"
        return 0.0, "paired_t_degenerate"
    if len(differences) >= 3:
        try:
            _stat, normality_p = stats.shapiro(differences)
            if normality_p <= 0.05:
                stat, p_value = stats.wilcoxon(reference, candidate)
                return float(p_value), "wilcoxon"
        except ValueError:
            pass
    stat, p_value = stats.ttest_rel(reference, candidate)
    if math.isnan(float(p_value)):
        return 1.0, "paired_t_degenerate"
    return float(p_value), "paired_t"


def _improvement_values(
    reference: np.ndarray,
    candidate: np.ndarray,
    direction: str,
) -> np.ndarray:
    if direction == "lower_is_better":
        return reference - candidate
    if direction == "higher_is_better":
        return candidate - reference
    return candidate - reference


def _cohens_dz(values: np.ndarray) -> tuple[float, str]:
    if len(values) < 2:
        return 0.0, "not_applicable"
    std = float(np.std(values, ddof=1))
    mean = float(np.mean(values))
    if std == 0.0:
        if mean == 0.0:
            return 0.0, "negligible"
        return math.inf, "very large"
    effect = mean / std
    magnitude = abs(effect)
    if magnitude < 0.2:
        label = "negligible"
    elif magnitude < 0.5:
        label = "small"
    elif magnitude < 0.8:
        label = "medium"
    elif magnitude < 1.2:
        label = "large"
    else:
        label = "very large"
    return float(effect), label


def _bootstrap_ci(
    values: np.ndarray,
    *,
    iterations: int,
    seed: Optional[int],
) -> tuple[float, float]:
    if len(values) == 0:
        return 0.0, 0.0
    if iterations <= 0:
        raise StatisticalReportError("bootstrap_iterations must be positive")
    rng = np.random.RandomState(seed)
    samples = []
    for _ in range(iterations):
        indices = rng.choice(len(values), size=len(values), replace=True)
        samples.append(float(np.mean(values[indices])))
    return (
        float(np.percentile(samples, 2.5)),
        float(np.percentile(samples, 97.5)),
    )
