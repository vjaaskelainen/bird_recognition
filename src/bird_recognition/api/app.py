"""FastAPI application factory and shared lifespan resources."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from bird_recognition.api.errors import install_error_handlers
from bird_recognition.api.jobs import JobManager
from bird_recognition.api.resources import APIResources
from bird_recognition.api.routers import (
    ask,
    crops,
    health,
    jobs,
    media,
    reviews,
    runs,
    search,
    session,
    videos,
    visits,
)
from bird_recognition.api.security import validate_bind
from bird_recognition.api.sessions import SessionStore
from bird_recognition.api.settings import APISettings, load_settings
from bird_recognition.api.ui import mount_ui

_DESCRIPTION = (
    "Bird-recognition HTTP API. Species confidence and search similarity are not "
    "biological probabilities. Visits require explicit owner-reviewed groups. "
    "Errors use application/problem+json."
)


def create_app(
    settings: APISettings | None = None,
    *,
    store_factory: Any = None,
    model_loader: Any = None,
    ask_executor: Any = None,
    job_manager: Any = None,
    review_store_factory: Any = None,
) -> FastAPI:
    """Create the versioned API without opening the database or loading models."""
    resolved_settings = settings or load_settings()
    validate_bind(resolved_settings)
    if job_manager is None and resolved_settings.jobs_dir is not None:
        job_manager = JobManager(resolved_settings.jobs_dir)
    resources = APIResources(
        resolved_settings,
        store_factory=store_factory,
        model_loader=model_loader,
        ask_executor=ask_executor,
        job_manager=job_manager,
        review_store_factory=review_store_factory,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if resources.job_manager is not None:
            resources.job_manager.recover()
        yield
        if resources._store is not None:
            resources._store.close()

    app = FastAPI(
        title="Bird Recognition API",
        version="1.0.0",
        description=_DESCRIPTION,
        openapi_version="3.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.resources = resources
    app.state.sessions = SessionStore()
    install_error_handlers(app)
    app.include_router(health.router, prefix="/v1")
    app.include_router(session.router, prefix="/v1")
    app.include_router(search.router, prefix="/v1")
    app.include_router(crops.router, prefix="/v1")
    app.include_router(runs.router, prefix="/v1")
    app.include_router(visits.router, prefix="/v1")
    app.include_router(ask.router, prefix="/v1")
    app.include_router(jobs.router, prefix="/v1")
    app.include_router(videos.router, prefix="/v1")
    app.include_router(reviews.router, prefix="/v1")
    app.include_router(media.router, prefix="/v1")
    mount_ui(app, resolved_settings.ui_dir)
    return app
