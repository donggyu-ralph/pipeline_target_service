"""Uploaded file model."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UploadedFile(BaseModel):
    id: str
    pipeline_id: str
    original_filename: str
    file_type: str
    file_size: int
    minio_path: str
    content_type: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
