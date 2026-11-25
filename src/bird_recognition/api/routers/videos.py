"""Video catalog, queue and crop image endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.review_schemas import (
    VideoDetail,
    VideoPage,
    VideoQueue,
)
from bird_recognition.api.review_support import (
    catalog,
    guarded,
    review_states,
    to_detail,
    to_summary,
)
from bird_recognition.api.security import require_api_key
from bird_recognition.review.catalog import VideoFilter

router = APIRouter(
    tags=["videos"],
    dependencies=[Depends(require_api_key)],
)

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetails},
    404: {"model": ProblemDetails},
    503: {"model": ProblemDetails},
}


@router.get(
    "/videos",
    response_model=VideoPage,
    summary="List videos with processing and review state",
    responses=_ERRORS,
)
def list_videos(
    request: Request,
    status: Annotated[
        list[Literal["not_ingested", "no_animals", "animals", "failed"]] | None,
        Query(),
    ] = None,
    review: Literal["unreviewed", "confirmed", "corrected"] | None = None,
    folder: Annotated[str | None, Query(max_length=1024)] = None,
    date_from: Annotated[str | None, Query(alias="from", max_length=40)] = None,
    date_to: Annotated[str | None, Query(alias="to", max_length=40)] = None,
    sort: Literal[
        "capture_start", "basename", "ingested_at", "crop_count"
    ] = "capture_start",
    order: Literal["asc", "desc"] = "asc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VideoPage:
    """Return a filtered page; the UI applies its own triage defaults."""
    reviews = review_states(request)
    filters = VideoFilter(
        statuses=tuple(status or ()),
        review=review,
        folder=folder,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        descending=order == "desc",
        limit=limit,
        offset=offset,
    )
    page, total = guarded(lambda: catalog(request).list_videos(filters, reviews))
    return VideoPage(
        items=[to_summary(request, item) for item in page],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get(
    "/videos/queue",
    response_model=VideoQueue,
    summary="Next unreviewed videos in triage order",
    responses=_ERRORS,
)
def video_queue(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=10)] = 3,
    exclude: Annotated[list[str] | None, Query(max_length=500)] = None,
) -> VideoQueue:
    """No-animal videos first, then oldest capture; skipped ids are excluded."""
    reviews = review_states(request)
    cat = catalog(request)
    items = guarded(lambda: cat.queue(reviews, exclude=exclude or (), limit=limit))
    remaining = guarded(lambda: cat.count_unreviewed(reviews))
    return VideoQueue(
        items=[to_detail(request, item) for item in items], remaining=remaining
    )


@router.get(
    "/videos/{source_id}",
    response_model=VideoDetail,
    summary="Get a video with crops and review history",
    responses=_ERRORS,
)
def get_video(source_id: str, request: Request) -> VideoDetail:
    reviews = review_states(request)
    video = guarded(lambda: catalog(request).get_video(source_id, reviews))
    if video is None:
        raise APIError(404, "not_found", "The video was not found.")
    return to_detail(request, video)


@router.get(
    "/videos/{source_id}/crops/{crop_id}/image",
    response_class=FileResponse,
    summary="Get a privacy-screened crop image of a video",
    responses={
        200: {"description": "Screened crop.", "content": {"image/jpeg": {}}},
        **_ERRORS,
    },
)
def get_video_crop_image(
    source_id: str, crop_id: str, request: Request
) -> FileResponse:
    cat = catalog(request)
    video = guarded(lambda: cat.get_video(source_id))
    path = (
        None if video is None else guarded(lambda: cat.crop_image_path(video, crop_id))
    )
    if path is None:
        raise APIError(404, "not_found", "The crop image was not found.")
    media_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(
        path.suffix.casefold()
    )
    if media_type is None:
        raise APIError(404, "not_found", "The crop image was not found.")
    return FileResponse(path, media_type=media_type)
