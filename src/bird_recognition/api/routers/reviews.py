"""Owner reviews and crop corrections."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.review_schemas import (
    BulkReviewRequest,
    BulkReviewResponse,
    CorrectionRequest,
    CropCorrection,
    Review,
    ReviewRequest,
)
from bird_recognition.api.review_support import (
    auto_result,
    catalog,
    correction_model,
    guarded,
    review_model,
    review_store,
)
from bird_recognition.api.security import require_api_key
from bird_recognition.review.store import (
    AlreadyUndoneError,
    ReviewInput,
    ReviewNotFoundError,
    ReviewValidationError,
    validate_correction,
    validate_review,
)

router = APIRouter(
    tags=["reviews"],
    dependencies=[Depends(require_api_key)],
)

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetails},
    403: {"model": ProblemDetails},
    404: {"model": ProblemDetails},
    409: {"model": ProblemDetails},
    422: {"model": ProblemDetails},
    503: {"model": ProblemDetails},
}


def _video(request: Request, source_id: str):
    video = guarded(lambda: catalog(request).get_video(source_id))
    if video is None:
        raise APIError(404, "not_found", "The video was not found.")
    return video


@router.post(
    "/videos/{source_id}/reviews",
    response_model=Review,
    status_code=201,
    summary="Record a review of a video",
    responses=_ERRORS,
)
def create_review(source_id: str, body: ReviewRequest, request: Request) -> Review:
    video = _video(request, source_id)
    data = ReviewInput(
        outcome=body.outcome,
        correction_kind=body.correction_kind,
        species=tuple(body.species),
        missed_times=tuple(body.missed_times),
        note=body.note,
    )
    try:
        validate_review(data)
    except ReviewValidationError as error:
        raise APIError(422, "invalid_review", str(error)) from None
    record = guarded(
        lambda: review_store(request).add_review(source_id, data, auto_result(video))
    )
    return review_model(record)


@router.get(
    "/videos/{source_id}/reviews",
    response_model=list[Review],
    summary="List a video's review history, newest first",
    responses=_ERRORS,
)
def list_reviews(source_id: str, request: Request) -> list[Review]:
    _video(request, source_id)
    return [
        review_model(item)
        for item in guarded(lambda: review_store(request).history(source_id))
    ]


@router.post(
    "/reviews/bulk",
    response_model=BulkReviewResponse,
    status_code=201,
    summary="Confirm many automatic no-animal results at once",
    responses=_ERRORS,
)
def bulk_review(body: BulkReviewRequest, request: Request) -> BulkReviewResponse:
    cat = catalog(request)
    unique = list(dict.fromkeys(body.source_ids))
    items: list[tuple[str, dict[str, object]]] = []
    offenders: list[dict[str, str]] = []
    for source_id in unique:
        video = guarded(lambda sid=source_id: cat.get_video(sid))
        if video is None:
            offenders.append({"source_id": source_id, "reason": "not found"})
        elif video.status != "no_animals":
            offenders.append(
                {"source_id": source_id, "reason": f"status is {video.status}"}
            )
        else:
            items.append((source_id, auto_result(video)))
    if offenders:
        raise APIError(
            422,
            "bulk_not_allowed",
            "Bulk confirmation is only allowed for no-animal videos.",
            errors=offenders,
        )
    bulk_id, records = guarded(lambda: review_store(request).add_bulk(items))
    return BulkReviewResponse(
        bulk_id=bulk_id, reviews=[review_model(item) for item in records]
    )


@router.post(
    "/reviews/{review_id}/undo",
    status_code=204,
    summary="Undo a review",
    responses=_ERRORS,
)
def undo_review(review_id: str, request: Request) -> Response:
    try:
        guarded(lambda: review_store(request).undo(review_id))
    except ReviewNotFoundError:
        raise APIError(404, "not_found", "The review was not found.") from None
    except AlreadyUndoneError:
        raise APIError(
            409, "already_undone", "The review was already undone."
        ) from None
    return Response(status_code=204)


@router.put(
    "/crops/{crop_id}/correction",
    response_model=CropCorrection,
    status_code=201,
    summary="Record the true label of a crop",
    responses=_ERRORS,
)
def put_correction(
    crop_id: str, body: CorrectionRequest, request: Request
) -> CropCorrection:
    cat = catalog(request)
    video = _video(request, body.source_id)
    if not any(crop.crop_id == crop_id for crop in guarded(lambda: cat.crops(video))):
        raise APIError(404, "not_found", "The crop was not found in the video.")
    try:
        validate_correction(body.truth_kind, body.species_id)
    except ReviewValidationError as error:
        raise APIError(422, "invalid_correction", str(error)) from None
    record = guarded(
        lambda: review_store(request).set_correction(
            crop_id, body.source_id, body.truth_kind, body.species_id
        )
    )
    return correction_model(record)


@router.delete(
    "/crops/{crop_id}/correction",
    status_code=204,
    summary="Undo the current crop correction",
    responses=_ERRORS,
)
def delete_correction(crop_id: str, request: Request) -> Response:
    try:
        guarded(lambda: review_store(request).clear_correction(crop_id))
    except ReviewNotFoundError:
        raise APIError(404, "not_found", "The crop has no correction.") from None
    return Response(status_code=204)


__all__ = ["router"]
