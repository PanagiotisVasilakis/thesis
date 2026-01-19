"""A/B Testing Framework for ML Model Comparison.

This module provides controlled traffic splitting between model versions
to measure and compare performance metrics. Essential for thesis evaluation
of different model architectures (LightGBM vs LSTM vs Ensemble).

Usage:
    from ml_service.app.models.ab_testing import ABTestManager
    
    # Create experiment
    ab = ABTestManager.get_instance()
    ab.create_experiment("lstm_evaluation", {
        "control": "lightgbm",
        "treatment": "lstm",
        "traffic_split": 0.2  # 20% to treatment
    })
    
    # Get model for prediction
    model_type = ab.get_variant("lstm_evaluation", ue_id="ue-123")
    
    # Record outcome
    ab.record_outcome("lstm_evaluation", ue_id="ue-123", 
                      success=True, latency_ms=12.5)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ExperimentMetrics:
    """Metrics for a single experiment variant."""
    predictions: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    latencies_ms: List[float] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        total = self.successes + self.failures
        return self.successes / total if total > 0 else 0.0
    
    @property
    def mean_latency_ms(self) -> float:
        return self.total_latency_ms / self.predictions if self.predictions > 0 else 0.0
    
    @property
    def p95_latency_ms(self) -> Optional[float]:
        if len(self.latencies_ms) < 20:
            return None
        sorted_latencies = sorted(self.latencies_ms)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[idx]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "predictions": self.predictions,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": self.success_rate,
            "mean_latency_ms": self.mean_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
        }


@dataclass
class Experiment:
    """An A/B testing experiment configuration."""
    name: str
    control_model: str  # e.g., "lightgbm"
    treatment_model: str  # e.g., "lstm"
    traffic_split: float  # Fraction of traffic to treatment (0.0-1.0)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
    is_active: bool = True
    
    # Metrics per variant
    control_metrics: ExperimentMetrics = field(default_factory=ExperimentMetrics)
    treatment_metrics: ExperimentMetrics = field(default_factory=ExperimentMetrics)
    
    # UE assignment cache (sticky assignment)
    _ue_assignments: Dict[str, str] = field(default_factory=dict)
    
    def get_variant(self, ue_id: str) -> str:
        """Get variant for a UE (sticky assignment based on hash)."""
        if not self.is_active:
            return self.control_model
        
        # Check cached assignment first
        if ue_id in self._ue_assignments:
            return self._ue_assignments[ue_id]
        
        # Deterministic assignment based on hash
        hash_input = f"{self.name}:{ue_id}".encode()
        hash_val = int(hashlib.sha256(hash_input).hexdigest(), 16)
        normalized = (hash_val % 10000) / 10000.0
        
        variant = self.treatment_model if normalized < self.traffic_split else self.control_model
        self._ue_assignments[ue_id] = variant
        return variant
    
    def record_outcome(
        self,
        ue_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """Record prediction outcome for a UE."""
        variant = self._ue_assignments.get(ue_id)
        if variant is None:
            return
        
        metrics = (
            self.treatment_metrics if variant == self.treatment_model 
            else self.control_metrics
        )
        
        metrics.predictions += 1
        metrics.total_latency_ms += latency_ms
        
        if success:
            metrics.successes += 1
        else:
            metrics.failures += 1
        
        # Keep last 1000 latencies for percentile calculation
        if len(metrics.latencies_ms) >= 1000:
            metrics.latencies_ms.pop(0)
        metrics.latencies_ms.append(latency_ms)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "control_model": self.control_model,
            "treatment_model": self.treatment_model,
            "traffic_split": self.traffic_split,
            "created_at": self.created_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "is_active": self.is_active,
            "control_metrics": self.control_metrics.to_dict(),
            "treatment_metrics": self.treatment_metrics.to_dict(),
            "total_ue_assignments": len(self._ue_assignments),
        }


class ABTestManager:
    """Singleton manager for A/B testing experiments."""
    
    _instance: Optional["ABTestManager"] = None
    _lock = threading.Lock()
    
    def __init__(self):
        self.experiments: Dict[str, Experiment] = {}
        self._experiments_lock = threading.Lock()
        
        # Load persisted experiments if available
        self._persistence_path = os.getenv(
            "AB_TEST_PERSISTENCE_PATH",
            "/tmp/ab_experiments.json"
        )
        self._load_experiments()
    
    @classmethod
    def get_instance(cls) -> "ABTestManager":
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None
    
    def create_experiment(
        self,
        name: str,
        control_model: str = "lightgbm",
        treatment_model: str = "lstm",
        traffic_split: float = 0.1,
    ) -> Experiment:
        """Create a new A/B testing experiment.
        
        Args:
            name: Unique experiment name
            control_model: Model type for control group
            treatment_model: Model type for treatment group
            traffic_split: Fraction of traffic to treatment (0.0-1.0)
            
        Returns:
            The created Experiment
        """
        if not 0.0 <= traffic_split <= 1.0:
            raise ValueError("traffic_split must be between 0.0 and 1.0")
        
        experiment = Experiment(
            name=name,
            control_model=control_model,
            treatment_model=treatment_model,
            traffic_split=traffic_split,
        )
        
        with self._experiments_lock:
            # Deactivate existing experiment with same name
            if name in self.experiments:
                self.experiments[name].is_active = False
                self.experiments[name].ended_at = datetime.now(timezone.utc)
            
            self.experiments[name] = experiment
            self._save_experiments()
        
        logger.info(
            f"Created experiment '{name}': {control_model} vs {treatment_model} "
            f"({traffic_split*100:.0f}% treatment)"
        )
        
        return experiment
    
    def get_variant(self, experiment_name: str, ue_id: str) -> str:
        """Get model variant for a UE in an experiment.
        
        Args:
            experiment_name: Name of the experiment
            ue_id: UE identifier
            
        Returns:
            Model type string (e.g., "lightgbm", "lstm")
        """
        with self._experiments_lock:
            experiment = self.experiments.get(experiment_name)
            if experiment is None or not experiment.is_active:
                return os.getenv("MODEL_TYPE", "lightgbm")
            
            return experiment.get_variant(ue_id)
    
    def record_outcome(
        self,
        experiment_name: str,
        ue_id: str,
        success: bool,
        latency_ms: float,
    ) -> None:
        """Record prediction outcome for an experiment."""
        with self._experiments_lock:
            experiment = self.experiments.get(experiment_name)
            if experiment is None:
                return
            
            experiment.record_outcome(ue_id, success, latency_ms)
    
    def end_experiment(self, name: str) -> Optional[Dict[str, Any]]:
        """End an experiment and return final results."""
        with self._experiments_lock:
            experiment = self.experiments.get(name)
            if experiment is None:
                return None
            
            experiment.is_active = False
            experiment.ended_at = datetime.now(timezone.utc)
            self._save_experiments()
            
            return experiment.to_dict()
    
    def get_experiment(self, name: str) -> Optional[Dict[str, Any]]:
        """Get experiment details."""
        with self._experiments_lock:
            experiment = self.experiments.get(name)
            return experiment.to_dict() if experiment else None
    
    def list_experiments(self) -> List[Dict[str, Any]]:
        """List all experiments."""
        with self._experiments_lock:
            return [exp.to_dict() for exp in self.experiments.values()]
    
    def get_comparison_summary(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a comparison summary for thesis reporting.
        
        Returns formatted comparison data suitable for thesis tables/figures.
        """
        with self._experiments_lock:
            experiment = self.experiments.get(name)
            if experiment is None:
                return None
            
            ctrl = experiment.control_metrics
            treat = experiment.treatment_metrics
            
            return {
                "experiment": name,
                "control": {
                    "model": experiment.control_model,
                    "predictions": ctrl.predictions,
                    "success_rate": f"{ctrl.success_rate:.4f}",
                    "mean_latency_ms": f"{ctrl.mean_latency_ms:.2f}",
                    "p95_latency_ms": f"{ctrl.p95_latency_ms:.2f}" if ctrl.p95_latency_ms else "N/A",
                },
                "treatment": {
                    "model": experiment.treatment_model,
                    "predictions": treat.predictions,
                    "success_rate": f"{treat.success_rate:.4f}",
                    "mean_latency_ms": f"{treat.mean_latency_ms:.2f}",
                    "p95_latency_ms": f"{treat.p95_latency_ms:.2f}" if treat.p95_latency_ms else "N/A",
                },
                "success_rate_diff": f"{(treat.success_rate - ctrl.success_rate)*100:+.2f}%",
                "latency_diff": f"{treat.mean_latency_ms - ctrl.mean_latency_ms:+.2f}ms",
                "winner": self._determine_winner(ctrl, treat),
            }
    
    def _determine_winner(
        self,
        ctrl: ExperimentMetrics,
        treat: ExperimentMetrics,
    ) -> str:
        """Determine experiment winner based on success rate."""
        if ctrl.predictions < 100 or treat.predictions < 100:
            return "insufficient_data"
        
        # Simple comparison - in practice would use statistical significance
        diff = treat.success_rate - ctrl.success_rate
        if abs(diff) < 0.01:
            return "no_difference"
        elif diff > 0:
            return "treatment"
        else:
            return "control"
    
    def _save_experiments(self) -> None:
        """Persist experiments to disk."""
        try:
            data = {}
            for name, exp in self.experiments.items():
                data[name] = {
                    "name": exp.name,
                    "control_model": exp.control_model,
                    "treatment_model": exp.treatment_model,
                    "traffic_split": exp.traffic_split,
                    "created_at": exp.created_at.isoformat(),
                    "ended_at": exp.ended_at.isoformat() if exp.ended_at else None,
                    "is_active": exp.is_active,
                }
            
            with open(self._persistence_path, "w") as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Failed to save experiments: {e}")
    
    def _load_experiments(self) -> None:
        """Load persisted experiments from disk."""
        try:
            if not os.path.exists(self._persistence_path):
                return
            
            with open(self._persistence_path, "r") as f:
                data = json.load(f)
            
            for name, exp_data in data.items():
                created_at = datetime.fromisoformat(exp_data["created_at"])
                ended_at = (
                    datetime.fromisoformat(exp_data["ended_at"])
                    if exp_data.get("ended_at") else None
                )
                
                self.experiments[name] = Experiment(
                    name=exp_data["name"],
                    control_model=exp_data["control_model"],
                    treatment_model=exp_data["treatment_model"],
                    traffic_split=exp_data["traffic_split"],
                    created_at=created_at,
                    ended_at=ended_at,
                    is_active=exp_data.get("is_active", True),
                )
            
            logger.info(f"Loaded {len(self.experiments)} experiments from disk")
            
        except Exception as e:
            logger.warning(f"Failed to load experiments: {e}")
