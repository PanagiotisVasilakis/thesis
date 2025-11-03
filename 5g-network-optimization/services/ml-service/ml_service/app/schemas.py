from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PredictionRequest(BaseModel):
    """Schema for prediction requests."""

    model_config = ConfigDict(extra="forbid")

    ue_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude: Optional[float] = None
    speed: Optional[float] = None
    velocity: Optional[float] = None
    acceleration: Optional[float] = None
    cell_load: Optional[float] = None
    handover_count: Optional[int] = None
    signal_trend: Optional[float] = None
    environment: Optional[float] = None
    direction: Optional[List[float]] = None
    connected_to: Optional[str] = None
    rf_metrics: Optional[Dict[str, Dict[str, float]]] = None
    service_type: Optional[str] = None
    service_priority: Optional[int] = Field(default=None, ge=1, le=10)
    qos_requirements: Optional[Dict[str, float]] = None


class TrainingSample(PredictionRequest):
    """Schema for training samples."""

    # training samples may omit UE identifier
    ue_id: Optional[str] = None  # type: ignore[override]
    optimal_antenna: str


class FeedbackSample(TrainingSample):
    """Schema for feedback on handover outcome."""

    success: bool = True
    model_config = ConfigDict(extra="forbid")

class QoSObservation(BaseModel):
    """Schema for observed QoS metrics supplied by the NEF emulator."""

    model_config = ConfigDict(extra="forbid")

    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    jitter_ms: Optional[float] = Field(default=None, ge=0.0)
    throughput_mbps: Optional[float] = Field(default=None, ge=0.0)
    packet_loss_rate: Optional[float] = Field(default=None, ge=0.0, le=100.0)

    def to_filtered_dict(self) -> Dict[str, float]:
        """Return only metrics that were provided (drop ``None`` values)."""

        return {
            key: value
            for key, value in (
                ("latency_ms", self.latency_ms),
                ("jitter_ms", self.jitter_ms),
                ("throughput_mbps", self.throughput_mbps),
                ("packet_loss_rate", self.packet_loss_rate),
            )
            if value is not None
        }


class PredictionRequestWithQoS(PredictionRequest):
    """Extended prediction request with QoS requirements."""

    model_config = ConfigDict(extra="forbid")

    # Allowed values: 'urllc', 'embb', 'mmtc', 'default'
    service_type: str = "default"
    qos_requirements: Optional[Dict[str, float]] = None
    edge_service_requirements: Optional[Dict[str, Any]] = None
    service_priority: int = Field(5, ge=1, le=10)
    observed_qos: Optional[QoSObservation] = None


class QoSFeedbackRequest(BaseModel):
    """Schema for QoS feedback originating from the NEF emulator."""

    model_config = ConfigDict(extra="forbid")

    ue_id: str
    antenna_id: str
    service_type: str = "default"
    service_priority: int = Field(5, ge=1, le=10)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    success: bool = True
    observed_qos: Optional[QoSObservation] = None
    qos_requirements: Optional[Dict[str, float]] = None
    violations: Optional[List[Dict[str, float]]] = None
    timestamp: Optional[float] = None
