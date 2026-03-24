"""Configuration management using Pydantic Settings."""
import os
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def _resolve_env_vars(obj):
    """Recursively resolve ${ENV_VAR} placeholders with environment variables."""
    import re
    if isinstance(obj, str):
        pattern = re.compile(r'\$\{(\w+)\}')
        def replace(m):
            return os.environ.get(m.group(1), m.group(0))
        return pattern.sub(replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def _load_yaml_config() -> dict:
    """Load config.yaml and resolve environment variable placeholders."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        return {}

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}

    return _resolve_env_vars(raw)


class MinIOSettings(BaseSettings):
    endpoint: str = Field(default="minio.data.svc:9000", alias="MINIO_ENDPOINT")
    access_key: str = Field(default="admin", alias="MINIO_ACCESS_KEY")
    secret_key: str = Field(default="", alias="MINIO_SECRET_KEY")
    bucket: str = Field(default="pipeline-data", alias="MINIO_BUCKET")
    secure: bool = False

    model_config = {"populate_by_name": True, "extra": "ignore"}


class PostgreSQLSettings(BaseSettings):
    host: str = Field(default="postgres.data.svc", alias="PG_HOST")
    port: int = Field(default=5432, alias="PG_PORT")
    database: str = Field(default="pipeline", alias="PG_DATABASE")
    user: str = Field(default="admin", alias="PG_USER")
    password: str = Field(default="", alias="PG_PASSWORD")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class QwenSettings(BaseSettings):
    base_url: str = Field(default="http://192.168.50.26:32000/v1", alias="QWEN_BASE_URL")
    api_key: str = Field(default="", alias="QWEN_API_KEY")
    model: str = Field(default="qwen3-vl:32b", alias="QWEN_MODEL")
    max_tokens: int = 2048
    timeout: int = 120

    model_config = {"populate_by_name": True, "extra": "ignore"}


class PipelineSettings(BaseSettings):
    max_file_size_mb: int = 50
    supported_formats: list[str] = ["csv", "json", "txt", "jpg", "jpeg", "png"]
    max_concurrent_pipelines: int = 3
    retry_max_attempts: int = 3
    retry_delay_seconds: int = 10


class ServerSettings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000


class LoggingSettings(BaseSettings):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


class Settings(BaseSettings):
    service_name: str = "data-pipeline-service"
    service_version: str = "1.0.0"

    server: ServerSettings = ServerSettings()
    minio: MinIOSettings = MinIOSettings()
    postgresql: PostgreSQLSettings = PostgreSQLSettings()
    qwen: QwenSettings = QwenSettings()
    pipeline: PipelineSettings = PipelineSettings()
    logging: LoggingSettings = LoggingSettings()

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    yaml_config = _load_yaml_config()

    # Override defaults from yaml if present
    overrides = {}
    if "server" in yaml_config:
        overrides["server"] = ServerSettings(**yaml_config["server"])
    if "minio" in yaml_config:
        overrides["minio"] = MinIOSettings(**yaml_config["minio"])
    if "qwen" in yaml_config:
        overrides["qwen"] = QwenSettings(**yaml_config["qwen"])
    if "pipeline" in yaml_config:
        overrides["pipeline"] = PipelineSettings(**yaml_config["pipeline"])
    if "logging" in yaml_config:
        overrides["logging"] = LoggingSettings(**yaml_config["logging"])

    svc = yaml_config.get("service", {})
    if "name" in svc:
        overrides["service_name"] = svc["name"]
    if "version" in svc:
        overrides["service_version"] = svc["version"]

    return Settings(**overrides)
