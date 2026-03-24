"""PostgreSQL client for pipeline data storage."""
import uuid
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2.extensions import connection as PgConnection

from src.config import PostgreSQLSettings
from src.models.pipeline import Pipeline, PipelineStatus
from src.models.result import AnalysisResult
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

# Register UUID adapter
psycopg2.extras.register_uuid()

INIT_SQL = """
CREATE TABLE IF NOT EXISTS pipelines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_size BIGINT NOT NULL,
    minio_path VARCHAR(500),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    current_stage VARCHAR(50),
    error_message TEXT,
    error_traceback TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_id UUID REFERENCES pipelines(id) ON DELETE CASCADE,
    result_type VARCHAR(50) NOT NULL,
    result_data JSONB NOT NULL,
    model_used VARCHAR(100),
    tokens_used INT,
    processing_time_ms INT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pipelines_status ON pipelines(status);
CREATE INDEX IF NOT EXISTS idx_pipelines_created ON pipelines(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_results_pipeline ON analysis_results(pipeline_id);
"""


class DBClient:
    def __init__(self, settings: PostgreSQLSettings):
        self.settings = settings
        self.conn: PgConnection | None = None

    async def initialize(self) -> None:
        """Connect to PostgreSQL and create tables if needed."""
        self.conn = psycopg2.connect(
            host=self.settings.host,
            port=self.settings.port,
            database=self.settings.database,
            user=self.settings.user,
            password=self.settings.password,
        )
        self.conn.autocommit = True

        with self.conn.cursor() as cur:
            cur.execute(INIT_SQL)

        logger.info("db_initialized", host=self.settings.host, database=self.settings.database)

    async def close(self) -> None:
        if self.conn and not self.conn.closed:
            self.conn.close()

    def _row_to_pipeline(self, row: tuple, columns: list[str]) -> Pipeline:
        data = dict(zip(columns, row))
        data["id"] = str(data["id"])
        return Pipeline(**data)

    def _row_to_result(self, row: tuple, columns: list[str]) -> AnalysisResult:
        data = dict(zip(columns, row))
        data["id"] = str(data["id"])
        data["pipeline_id"] = str(data["pipeline_id"])
        return AnalysisResult(**data)

    # --- Pipeline CRUD ---

    async def create_pipeline(self, pipeline: Pipeline) -> Pipeline:
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO pipelines (id, filename, file_type, file_size, minio_path, status, current_stage)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING id, created_at, updated_at""",
                (pipeline.id, pipeline.filename, pipeline.file_type,
                 pipeline.file_size, pipeline.minio_path, pipeline.status.value, pipeline.current_stage),
            )
            row = cur.fetchone()
            pipeline.created_at = row[1]
            pipeline.updated_at = row[2]
        return pipeline

    async def get_pipeline(self, pipeline_id: str) -> Optional[Pipeline]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM pipelines WHERE id = %s", (pipeline_id,))
            row = cur.fetchone()
            if not row:
                return None
            columns = [desc[0] for desc in cur.description]
            return self._row_to_pipeline(row, columns)

    async def list_pipelines(
        self, status: Optional[PipelineStatus] = None, limit: int = 20, offset: int = 0
    ) -> list[Pipeline]:
        with self.conn.cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM pipelines WHERE status = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (status.value, limit, offset),
                )
            else:
                cur.execute(
                    "SELECT * FROM pipelines ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            columns = [desc[0] for desc in cur.description]
            return [self._row_to_pipeline(row, columns) for row in cur.fetchall()]

    async def update_pipeline_status(
        self,
        pipeline_id: str,
        status: PipelineStatus,
        current_stage: str,
        error_message: Optional[str] = None,
        error_traceback: Optional[str] = None,
    ) -> None:
        with self.conn.cursor() as cur:
            completed_at = datetime.now() if status in (PipelineStatus.COMPLETED, PipelineStatus.FAILED) else None
            cur.execute(
                """UPDATE pipelines
                   SET status = %s, current_stage = %s, error_message = %s,
                       error_traceback = %s, updated_at = NOW(), completed_at = %s
                   WHERE id = %s""",
                (status.value, current_stage, error_message, error_traceback, completed_at, pipeline_id),
            )

    async def update_pipeline_minio_path(self, pipeline_id: str, minio_path: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE pipelines SET minio_path = %s, updated_at = NOW() WHERE id = %s",
                (minio_path, pipeline_id),
            )

    async def increment_retry(self, pipeline_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute(
                "UPDATE pipelines SET retry_count = retry_count + 1, status = 'pending', updated_at = NOW() WHERE id = %s",
                (pipeline_id,),
            )

    async def delete_pipeline(self, pipeline_id: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM pipelines WHERE id = %s", (pipeline_id,))

    # --- Result CRUD ---

    async def create_result(self, result: AnalysisResult) -> AnalysisResult:
        import json
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO analysis_results (id, pipeline_id, result_type, result_data, model_used, tokens_used, processing_time_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   RETURNING created_at""",
                (result.id, result.pipeline_id, result.result_type,
                 json.dumps(result.result_data), result.model_used,
                 result.tokens_used, result.processing_time_ms),
            )
            row = cur.fetchone()
            result.created_at = row[0]
        return result

    async def get_result(self, result_id: str) -> Optional[AnalysisResult]:
        with self.conn.cursor() as cur:
            cur.execute("SELECT * FROM analysis_results WHERE id = %s", (result_id,))
            row = cur.fetchone()
            if not row:
                return None
            columns = [desc[0] for desc in cur.description]
            return self._row_to_result(row, columns)

    async def list_results(
        self, pipeline_id: Optional[str] = None, limit: int = 20, offset: int = 0
    ) -> list[AnalysisResult]:
        with self.conn.cursor() as cur:
            if pipeline_id:
                cur.execute(
                    "SELECT * FROM analysis_results WHERE pipeline_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (pipeline_id, limit, offset),
                )
            else:
                cur.execute(
                    "SELECT * FROM analysis_results ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    (limit, offset),
                )
            columns = [desc[0] for desc in cur.description]
            return [self._row_to_result(row, columns) for row in cur.fetchall()]
