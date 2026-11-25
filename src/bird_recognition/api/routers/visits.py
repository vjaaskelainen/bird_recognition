"""Owner-reviewed visit aggregation endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.schemas import VisitList
from bird_recognition.api.security import require_api_key

router = APIRouter(
    tags=["visits"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/visits",
    response_model=VisitList,
    summary="Aggregate owner-reviewed visit groups",
    description=(
        "Requires a reviewed group manifest. Visit membership is not inferred from "
        "shared video membership."
    ),
    responses={
        400: {"model": ProblemDetails},
        401: {"model": ProblemDetails},
        404: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def get_visits(
    run_id: UUID,
    request: Request,
    groups: Annotated[
        str | None, Query(description="Reviewed groups manifest path")
    ] = None,
) -> dict[str, object]:
    """Build the same visit report as the CLI without writing a local report file."""
    from bird_recognition.embed.visits import (
        build_visit_report,
        load_visit_group_manifest,
    )

    if not groups:
        raise APIError(
            400,
            "invalid_selection",
            "A reviewed visit-groups manifest is required.",
        )
    try:
        manifest = load_visit_group_manifest(Path(groups))
        store = request.app.state.resources.get_store()
        store.preflight(read_only=True)
        run_data, items = store.inspect_run(run_id)
        return build_visit_report(
            run_data,
            items,
            manifest,
            expected_run_id=run_id,
        )
    except APIError:
        raise
    except Exception as error:
        if "not found" in str(error).casefold():
            raise APIError(404, "not_found", "The run was not found.") from None
        raise APIError(
            400,
            "invalid_selection",
            "The run or reviewed visit groups are not compatible.",
        ) from None
