"""Validation for completed policy comparison outputs.

This module inspects existing offline replay or live experiment artifacts. It
does not start services, run scenarios, or generate experiment results.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

from .schemas import PolicyDecisionRecord
from .trace_io import read_decisions_jsonl


Severity = Literal["critical", "high", "medium", "low"]
SUPPORTED_POLICIES = {
    "ml",
    "ml_policy",
    "a3",
    "hybrid",
    "fixed_a3_baseline",
    "tuned_a3_baseline",
    "strongest_rsrp_baseline",
    "strongest_sinr_baseline",
    "strongest_rsrq_baseline",
    "load_aware_a3_baseline",
    "velocity_adaptive_a3_baseline",
    "complexity_aware_ml_a3",
}
BLOCKING_SEVERITIES = {"critical", "high"}
LIVE_ML_POLICIES = {"ml", "complexity_aware_ml_a3"}
LIVE_ML_LOG_POLICIES = {"ml", "hybrid", "complexity_aware_ml_a3"}
LIVE_REQUIRED_POLICY_METRICS = ("total_handovers", "skipped_handovers")
LIVE_REQUIRED_ML_METRICS = (
    "avg_confidence",
    "pingpong_suppressions",
    "qos_compliance_ok",
    "qos_compliance_failed",
)


@dataclass(frozen=True)
class OutputValidationIssue:
    """One concrete validation issue found in a completed output."""

    severity: Severity
    code: str
    message: str
    path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OutputValidationReport:
    """Validation result for one offline or live comparison output."""

    path: str
    artifact_type: str
    ok: bool
    issues: List[OutputValidationIssue]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "artifact_type": self.artifact_type,
            "ok": self.ok,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_comparison_output(
    path: Path,
    *,
    expected_policies: Optional[Sequence[str]] = None,
    require_neighbour_measurements: bool = True,
) -> OutputValidationReport:
    """Validate one completed offline replay or live experiment output."""
    root, artifact_type, issues = _resolve_output_root(path)
    if artifact_type == "offline_replay":
        _validate_offline_output(
            root,
            issues,
            expected_policies=expected_policies,
            require_neighbour_measurements=require_neighbour_measurements,
        )
    elif artifact_type == "live_experiment":
        _validate_live_output(
            root,
            issues,
            expected_policies=expected_policies,
        )

    ok = not any(issue.severity in BLOCKING_SEVERITIES for issue in issues)
    return OutputValidationReport(
        path=str(root),
        artifact_type=artifact_type,
        ok=ok,
        issues=issues,
    )


def write_validation_report(report: OutputValidationReport, output_path: Path) -> None:
    """Write the validation report as JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def validation_summary_lines(report: OutputValidationReport) -> List[str]:
    """Return a compact pass/fail checklist for CLI output."""
    status = "PASS" if report.ok else "FAIL"
    lines = [
        f"{status}: {report.artifact_type} output validation for {report.path}",
    ]
    if not report.issues:
        lines.append("- No validation issues found.")
        return lines

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    for issue in sorted(
        report.issues,
        key=lambda item: (severity_order[item.severity], item.code, item.path or ""),
    ):
        location = f" ({issue.path})" if issue.path else ""
        lines.append(
            f"- [{issue.severity}] {issue.code}: {issue.message}{location}"
        )
    return lines


def _resolve_output_root(path: Path) -> tuple[Path, str, List[OutputValidationIssue]]:
    issues: List[OutputValidationIssue] = []
    if path.is_file():
        if path.name == "summary.json":
            return path.parent, "offline_replay", issues
        if path.name == "experiment_summary.json":
            return path.parent, "live_experiment", issues
        return path.parent, "unknown", [
            OutputValidationIssue(
                "critical",
                "unknown_summary_file",
                "expected summary.json or experiment_summary.json",
                str(path),
            )
        ]

    if not path.exists():
        return path, "unknown", [
            OutputValidationIssue(
                "critical",
                "missing_output_path",
                "output path does not exist",
                str(path),
            )
        ]
    if not path.is_dir():
        return path, "unknown", [
            OutputValidationIssue(
                "critical",
                "invalid_output_path",
                "output path is neither a file nor a directory",
                str(path),
            )
        ]

    offline = path / "summary.json"
    live = path / "experiment_summary.json"
    if offline.is_file() and live.is_file():
        return path, "unknown", [
            OutputValidationIssue(
                "critical",
                "ambiguous_output_type",
                "directory contains both offline and live summary files",
                str(path),
            )
        ]
    if offline.is_file():
        return path, "offline_replay", issues
    if live.is_file():
        return path, "live_experiment", issues
    return path, "unknown", [
        OutputValidationIssue(
            "critical",
            "missing_summary",
            "directory must contain summary.json or experiment_summary.json",
            str(path),
        )
    ]


