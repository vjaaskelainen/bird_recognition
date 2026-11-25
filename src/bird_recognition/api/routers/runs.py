"""Processing-run listing and inspection endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.schemas import PageEnvelope, RunDetail
from bird_recognition.api.security import require_api_key
from bird_recognition.inspection import build_inspection_payload

router = APIRouter(
    tags=["runs"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/runs",
    response_model=PageEnvelope,
    summary="List processing runs",
    responses={401: {"model": ProblemDetails}, 503: {"model": ProblemDetails}},
)
def list_runs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """Return a bounded page of persisted run summaries."""
    try:
        values = request.app.state.resources.get_store().list_runs()
    except APIError:
        raise
    except Exception:
        raise APIError(503, "database_unavailable", "Runs are unavailable.") from None
    return {
        "items": values[offset : offset + limit],
        "limit": limit,
        "offset": offset,
        "total": len(values),
    }


@router.get(
    "/runs/{run_id}",
    response_model=RunDetail,
    summary="Inspect a processing run",
    responses={
        401: {"model": ProblemDetails},
        404: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def get_run(run_id: UUID, request: Request) -> dict[str, object]:
    """Return the same enriched inspection envelope as the CLI."""
    try:
        run_data, items = request.app.state.resources.get_store().inspect_run(run_id)
    except APIError:
        raise
    except Exception as error:
        if "not found" in str(error).casefold():
            raise APIError(404, "not_found", "The run was not found.") from None
        raise APIError(503, "database_unavailable", "The run is unavailable.") from None
    return build_inspection_payload(run_data, items)
