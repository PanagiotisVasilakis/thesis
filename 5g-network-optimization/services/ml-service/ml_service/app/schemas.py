from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel


class PredictionRequest(BaseModel):
    """Schema for prediction requests."""

    ue_id: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
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

    class Config:
        extra = "ignore"


class TrainingSample(PredictionRequest):
    """Schema for training samples."""

    # training samples may omit UE identifier
    ue_id: Optional[str] = None
    optimal_antenna: str

    class Config:
        extra = "ignore"


class FeedbackSample(TrainingSample):
    """Schema for feedback on handover outcome."""

    success: bool = True

    class Config:
        extra = "ignore"