def _validate_offline_output(
    root: Path,
    issues: List[OutputValidationIssue],
    *,
    expected_policies: Optional[Sequence[str]],
    require_neighbour_measurements: bool,
) -> None:
    summary_path = root / "summary.json"
    data = _read_json_object(summary_path, issues)
    if data is None:
        return

    _require_non_empty_string(data, "scenario", summary_path, issues)
    _require_int(data, "seed", summary_path, issues)
    if not data.get("topology_hash"):
        _add_issue(
            issues,
            "high",
            "missing_topology_hash",
            "offline summary is missing topology_hash",
            summary_path,
        )

    policy_results = data.get("policy_results")
    if not isinstance(policy_results, Mapping) or not policy_results:
        _add_issue(
            issues,
            "critical",
            "missing_policy_results",
            "offline summary must include non-empty policy_results",
            summary_path,
        )
        return

    policy_names = sorted(str(policy) for policy in policy_results)
    _validate_policy_names(policy_names, expected_policies, issues, summary_path)
    if {"tuned_a3_baseline", "complexity_aware_ml_a3"}.intersection(policy_names):
        _validate_offline_tuned_a3_artifact(root, issues)

    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        _add_issue(
            issues,
            "high",
            "missing_manifest",
            "offline output is missing reproducibility manifest.json",
            manifest_path,
        )

    for policy_name, payload in policy_results.items():
        if not isinstance(payload, Mapping):
            _add_issue(
                issues,
                "high",
                "invalid_policy_result",
                f"policy result for {policy_name} must be a JSON object",
                summary_path,
            )
            continue
        summary = payload.get("summary")
        if not isinstance(summary, Mapping):
            _add_issue(
                issues,
                "high",
                "missing_policy_summary",
                f"policy {policy_name} is missing summary metrics",
                summary_path,
            )
        elif not _has_numeric_metric(summary):
            _add_issue(
                issues,
                "high",
                "empty_policy_summary",
                f"policy {policy_name} summary has no numeric metrics",
                summary_path,
            )

        decisions = _load_offline_decisions(root, str(policy_name), payload, issues)
        if decisions is None:
            continue
        _validate_decisions(
            decisions,
            policy_name=str(policy_name),
            issues=issues,
            source_path=root,
            require_neighbour_measurements=require_neighbour_measurements,
        )


