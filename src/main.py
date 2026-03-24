"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.deps import init_services, shutdown_services
from src.api.routes import router
from src.config import get_settings
from src.utils.logging_config import setup_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    setup_logging()
    logger = get_logger(__name__)

    logger.info("starting_service", service=settings.service_name, version=settings.service_version)
    await init_services()
    logger.info("service_started")

    yield

    logger.info("shutting_down_service")
    await shutdown_services()
    logger.info("service_stopped")


settings = get_settings()

app = FastAPI(
    title=settings.service_name,
    version=settings.service_version,
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": settings.service_name, "version": settings.service_version}


app.include_router(router)
