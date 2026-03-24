"""MinIO client for file storage."""
import io
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from src.config import MinIOSettings
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class MinIOClient:
    def __init__(self, settings: MinIOSettings):
        self.settings = settings
        self.client: Minio | None = None

    def initialize(self) -> None:
        """Initialize MinIO client and ensure bucket exists."""
        self.client = Minio(
            self.settings.endpoint,
            access_key=self.settings.access_key,
            secret_key=self.settings.secret_key,
            secure=self.settings.secure,
        )

        if not self.client.bucket_exists(self.settings.bucket):
            self.client.make_bucket(self.settings.bucket)
            logger.info("minio_bucket_created", bucket=self.settings.bucket)

    async def upload_file(
        self, object_name: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload file to MinIO. Returns the object path."""
        assert self.client is not None, "MinIO client not initialized"

        self.client.put_object(
            self.settings.bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info("minio_upload_success", object_name=object_name, size=len(data))
        return f"{self.settings.bucket}/{object_name}"

    async def download_file(self, object_name: str) -> bytes:
        """Download file from MinIO."""
        assert self.client is not None, "MinIO client not initialized"

        response = self.client.get_object(self.settings.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def delete_file(self, object_name: str) -> None:
        """Delete file from MinIO."""
        assert self.client is not None, "MinIO client not initialized"
        self.client.remove_object(self.settings.bucket, object_name)