def _validate_live_output(
    root: Path,
    issues: List[OutputValidationIssue],
    *,
    expected_policies: Optional[Sequence[str]],
) -> None:
    summary_path = root / "experiment_summary.json"
    data = _read_json_object(summary_path, issues)
    if data is None:
        return

    experiment = data.get("experiment")
    if not isinstance(experiment, Mapping):
        _add_issue(
            issues,
            "critical",
            "missing_experiment_metadata",
            "live summary must include experiment metadata",
            summary_path,
        )
        return

    _require_non_empty_string(experiment, "scenario", summary_path, issues)
    _require_int(experiment, "seed", summary_path, issues)
    if not experiment.get("topology_hash"):
        _add_issue(
            issues,
            "high",
            "missing_topology_hash",
            "live summary is missing topology_hash",
            summary_path,
        )

    metrics = data.get("policy_metrics")
    if not isinstance(metrics, Mapping) or not metrics:
        _add_issue(
            issues,
            "critical",
            "missing_policy_metrics",
            "live summary must include non-empty policy_metrics",
            summary_path,
        )
        return

    _validate_live_metric_warnings(data.get("policy_metric_warnings"), issues, summary_path)

    plan_entries = _load_live_plan(root, issues)
    plan_policies = [
        str(entry.get("policy"))
        for entry in plan_entries
        if isinstance(entry, Mapping) and entry.get("policy")
    ]
    experiment_policies = [
        str(policy)
        for policy in experiment.get("policies", [])
        if str(policy)
    ] if isinstance(experiment.get("policies"), list) else []
    metric_policies = sorted(str(policy) for policy in metrics)
    policy_names = sorted(
        set(experiment_policies).union(plan_policies).union(metric_policies)
    )
    _validate_policy_names(policy_names, expected_policies, issues, summary_path)

    for policy_name in policy_names:
        if policy_name not in metrics:
            _add_issue(
                issues,
                "high",
                "missing_policy_metric_entry",
                f"live summary is missing policy_metrics for {policy_name}",
                summary_path,
            )
            continue
        policy_metrics = metrics.get(policy_name)
        if not isinstance(policy_metrics, Mapping) or not _has_numeric_metric(policy_metrics):
            _add_issue(
                issues,
                "high",
                "empty_policy_metrics",
                f"policy {policy_name} has no numeric live metrics",
                summary_path,
            )
            continue
        _validate_live_required_metrics(
            policy_name,
            policy_metrics,
            issues,
            summary_path,
        )
        if policy_name in LIVE_ML_POLICIES:
            _validate_live_ml_qos_metrics(policy_metrics, issues, summary_path)

    if plan_entries:
        _validate_live_plan_entries(plan_entries, issues, root / "live_experiment_plan.json")

    _validate_live_topologies(root, policy_names, issues)
    _validate_live_logs(root, policy_names, issues)


def _load_offline_decisions(
    root: Path,
    policy_name: str,
    payload: Mapping[str, Any],
    issues: List[OutputValidationIssue],
) -> Optional[List[PolicyDecisionRecord]]:
    inline_decisions = payload.get("decisions")
    if isinstance(inline_decisions, list) and inline_decisions:
        try:
            return [PolicyDecisionRecord.from_dict(item) for item in inline_decisions]
        except Exception as exc:  # noqa: BLE001 - include policy context
            _add_issue(
                issues,
                "critical",
                "invalid_inline_decision",
                f"invalid inline decision for {policy_name}: {exc}",
                root / "summary.json",
            )
            return None

    decision_path = root / "decisions" / f"{policy_name}.jsonl"
    if not decision_path.is_file():
        _add_issue(
            issues,
            "high",
            "missing_decision_log",
            f"missing decision log for policy {policy_name}",
            decision_path,
        )
        return None
    if decision_path.stat().st_size == 0:
        _add_issue(
            issues,
            "high",
            "empty_decision_log",
            f"decision log is empty for policy {policy_name}",
            decision_path,
        )
        return None
    try:
        decisions = read_decisions_jsonl(decision_path)
    except Exception as exc:  # noqa: BLE001 - include file context
        _add_issue(
            issues,
            "critical",
            "invalid_decision_log",
            f"invalid decision log for {policy_name}: {exc}",
            decision_path,
        )
        return None
    if not decisions:
        _add_issue(
            issues,
            "high",
            "empty_decision_log",
            f"decision log has no records for policy {policy_name}",
            decision_path,
        )
        return None
    return decisions


