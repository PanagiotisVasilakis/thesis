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


class TrainingSample(PredictionRequest):
    """Schema for training samples."""

    # training samples may omit UE identifier
    ue_id: Optional[str] = None  # type: ignore[override]
    optimal_antenna: str


class FeedbackSample(TrainingSample):
    """Schema for feedback on handover outcome."""

    success: bool = True
    model_config = ConfigDict(extra="forbid")


class PredictionRequestWithQoS(PredictionRequest):
    """Extended prediction request with QoS requirements."""

    model_config = ConfigDict(extra="forbid")

    # Allowed values: 'urllc', 'embb', 'mmtc', 'default'
    service_type: str = "default"
    qos_requirements: Optional[Dict[str, float]] = None
    edge_service_requirements: Optional[Dict[str, Any]] = None
    service_priority: int = Field(5, ge=1, le=10)
