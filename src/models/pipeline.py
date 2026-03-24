"""Pipeline data models."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PipelineStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PREPROCESSING = "preprocessing"
    ANALYZING = "analyzing"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"


class Pipeline(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    minio_path: Optional[str] = None
    status: PipelineStatus = PipelineStatus.PENDING
    current_stage: str = "pending"
    error_message: Optional[str] = None
    error_traceback: Optional[str] = None
    retry_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class PipelineCreate(BaseModel):
    """Request model for pipeline creation (file upload)."""
    pass  # File comes via UploadFile, no body needed


class PipelineResponse(BaseModel):
    """Response model for pipeline endpoints."""
    id: str
    filename: str
    file_type: str
    file_size: int
    minio_path: Optional[str] = None
    status: PipelineStatus
    current_stage: str
    error_message: Optional[str] = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