def _validate_decisions(
    decisions: Sequence[PolicyDecisionRecord],
    *,
    policy_name: str,
    issues: List[OutputValidationIssue],
    source_path: Path,
    require_neighbour_measurements: bool,
) -> None:
    for index, decision in enumerate(decisions):
        if decision.policy_name != policy_name:
            _add_issue(
                issues,
                "high",
                "decision_policy_mismatch",
                f"decision {index} policy_name={decision.policy_name!r} "
                f"does not match output policy {policy_name!r}",
                source_path,
            )
        if (
            require_neighbour_measurements
            and not decision.neighbour_measurements_considered
        ):
            _add_issue(
                issues,
                "high",
                "missing_decision_measurements",
                f"decision {index} for policy {policy_name} has no neighbour measurements",
                source_path,
            )
            break
        if (
            decision.decision_type == "handover"
            and decision.selected_target_cell not in decision.neighbour_measurements_considered
        ):
            _add_issue(
                issues,
                "high",
                "invalid_selected_target",
                f"decision {index} for policy {policy_name} selected a target "
                "that was not a visible neighbour",
                source_path,
            )
            break
        if policy_name in {"fixed_a3_baseline", "tuned_a3_baseline"}:
            if decision.confidence is not None:
                _add_issue(
                    issues,
                    "high",
                    "fake_a3_confidence",
                    f"A3 policy {policy_name} must not emit ML-like confidence",
                    source_path,
                )
                break
        if policy_name == "ml_policy":
            if not _has_required_ml_decision_debug(decision):
                _add_issue(
                    issues,
                    "high",
                    "missing_ml_decision_debug",
                    "offline ml_policy decisions must include ML response/QoS debug fields",
                    source_path,
                )
                break
            fallback_reason = _hidden_ml_fallback_reason(decision.debug)
            if fallback_reason:
                _add_issue(
                    issues,
                    "high",
                    "hidden_ml_fallback",
                    f"offline ml_policy decision {index} used fallback/override metadata: {fallback_reason}",
                    source_path,
                )
                break
        if policy_name == "complexity_aware_ml_a3":
            if not _has_candidate_complexity(decision):
                _add_issue(
                    issues,
                    "high",
                    "missing_candidate_complexity",
                    f"complexity-aware decision {index} is missing candidate_complexity",
                    source_path,
                )
                break
            decision_source = decision.debug.get("decision_source")
            delegated_policy = decision.debug.get("delegated_policy")
            bucket = _decision_complexity_bucket(decision)
            if decision_source not in {"ml_high_complexity", "a3_complexity_gate"}:
                _add_issue(
                    issues,
                    "high",
                    "invalid_complexity_gate_source",
                    f"complexity-aware decision {index} has invalid decision_source={decision_source!r}",
                    source_path,
                )
                break
            if not isinstance(delegated_policy, str) or not delegated_policy:
                _add_issue(
                    issues,
                    "high",
                    "missing_delegated_policy",
                    f"complexity-aware decision {index} is missing delegated_policy",
                    source_path,
                )
                break
            if decision_source == "ml_high_complexity":
                if bucket != "high":
                    _add_issue(
                        issues,
                        "high",
                        "complexity_gate_bucket_mismatch",
                        f"complexity-aware decision {index} used ML outside high bucket: {bucket!r}",
                        source_path,
                    )
                    break
                if not _has_required_ml_decision_debug(decision):
                    _add_issue(
                        issues,
                        "high",
                        "missing_ml_decision_debug",
                        "high-complexity ML decisions must include ML response/QoS debug fields",
                        source_path,
                    )
                    break
                fallback_reason = _hidden_ml_fallback_reason(decision.debug)
                if fallback_reason:
                    _add_issue(
                        issues,
                        "high",
                        "hidden_ml_fallback",
                        f"complexity-aware ML decision {index} used fallback/override metadata: {fallback_reason}",
                        source_path,
                    )
                    break
            elif bucket == "high":
                _add_issue(
                    issues,
                    "high",
                    "complexity_gate_bucket_mismatch",
                    f"complexity-aware decision {index} routed high bucket to A3",
                    source_path,
                )
                break


def _has_required_ml_decision_debug(decision: PolicyDecisionRecord) -> bool:
    if decision.debug.get("ml_backend") == "candidate_ranker":
        return _has_required_ranker_decision_debug(decision)
    return (
        "ml_response_keys" in decision.debug
        and "qos_compliance" in decision.debug
        and "raw_ml_response_metadata" in decision.debug
        and "ml_target_resolution" in decision.debug
        and _has_candidate_complexity(decision)
    )


