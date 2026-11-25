"""Search endpoint backed by existing local retrieval behavior."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.schemas import SearchRequest, SearchResponse
from bird_recognition.api.security import require_api_key
from bird_recognition.embed.models import (
    Lighting,
    PreflightError,
    StorageError,
)
from bird_recognition.embed.models import (
    SearchRequest as DomainSearchRequest,
)
from bird_recognition.payloads import (
    _preflight_code,
    _search_failure_code,
    _search_payload,
)

router = APIRouter(
    tags=["search"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="Search indexed crops",
    description=(
        "Searches one indexed run. Similarity and species confidence are not "
        "biological probabilities."
    ),
    responses={
        400: {"model": ProblemDetails},
        401: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def search(
    body: SearchRequest,
    request: Request,
) -> dict[str, object]:
    """Return CLI-equivalent search results and caveats."""
    from uuid import UUID

    from bird_recognition.embed.search import execute_search

    resources = request.app.state.resources
    try:
        domain_request = DomainSearchRequest(
            query=body.query,
            run_id=UUID(str(body.run_id)),
            start_date=body.start_date,
            end_date=body.end_date,
            lighting=Lighting(body.lighting) if body.lighting else None,
            species_id=body.species_id,
            limit=body.limit,
        )
        store = resources.get_store()
        try:
            store.preflight(read_only=True)
        except StorageError as error:
            raise PreflightError(str(error)) from None
        context, candidates = store.load_search_collection(domain_request)
        model = resources.get_model(context.model_input_view)
        outcome = execute_search(
            domain_request,
            model,
            store,
            context=context,
            candidates=candidates,
        )
    except APIError:
        raise
    except Exception as error:
        code = (
            _preflight_code(error)
            if isinstance(error, PreflightError)
            else _search_failure_code(error)
        )
        status = 503 if code in {"database_unavailable", "model_unavailable"} else 400
        raise APIError(
            status,
            code,
            "The search could not be completed."
            if status == 503
            else "The search request is not compatible with the selected run.",
        ) from None
    return _with_video_links(request, _search_payload(outcome))


def _with_video_links(
    request: Request, payload: dict[str, object]
) -> dict[str, object]:
    """Add optional source_id and elapsed_seconds when the manifest knows the crop."""
    results = payload.get("results")
    resources = request.app.state.resources
    if not isinstance(results, list) or resources.settings.manifest is None:
        return payload
    try:
        locations = resources.get_catalog().crop_locations(
            [str(item.get("crop_id")) for item in results]
        )
    except Exception:
        return payload
    for item in results:
        found = locations.get(str(item.get("crop_id")))
        if found is not None:
            item["source_id"], item["elapsed_seconds"] = found
    return payload
