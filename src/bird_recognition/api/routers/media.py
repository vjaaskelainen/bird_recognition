"""Unfiltered owner-review media: contact sheets and playback."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.review_schemas import (
    Playback,
    SheetBox,
    SheetLayout,
    SheetTile,
)
from bird_recognition.api.review_support import catalog, guarded
from bird_recognition.api.security import require_media_access
from bird_recognition.review.catalog import VideoRecord
from bird_recognition.review.contact_sheet import SheetUnavailableError

router = APIRouter(
    tags=["media"],
    dependencies=[Depends(require_media_access)],
)

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ProblemDetails},
    403: {"model": ProblemDetails},
    404: {"model": ProblemDetails},
    409: {"model": ProblemDetails},
    503: {"model": ProblemDetails},
}
_UNFILTERED = {"X-Unfiltered-Media": "true"}


def _video(request: Request, source_id: str) -> VideoRecord:
    video = guarded(lambda: catalog(request).get_video(source_id))
    if video is None:
        raise APIError(404, "not_found", "The video was not found.")
    return video


def _sheet(request: Request, source_id: str):
    video = _video(request, source_id)
    resources = request.app.state.resources
    service = resources.get_contact_sheets()
    if service is None:
        raise APIError(503, "cache_unavailable", "The media cache is not configured.")
    cat = catalog(request)
    source = cat.source_path(video)
    if source is None:
        raise APIError(
            409, "source_missing", "The source video is missing or not allowed."
        )
    frames = guarded(lambda: cat.frames(video))
    try:
        return service.sheet(video, frames, source)
    except SheetUnavailableError:
        raise APIError(
            503, "cache_unavailable", "The contact sheet could not be built."
        ) from None


@router.get(
    "/videos/{source_id}/contact-sheet",
    response_class=FileResponse,
    summary="Get an unfiltered contact sheet of sampled frames",
    responses={200: {"content": {"image/jpeg": {}}}, **_ERRORS},
)
def contact_sheet(source_id: str, request: Request) -> FileResponse:
    path, _ = _sheet(request, source_id)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={**_UNFILTERED, "Cache-Control": "private, max-age=3600"},
    )


@router.get(
    "/videos/{source_id}/contact-sheet/layout",
    response_model=SheetLayout,
    summary="Get the contact sheet tile and box layout",
    responses=_ERRORS,
)
def contact_sheet_layout(source_id: str, request: Request) -> SheetLayout:
    _, layout = _sheet(request, source_id)
    return SheetLayout(
        columns=layout.columns,
        tile_width=layout.tile_width,
        tile_height=layout.tile_height,
        tiles=[
            SheetTile(
                index=tile.index,
                frame_number=tile.frame_number,
                elapsed_seconds=tile.elapsed_seconds,
                boxes=[
                    SheetBox(
                        left=box.left,
                        top=box.top,
                        right=box.right,
                        bottom=box.bottom,
                        confidence=box.confidence,
                        category=box.category,
                        qualifies=box.qualifies,
                    )
                    for box in tile.boxes
                ],
            )
            for tile in layout.tiles
        ],
    )


@router.get(
    "/videos/{source_id}/playback",
    response_model=Playback,
    summary="Start or poll a browser-playable copy of the video",
    responses=_ERRORS,
)
def playback(source_id: str, request: Request) -> Playback:
    video = _video(request, source_id)
    service = request.app.state.resources.get_playback()
    if service is None:
        return Playback(
            status="unavailable", reason="The media cache is not configured."
        )
    status, reason = service.request(video)
    return Playback(
        status=status,
        reason=reason,
        url=f"/v1/videos/{source_id}/playback/stream" if status == "ready" else None,
    )


@router.get(
    "/videos/{source_id}/playback/stream",
    response_class=FileResponse,
    summary="Stream the playable video (supports Range)",
    responses={200: {"content": {"video/mp4": {}}}, **_ERRORS},
)
def playback_stream(source_id: str, request: Request) -> FileResponse:
    video = _video(request, source_id)
    service = request.app.state.resources.get_playback()
    path = None if service is None else service.stream_path(video)
    if path is None:
        raise APIError(
            409, "playback_not_ready", "The video is not ready for playback."
        )
    return FileResponse(path, media_type="video/mp4", headers=_UNFILTERED)
