"""Pipeline manager: orchestrates the 4-stage pipeline."""
import asyncio
import traceback
import uuid
from pathlib import Path

from fastapi import UploadFile

from src.config import PipelineSettings
from src.models.pipeline import Pipeline, PipelineStatus
from src.pipeline.errors import PipelineError
from src.pipeline.stages.upload import upload_stage
from src.pipeline.stages.preprocess import preprocess_stage
from src.pipeline.stages.analyze import analyze_stage
from src.pipeline.stages.store import store_stage
from src.services.db_client import DBClient
from src.services.minio_client import MinIOClient
from src.services.qwen_client import QwenClient
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class PipelineManager:
    def __init__(
        self,
        db: DBClient,
        minio: MinIOClient,
        qwen: QwenClient,
        settings: PipelineSettings,
    ):
        self.db = db
        self.minio = minio
        self.qwen = qwen
        self.settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_pipelines)
        self._upload_files: dict[str, UploadFile] = {}

    async def create_pipeline(self, file: UploadFile) -> Pipeline:
        """Create a new pipeline entry and store the upload file reference."""
        filename = file.filename or "unknown"
        file_ext = Path(filename).suffix.lstrip(".").lower()

        pipeline = Pipeline(
            id=str(uuid.uuid4()),
            filename=filename,
            file_type=file_ext,
            file_size=0,  # Updated after upload
            status=PipelineStatus.PENDING,
            current_stage="pending",
        )

        pipeline = await self.db.create_pipeline(pipeline)
        self._upload_files[pipeline.id] = file

        logger.info("pipeline_created", pipeline_id=pipeline.id, filename=filename)
        return pipeline

    async def run_pipeline(self, pipeline_id: str) -> None:
        """Execute the full 4-stage pipeline with concurrency control."""
        async with self._semaphore:
            await self._execute_pipeline(pipeline_id)

    async def _execute_pipeline(self, pipeline_id: str) -> None:
        """Execute pipeline stages sequentially."""
        pipeline = await self.db.get_pipeline(pipeline_id)
        if not pipeline:
            logger.error("pipeline_not_found", pipeline_id=pipeline_id)
            return

        file = self._upload_files.pop(pipeline_id, None)

        try:
            # Stage 1: Upload
            await self.db.update_pipeline_status(
                pipeline_id, PipelineStatus.UPLOADING, "upload"
            )
            pipeline = await upload_stage(file, pipeline, self.minio, self.settings)
            await self.db.update_pipeline_minio_path(pipeline_id, pipeline.minio_path)

            # Stage 2: Preprocess
            await self.db.update_pipeline_status(
                pipeline_id, PipelineStatus.PREPROCESSING, "preprocess"
            )
            preprocessed = await preprocess_stage(pipeline, self.minio)

            # Stage 3: Analyze
            await self.db.update_pipeline_status(
                pipeline_id, PipelineStatus.ANALYZING, "analyze"
            )
            analysis = await analyze_stage(pipeline, preprocessed, self.qwen)

            # Stage 4: Store
            await self.db.update_pipeline_status(
                pipeline_id, PipelineStatus.STORING, "store"
            )
            result = await store_stage(pipeline, analysis, self.db)

            # Mark completed
            await self.db.update_pipeline_status(
                pipeline_id, PipelineStatus.COMPLETED, "completed"
            )
            logger.info("pipeline_completed", pipeline_id=pipeline_id)

        except PipelineError as e:
            tb = traceback.format_exc()
            logger.error(
                "pipeline_failed",
                pipeline_id=pipeline_id,
                error=str(e),
                stage=pipeline.current_stage,
            )
            await self.db.update_pipeline_status(
                pipeline_id,
                PipelineStatus.FAILED,
                pipeline.current_stage,
                error_message=str(e),
                error_traceback=tb,
            )
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(
                "pipeline_unexpected_error",
                pipeline_id=pipeline_id,
                error=str(e),
            )
            await self.db.update_pipeline_status(
                pipeline_id,
                PipelineStatus.FAILED,
                pipeline.current_stage,
                error_message=f"Unexpected error: {e}",
                error_traceback=tb,
            )

    async def retry_pipeline(self, pipeline_id: str) -> Pipeline:
        """Reset a failed pipeline for retry."""
        await self.db.increment_retry(pipeline_id)
        pipeline = await self.db.get_pipeline(pipeline_id)
        logger.info("pipeline_retry", pipeline_id=pipeline_id, retry_count=pipeline.retry_count)
        return pipeline
