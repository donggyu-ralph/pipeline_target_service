"""Stage 4: Store analysis results to PostgreSQL."""
import json
import uuid

from src.models.pipeline import Pipeline
from src.models.result import AnalysisResult
from src.pipeline.errors import StorageError
from src.services.db_client import DBClient
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


async def store_stage(pipeline: Pipeline, analysis: dict, db: DBClient) -> AnalysisResult:
    """Store analysis result in PostgreSQL."""
    try:
        # Parse the raw LLM response as JSON if possible
        raw_response = analysis["raw_response"]
        try:
            result_data = json.loads(raw_response)
        except (json.JSONDecodeError, TypeError):
            result_data = {"raw_text": raw_response}

        result = AnalysisResult(
            id=str(uuid.uuid4()),
            pipeline_id=pipeline.id,
            result_type=analysis.get("analysis_type", "unknown"),
            result_data=result_data,
            model_used=analysis.get("model_used"),
            tokens_used=analysis.get("tokens_used"),
            processing_time_ms=analysis.get("processing_time_ms"),
        )

        result = await db.create_result(result)

        logger.info(
            "store_stage_completed",
            pipeline_id=pipeline.id,
            result_id=result.id,
            result_type=result.result_type,
        )

        return result

    except Exception as e:
        raise StorageError(f"Failed to store result: {e}") from e
