"""Stage 3: Qwen API analysis."""
from src.models.pipeline import Pipeline
from src.pipeline.errors import AnalysisError
from src.services.qwen_client import QwenClient
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


async def analyze_stage(pipeline: Pipeline, preprocessed: dict, qwen: QwenClient) -> dict:
    """Call Qwen API to analyze preprocessed data."""
    file_type = preprocessed["type"]

    try:
        if file_type == "csv":
            result = await qwen.analyze_csv(preprocessed["preview"])
        elif file_type == "json":
            result = await qwen.analyze_text(preprocessed["preview"], task="extract")
        elif file_type == "image":
            result = await qwen.analyze_image(
                preprocessed["image_data"],
                preprocessed["format"],
            )
        elif file_type == "text":
            result = await qwen.analyze_text(preprocessed["preview"], task="summarize")
        else:
            raise AnalysisError(f"No analyzer for type: {file_type}")
    except AnalysisError:
        raise
    except Exception as e:
        raise AnalysisError(f"Analysis failed: {e}") from e

    logger.info(
        "analyze_stage_completed",
        pipeline_id=pipeline.id,
        file_type=file_type,
        tokens=result.get("tokens_used"),
        elapsed_ms=result.get("processing_time_ms"),
    )

    return {
        "raw_response": result["content"],
        "tokens_used": result.get("tokens_used"),
        "processing_time_ms": result.get("processing_time_ms"),
        "model_used": result.get("model"),
        "analysis_type": file_type,
    }