def _has_required_ranker_decision_debug(decision: PolicyDecisionRecord) -> bool:
    debug = decision.debug
    metadata = debug.get("ranker_metadata")
    scores = debug.get("ranker_candidate_scores")
    threshold = debug.get("ranker_score_threshold")
    return (
        _has_candidate_complexity(decision)
        and isinstance(scores, Mapping)
        and isinstance(metadata, Mapping)
        and bool(metadata.get("model_sha256"))
        and bool(metadata.get("selected_features"))
        and isinstance(metadata.get("validation_metrics"), Mapping)
        and isinstance(metadata.get("threshold_tuning_result"), Mapping)
        and _valid_ranker_complexity_metadata(metadata)
        and isinstance(debug.get("ranker_artifact_sha256"), str)
        and bool(debug.get("ranker_artifact_sha256"))
        and isinstance(debug.get("ranker_model_family"), str)
        and debug.get("ranker_model_family") == "candidate_ranker"
        and isinstance(threshold, (int, float))
        and math.isfinite(float(threshold))
        and "ranker_selected_candidate" in debug
        and "ranker_stay_score" in debug
        and "ranker_best_candidate_score" in debug
        and "ranker_margin_vs_stay" in debug
        and "ranker_min_margin" in debug
        and "dwell_guard_applied" in debug
        and "ml_target_resolution" in debug
        and "qos_compliance" in debug
        and "raw_ml_response_metadata" in debug
    )


def _valid_ranker_complexity_metadata(metadata: Mapping[str, Any]) -> bool:
    high_rows = metadata.get("high_complexity_row_count")
    min_rows = metadata.get("min_high_complexity_rows")
    summaries = metadata.get("trace_complexity_summaries")
    return (
        isinstance(high_rows, int)
        and high_rows >= 0
        and isinstance(min_rows, int)
        and min_rows >= 0
        and isinstance(summaries, list)
        and bool(summaries)
    )


def _has_candidate_complexity(decision: PolicyDecisionRecord) -> bool:
    complexity = decision.debug.get("candidate_complexity")
    if not isinstance(complexity, Mapping):
        return False
    count = complexity.get("viable_candidate_count")
    bucket = complexity.get("complexity_bucket")
    return (
        isinstance(count, int)
        and count >= 0
        and bucket in {"sparse", "moderate", "high"}
    )


def _decision_complexity_bucket(decision: PolicyDecisionRecord) -> Optional[str]:
    complexity = decision.debug.get("candidate_complexity")
    if not isinstance(complexity, Mapping):
        return None
    bucket = complexity.get("complexity_bucket")
    return bucket if isinstance(bucket, str) else None


def _hidden_ml_fallback_reason(debug: Mapping[str, Any]) -> Optional[str]:
    metadata = debug.get("raw_ml_response_metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    combined: Dict[str, Any] = {}
    combined.update({str(key): value for key, value in metadata.items()})
    for key in (
        "fallback_reason",
        "fallback_to_a3",
        "geographic_override",
        "synthetic_bootstrap",
        "model_not_ready",
        "model_ready",
    ):
        if key in debug:
            combined[key] = debug[key]

    fallback_reason = combined.get("fallback_reason")
    if fallback_reason:
        return f"fallback_reason={fallback_reason}"
    if combined.get("fallback_to_a3") is True:
        return "fallback_to_a3=true"
    if combined.get("geographic_override") is True:
        return "geographic_override=true"
    if combined.get("synthetic_bootstrap") is True:
        return "synthetic_bootstrap=true"
    if combined.get("model_not_ready") is True or combined.get("model_ready") is False:
        return "model_not_ready=true"

    warnings = combined.get("warnings")
    if isinstance(warnings, list):
        text = " ".join(str(warning).lower() for warning in warnings)
        if any(token in text for token in ("synthetic", "bootstrap", "model_not_ready", "unfitted")):
            return "warnings=" + text[:120]
    return None


def _load_live_plan(
    root: Path,
    issues: List[OutputValidationIssue],
) -> List[Mapping[str, Any]]:
    path = root / "live_experiment_plan.json"
    if not path.is_file():
        _add_issue(
            issues,
            "high",
            "missing_live_plan",
            "live output is missing live_experiment_plan.json",
            path,
        )
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _add_issue(
            issues,
            "critical",
            "invalid_live_plan_json",
            f"live plan is not valid JSON: {exc}",
            path,
        )
        return []
    if not isinstance(data, list) or not data:
        _add_issue(
            issues,
            "critical",
            "invalid_live_plan",
            "live plan must be a non-empty list",
            path,
        )
        return []
    entries: List[Mapping[str, Any]] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, Mapping):
            _add_issue(
                issues,
                "critical",
                "invalid_live_plan_entry",
                f"live plan entry {index} must be a JSON object",
                path,
            )
            continue
        entries.append(entry)
    return entries


