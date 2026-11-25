"""Service readiness endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request

from bird_recognition.api.errors import APIError
from bird_recognition.api.schemas import Health

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=Health,
    summary="Check service readiness",
    description="Reports whether the API can reach its configured read-only database.",
    responses={503: {"description": "Database is not ready."}},
)
def health(request: Request) -> dict[str, str]:
    """Return readiness, or a structured error if the database is unavailable."""
    try:
        store = request.app.state.resources.get_store()
        store.preflight(read_only=True)
    except Exception:
        raise APIError(
            503, "database_unavailable", "The database is not ready."
        ) from None
    return {"status": "ready", "database": "ready"}
