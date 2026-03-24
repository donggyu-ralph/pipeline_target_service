"""Analysis result models."""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AnalysisResult(BaseModel):
    id: str
    pipeline_id: str
    result_type: str  # summary, classification, extraction, etc.
    result_data: dict[str, Any]
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)


class AnalysisResultResponse(BaseModel):
    id: str
    pipeline_id: str
    result_type: str
    result_data: dict[str, Any]
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    processing_time_ms: Optional[int] = None
    created_at: datetime