def _validate_live_plan_entries(
    entries: Sequence[Mapping[str, Any]],
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    for entry in entries:
        policy = str(entry.get("policy") or "")
        if not policy:
            _add_issue(
                issues,
                "critical",
                "missing_live_plan_policy",
                "live plan entry is missing policy",
                path,
            )
            continue
        if policy in {"tuned_a3_baseline", "complexity_aware_ml_a3"}:
            tuned_config = entry.get("tuned_a3_config")
            if not tuned_config:
                _add_issue(
                    issues,
                    "high",
                    "missing_tuned_a3_config",
                    f"{policy} live plan is missing tuned_a3_config",
                    path,
                )
                continue
            config_path = Path(str(tuned_config)).expanduser()
            if not config_path.is_file():
                _add_issue(
                    issues,
                    "high",
                    "missing_tuned_a3_config_file",
                    "tuned A3 config path recorded in live plan does not exist",
                    config_path,
                )
                continue
            _validate_tuned_config_payload(config_path, issues, live=True)
        if policy == "complexity_aware_ml_a3" and entry.get("requires_ml_service") is not True:
            _add_issue(
                issues,
                "high",
                "missing_ml_service_requirement",
                "complexity_aware_ml_a3 live plan must declare requires_ml_service=true",
                path,
            )


def _validate_live_topologies(
    root: Path,
    policy_names: Sequence[str],
    issues: List[OutputValidationIssue],
) -> None:
    topology_dir = root / "topology"
    if not topology_dir.is_dir():
        _add_issue(
            issues,
            "high",
            "missing_topology_dir",
            "live output is missing topology directory",
            topology_dir,
        )
        return

    for policy_name in policy_names:
        topology_path = topology_dir / f"{policy_name}_topology.json"
        topology = _read_json_object(topology_path, issues)
        if topology is None:
            continue
        for key in ("metadata", "cells", "ues", "paths"):
            value = topology.get(key)
            if key == "metadata":
                if not isinstance(value, Mapping) or not value:
                    _add_issue(
                        issues,
                        "high",
                        "partial_topology",
                        f"topology for {policy_name} is missing metadata",
                        topology_path,
                    )
            elif not isinstance(value, list) or not value:
                _add_issue(
                    issues,
                    "high",
                    "partial_topology",
                    f"topology for {policy_name} has empty or missing {key}",
                    topology_path,
                )


def _validate_live_logs(
    root: Path,
    policy_names: Sequence[str],
    issues: List[OutputValidationIssue],
) -> None:
    logs_dir = root / "logs"
    if not logs_dir.is_dir():
        _add_issue(
            issues,
            "high",
            "missing_logs_dir",
            "live output is missing logs directory",
            logs_dir,
        )
        return

    for policy_name in policy_names:
        log_path = logs_dir / f"{policy_name}_docker.log"
        if not log_path.is_file():
            _add_issue(
                issues,
                "high",
                "missing_policy_log",
                f"missing Docker log for policy {policy_name}",
                log_path,
            )
            continue
        text = log_path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            _add_issue(
                issues,
                "high",
                "empty_policy_log",
                f"Docker log is empty for policy {policy_name}",
                log_path,
            )
            continue
        if policy_name in LIVE_ML_LOG_POLICIES:
            _validate_ml_error_signatures(text, issues, log_path)
            _validate_ml_fallback_logging(text, issues, log_path)


def _validate_live_ml_qos_metrics(
    policy_metrics: Mapping[str, Any],
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    ok = _numeric_value(policy_metrics.get("qos_compliance_ok"))
    failed = _numeric_value(policy_metrics.get("qos_compliance_failed"))
    if ok is None or failed is None or ok + failed <= 0:
        _add_issue(
            issues,
            "high",
            "missing_ml_qos_compliance_counters",
            "live ml output must include non-zero QoS compliance checks",
            path,
        )


def _validate_live_required_metrics(
    policy_name: str,
    policy_metrics: Mapping[str, Any],
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    required = list(LIVE_REQUIRED_POLICY_METRICS)
    if policy_name in LIVE_ML_POLICIES:
        required.extend(LIVE_REQUIRED_ML_METRICS)
    for metric_name in required:
        if _numeric_value(policy_metrics.get(metric_name)) is None:
            _add_issue(
                issues,
                "high",
                "missing_live_metric",
                f"live policy {policy_name} is missing numeric metric {metric_name}",
                path,
            )


def _validate_live_metric_warnings(
    raw_warnings: Any,
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    if raw_warnings in (None, {}, []):
        return
    if not isinstance(raw_warnings, Mapping):
        _add_issue(
            issues,
            "low",
            "invalid_metric_warning_shape",
            "policy_metric_warnings should be a mapping of policy to warning list",
            path,
        )
        return
    for policy_name, warnings in raw_warnings.items():
        if not isinstance(warnings, list):
            _add_issue(
                issues,
                "low",
                "invalid_metric_warning_shape",
                f"metric warnings for {policy_name} should be a list",
                path,
            )
            continue
        for warning in warnings:
            _add_issue(
                issues,
                "high",
                "metric_collection_warning",
                f"{policy_name}: {warning}",
                path,
            )


def _validate_offline_tuned_a3_artifact(
    root: Path,
    issues: List[OutputValidationIssue],
) -> None:
    config_path = root / "tuned_a3_config.json"
    tuning_path = root / "tuned_a3_tuning_result.json"
    if config_path.is_file():
        _validate_tuned_config_payload(config_path, issues, live=False)
        return
    if tuning_path.is_file():
        _validate_tuned_config_payload(tuning_path, issues, live=False)
        return
    _add_issue(
        issues,
        "high",
        "missing_tuned_a3_artifact",
        "offline tuned A3 policies must include tuned_a3_config.json or tuned_a3_tuning_result.json",
        root,
    )


def _validate_tuned_config_payload(
    path: Path,
    issues: List[OutputValidationIssue],
    *,
    live: bool,
) -> None:
    data = _read_json_object(path, issues)
    if data is None:
        return
    params = data.get("selected_parameters")
    if not isinstance(params, Mapping):
        _add_issue(
            issues,
            "high",
            "invalid_tuned_a3_config",
            "tuned A3 artifact is missing selected_parameters",
            path,
        )
        return
    required = {"a3_offset_db", "hysteresis_db", "time_to_trigger_s", "cooldown_s"}
    missing = sorted(required.difference(params))
    if missing:
        _add_issue(
            issues,
            "high",
            "invalid_tuned_a3_config",
            "tuned A3 selected_parameters missing required keys: " + ", ".join(missing),
            path,
        )
    evaluated = data.get("evaluated_configuration_scores") or data.get(
        "evaluated_configurations"
    )
    if not isinstance(evaluated, list) or not evaluated:
        _add_issue(
            issues,
            "high",
            "missing_tuned_a3_scores",
            "tuned A3 artifact must preserve evaluated configuration scores",
            path,
        )
    if live and not isinstance(data.get("calibration"), Mapping):
        _add_issue(
            issues,
            "high",
            "missing_tuned_a3_calibration_metadata",
            "live tuned A3 config must include calibration metadata",
            path,
        )


def _validate_ml_error_signatures(
    log_text: str,
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    signatures = {
        "Too Many Requests": re.compile(r"Too Many Requests"),
        "500 INTERNAL": re.compile(r"500 INTERNAL"),
        "ML service returned status 429": re.compile(
            r"ML service returned status\s+429"
        ),
        "HTTP 429": re.compile(r"\bHTTP\s+429\b"),
        "status 429": re.compile(r"\bstatus\s+429\b"),
        "access-log 429": re.compile(r'"[A-Z]+\s+[^"]+\s+HTTP/[^"]+"\s+429\b'),
    }
    for signature, pattern in signatures.items():
        if pattern.search(log_text):
            _add_issue(
                issues,
                "high",
                "ml_error_signature_in_logs",
                f"live ML log contains failure signature: {signature}",
                path,
            )
            return


def _validate_ml_fallback_logging(
    log_text: str,
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    normalized = log_text.lower().replace(" ", "")
    fallback_markers = (
        '"fallback_to_a3":true',
        "'fallback_to_a3':true",
        "fallback_to_a3=true",
    )
    if any(marker in normalized for marker in fallback_markers):
        if "fallback_reason" not in normalized:
            _add_issue(
                issues,
                "high",
                "unlabeled_ml_fallback",
                "ML log indicates fallback_to_a3 without fallback_reason",
                path,
            )
        _add_issue(
            issues,
            "high",
            "ml_fallback_in_logs",
            "ML log indicates fallback_to_a3; pure ML/complexity ML evidence is not valid",
            path,
        )
    if '"geographic_override":true' in normalized or "geographic_override=true" in normalized:
        _add_issue(
            issues,
            "high",
            "ml_geographic_override_in_logs",
            "ML log indicates geographic override; pure ML/complexity ML evidence is not valid",
            path,
        )
    if (
        "model_not_ready" in normalized
        or "model_unfitted" in normalized
        or "synthetic_bootstrap" in normalized
    ):
        _add_issue(
            issues,
            "high",
            "ml_model_not_ready_in_logs",
            "ML log indicates synthetic/model-not-ready behavior",
            path,
        )


def _read_json_object(
    path: Path,
    issues: List[OutputValidationIssue],
) -> Optional[Mapping[str, Any]]:
    if not path.is_file():
        _add_issue(
            issues,
            "high",
            "missing_json_file",
            "required JSON file is missing",
            path,
        )
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _add_issue(
            issues,
            "critical",
            "invalid_json",
            f"file is not valid JSON: {exc}",
            path,
        )
        return None
    if not isinstance(data, Mapping):
        _add_issue(
            issues,
            "critical",
            "invalid_json_object",
            "file must contain a JSON object",
            path,
        )
        return None
    return data


def _validate_policy_names(
    policy_names: Sequence[str],
    expected_policies: Optional[Sequence[str]],
    issues: List[OutputValidationIssue],
    path: Path,
) -> None:
    if not policy_names:
        _add_issue(
            issues,
            "critical",
            "missing_policies",
            "output does not declare any policies",
            path,
        )
        return

    unknown = sorted(set(policy_names).difference(SUPPORTED_POLICIES))
    if unknown:
        _add_issue(
            issues,
            "critical",
            "invalid_policy",
            "unsupported policy value(s): " + ", ".join(unknown),
            path,
        )

    if expected_policies:
        missing = sorted(set(expected_policies).difference(policy_names))
        if missing:
            _add_issue(
                issues,
                "high",
                "missing_expected_policy",
                "output is missing expected policy/policies: " + ", ".join(missing),
                path,
            )


def _require_non_empty_string(
    data: Mapping[str, Any],
    key: str,
    path: Path,
    issues: List[OutputValidationIssue],
) -> None:
    if not isinstance(data.get(key), str) or not str(data.get(key)).strip():
        _add_issue(
            issues,
            "high",
            f"missing_{key}",
            f"required field {key} is missing or empty",
            path,
        )


def _require_int(
    data: Mapping[str, Any],
    key: str,
    path: Path,
    issues: List[OutputValidationIssue],
) -> None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        _add_issue(
            issues,
            "high",
            f"missing_{key}",
            f"required integer field {key} is missing",
            path,
        )


def _has_numeric_metric(metrics: Mapping[str, Any]) -> bool:
    for value in metrics.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            return True
    return False


def _numeric_value(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def _add_issue(
    issues: List[OutputValidationIssue],
    severity: Severity,
    code: str,
    message: str,
    path: Path,
) -> None:
    issues.append(
        OutputValidationIssue(
            severity=severity,
            code=code,
            message=message,
            path=str(path),
        )
    )
