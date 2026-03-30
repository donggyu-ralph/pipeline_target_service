"""Stage 2: File preprocessing."""
import csv
import io
import json

import chardet
from PIL import Image

from src.models.pipeline import Pipeline
from src.pipeline.errors import PreprocessingError
from src.services.minio_client import MinIOClient
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


async def preprocess_stage(pipeline: Pipeline, minio: MinIOClient) -> dict:
    """Preprocess file based on type. Returns preprocessed content."""
    object_name = pipeline.minio_path.split("/", 1)[1] if pipeline.minio_path else ""
    raw_data = await minio.download_file(object_name)

    file_type = pipeline.file_type.lower()

    try:
        if file_type == "csv":
            result = _preprocess_csv(raw_data)
        elif file_type == "json":
            result = _preprocess_json(raw_data)
        elif file_type in ("jpg", "jpeg", "png"):
            result = _preprocess_image(raw_data, file_type)
        elif file_type == "txt":
            result = _preprocess_text(raw_data)
        else:
            raise PreprocessingError(f"No preprocessor for type: {file_type}")
    except PreprocessingError:
        raise
    except Exception as e:
        raise PreprocessingError(f"Preprocessing failed: {e}") from e

    logger.info("preprocess_stage_completed", pipeline_id=pipeline.id, file_type=file_type)
    return result


def _preprocess_csv(raw_data: bytes) -> dict:
    """Detect encoding, validate headers, remove blank rows."""
    detected = chardet.detect(raw_data)
    encoding = detected.get("encoding", "utf-8") or "utf-8"

    text = raw_data.decode(encoding)
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]

    if not rows:
        raise PreprocessingError("CSV file is empty")

    headers = rows[0]
    data_rows = rows[1:]

    return {
        "type": "csv",
        "encoding": encoding,
        "headers": headers,
        "row_count": len(data_rows),
        "content": text,
        "preview": "\n".join(",".join(row) for row in rows[:20]),
    }


def _preprocess_json(raw_data: bytes) -> dict:
    """Parse and validate JSON."""
    text = raw_data.decode("utf-8")
    data = json.loads(text)

    if isinstance(data, list):
        item_count = len(data)
        preview = json.dumps(data[:5], ensure_ascii=False, indent=2)
    elif isinstance(data, dict):
        item_count = len(data)
        preview = json.dumps(data, ensure_ascii=False, indent=2)[:3000]
    else:
        item_count = 1
        preview = str(data)[:3000]

    return {
        "type": "json",
        "item_count": item_count,
        "content": text,
        "preview": preview,
    }


def _preprocess_image(raw_data: bytes, file_type: str) -> dict:
    """Validate image and resize for Qwen input optimization."""
    img = Image.open(io.BytesIO(raw_data))
    original_size = img.size

    # Resize if too large (Qwen optimal: max 1280px on longest side)
    max_dim = 1280
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Convert to bytes
    buf = io.BytesIO()
    fmt = "JPEG" if file_type in ("jpg", "jpeg") else "PNG"
    img.save(buf, format=fmt)
    processed_data = buf.getvalue()

    return {
        "type": "image",
        "format": file_type,
        "original_size": original_size,
        "processed_size": img.size,
        "image_data": processed_data,
    }


def _preprocess_text(raw_data: bytes) -> dict:
    """Detect encoding and clean text."""
    detected = chardet.detect(raw_data)
    encoding = detected.get("encoding", "utf-8") or "utf-8"

    text = raw_data.decode(encoding)
    # Clean: normalize line endings, strip trailing whitespace
    lines = [line.rstrip() for line in text.splitlines()]
    cleaned = "\n".join(lines).strip()

    return {
        "type": "text",
        "encoding": encoding,
        "line_count": len(lines),
        "char_count": len(cleaned),
        "content": cleaned,
        "preview": cleaned[:3000],
    }
