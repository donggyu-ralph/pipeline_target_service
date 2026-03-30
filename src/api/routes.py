"""API endpoints for the data pipeline service."""
import asyncio
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Query

from src.api.deps import get_pipeline_manager, get_db
from src.models.pipeline import PipelineResponse, PipelineStatus
from src.models.result import AnalysisResultResponse
from src.utils.logging_config import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1")


@router.post("/pipelines", response_model=PipelineResponse, status_code=201)
async def create_pipeline(file: UploadFile = File(...)):
    """Create a new pipeline by uploading a file."""
    manager = get_pipeline_manager()

    # Read file content before response closes the file handle
    file_content = await file.read()
    await file.seek(0)

    try:
        pipeline = await manager.create_pipeline(file, file_content)
    except Exception as e:
        logger.error("pipeline_creation_failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    # Run pipeline in background with pre-read content
    asyncio.create_task(manager.run_pipeline(pipeline.id))

    return PipelineResponse(**pipeline.model_dump())


@router.get("/pipelines", response_model=list[PipelineResponse])
async def list_pipelines(
    status: Optional[PipelineStatus] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List pipelines with optional status filter."""
    db = get_db()
    pipelines = await db.list_pipelines(status=status, limit=limit, offset=offset)
    return [PipelineResponse(**p.model_dump()) for p in pipelines]


@router.get("/pipelines/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(pipeline_id: str):
    """Get pipeline status by ID."""
    db = get_db()
    pipeline = await db.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return PipelineResponse(**pipeline.model_dump())


@router.post("/pipelines/{pipeline_id}/retry", response_model=PipelineResponse)
async def retry_pipeline(pipeline_id: str):
    """Retry a failed pipeline."""
    manager = get_pipeline_manager()
    db = get_db()

    pipeline = await db.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    if pipeline.status != PipelineStatus.FAILED:
        raise HTTPException(status_code=400, detail="Only failed pipelines can be retried")

    pipeline = await manager.retry_pipeline(pipeline_id)
    asyncio.create_task(manager.run_pipeline(pipeline.id))

    return PipelineResponse(**pipeline.model_dump())


@router.delete("/pipelines/{pipeline_id}", status_code=204)
async def delete_pipeline(pipeline_id: str):
    """Delete a pipeline and its results."""
    db = get_db()
    pipeline = await db.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    await db.delete_pipeline(pipeline_id)


@router.get("/results", response_model=list[AnalysisResultResponse])
async def list_results(
    pipeline_id: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List analysis results."""
    db = get_db()
    results = await db.list_results(pipeline_id=pipeline_id, limit=limit, offset=offset)
    return [AnalysisResultResponse(**r.model_dump()) for r in results]


@router.get("/results/{result_id}", response_model=AnalysisResultResponse)
async def get_result(result_id: str):
    """Get analysis result by ID."""
    db = get_db()
    result = await db.get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")
    return AnalysisResultResponse(**result.model_dump())
