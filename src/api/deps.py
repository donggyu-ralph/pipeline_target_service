"""Dependency injection for API endpoints."""
from functools import lru_cache

from src.config import Settings, get_settings
from src.services.db_client import DBClient
from src.services.minio_client import MinIOClient
from src.services.qwen_client import QwenClient
from src.pipeline.manager import PipelineManager


_db_client: DBClient | None = None
_minio_client: MinIOClient | None = None
_qwen_client: QwenClient | None = None
_pipeline_manager: PipelineManager | None = None


async def init_services() -> None:
    """Initialize all service clients. Called on app startup."""
    global _db_client, _minio_client, _qwen_client, _pipeline_manager

    settings = get_settings()

    _db_client = DBClient(settings.postgresql)
    await _db_client.initialize()

    _minio_client = MinIOClient(settings.minio)
    _minio_client.initialize()

    _qwen_client = QwenClient(settings.qwen)

    _pipeline_manager = PipelineManager(
        db=_db_client,
        minio=_minio_client,
        qwen=_qwen_client,
        settings=settings.pipeline,
    )


async def shutdown_services() -> None:
    """Cleanup service clients. Called on app shutdown."""
    global _db_client, _qwen_client
    if _db_client:
        await _db_client.close()
    if _qwen_client:
        await _qwen_client.close()


def get_db() -> DBClient:
    assert _db_client is not None, "DB client not initialized"
    return _db_client


def get_minio() -> MinIOClient:
    assert _minio_client is not None, "MinIO client not initialized"
    return _minio_client


def get_qwen() -> QwenClient:
    assert _qwen_client is not None, "Qwen client not initialized"
    return _qwen_client


def get_pipeline_manager() -> PipelineManager:
    assert _pipeline_manager is not None, "Pipeline manager not initialized"
    return _pipeline_manager
