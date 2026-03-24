"""Stage 1: File upload to MinIO."""
import uuid

from fastapi import UploadFile

from src.config import PipelineSettings
from src.models.pipeline import Pipeline, PipelineStatus
from src.pipeline.errors import FileTooLargeError, UnsupportedFormatError
from src.services.minio_client import MinIOClient
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


async def upload_stage(
    file: UploadFile,
    pipeline: Pipeline,
    minio: MinIOClient,
    settings: PipelineSettings,
    file_content: bytes = None,
) -> Pipeline:
    """Upload file to MinIO after validation."""
    # Use pre-read content or read from file
    content = file_content if file_content is not None else await file.read()
    file_size = len(content)

    # Validate file size
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise FileTooLargeError(
            f"File size {file_size / 1024 / 1024:.1f}MB exceeds limit {settings.max_file_size_mb}MB"
        )

    # Validate file format
    file_ext = pipeline.file_type.lower()
    if file_ext not in settings.supported_formats:
        raise UnsupportedFormatError(
            f"Format '{file_ext}' not supported. Supported: {settings.supported_formats}"
        )

    # Upload to MinIO
    object_name = f"uploads/{pipeline.id}/{pipeline.filename}"
    content_type = file.content_type or "application/octet-stream"

    minio_path = await minio.upload_file(object_name, content, content_type)

    pipeline.minio_path = minio_path
    pipeline.file_size = file_size
    pipeline.status = PipelineStatus.UPLOADING
    pipeline.current_stage = "upload"

    logger.info(
        "upload_stage_completed",
        pipeline_id=pipeline.id,
        filename=pipeline.filename,
        size=file_size,
        minio_path=minio_path,
    )

    return pipeline
