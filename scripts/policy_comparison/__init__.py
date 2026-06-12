"""Offline policy comparison helpers for thesis handover experiments.

The package keeps comparison orchestration separate from the shared NEF
emulator, the ML service, and the standards-inspired A3 baseline service.
"""

from .campaign_plan import (
    ComparisonCampaignPlan,
    build_comparison_campaign_plan,
)
from .candidate_ranker import (
    build_candidate_ranker_dataset,
    build_candidate_ranker_features,
    build_labeled_candidate_ranker_dataset,
)
from .candidate_ranker_artifact import (
    CandidateRankerArtifact,
    load_candidate_ranker_artifact,
)
from .manifest import ReproducibilityManifest, build_reproducibility_manifest
from .nef_trace import capture_nef_trace_records, feature_vector_to_trace_record
from .output_validation import (
    OutputValidationReport,
    validate_comparison_output,
)
from .policy_adapters import FixedA3PolicyAdapter, MLPolicyAdapter, TunedA3PolicyAdapter
from .replay import OfflineReplayRunner, ReplayResult
from .schemas import (
    MeasurementTraceRecord,
    PolicyDecisionRecord,
    TraceSchemaError,
    VisibleCellMeasurement,
)
from .trace_io import read_trace_jsonl, write_trace_jsonl
from .trace_plan import TracePreparationPlan, build_trace_preparation_plan


def __getattr__(name: str):
    if name in {
        "PolicyStatisticalReport",
        "build_statistical_report",
        "load_run_metrics",
    }:
        from . import statistical_report as _statistical_report

        return getattr(_statistical_report, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "FixedA3PolicyAdapter",
    "ComparisonCampaignPlan",
    "CandidateRankerArtifact",
    "MLPolicyAdapter",
    "MeasurementTraceRecord",
    "OfflineReplayRunner",
    "OutputValidationReport",
    "PolicyDecisionRecord",
    "ReplayResult",
    "ReproducibilityManifest",
    "PolicyStatisticalReport",
    "TraceSchemaError",
    "TracePreparationPlan",
    "TunedA3PolicyAdapter",
    "VisibleCellMeasurement",
    "build_reproducibility_manifest",
    "build_comparison_campaign_plan",
    "build_candidate_ranker_dataset",
    "build_candidate_ranker_features",
    "build_labeled_candidate_ranker_dataset",
    "build_statistical_report",
    "build_trace_preparation_plan",
    "capture_nef_trace_records",
    "feature_vector_to_trace_record",
    "load_run_metrics",
    "load_candidate_ranker_artifact",
    "read_trace_jsonl",
    "validate_comparison_output",
    "write_trace_jsonl",
]
