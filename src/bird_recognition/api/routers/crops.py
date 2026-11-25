"""Privacy-screened crop metadata and image endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.schemas import CropDetail
from bird_recognition.api.security import require_api_key
from bird_recognition.inspection import build_inspection_payload

router = APIRouter(
    tags=["crops"],
    dependencies=[Depends(require_api_key)],
)


@router.get(
    "/crops/{crop_id}",
    response_model=CropDetail,
    summary="Get crop metadata",
    responses={
        401: {"model": ProblemDetails},
        404: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def get_crop(crop_id: str, request: Request) -> dict[str, object]:
    """Find a crop from the newest indexed run and return CLI-compatible details."""
    run_data, item = _find_crop(request, crop_id)
    return build_inspection_payload(run_data, [item])


@router.get(
    "/crops/{crop_id}/image",
    response_class=FileResponse,
    summary="Get a stored privacy-screened crop image",
    responses={
        200: {
            "description": "Stored screened crop image.",
            "content": {
                "image/jpeg": {},
                "image/png": {},
            },
        },
        401: {"model": ProblemDetails},
        404: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def get_crop_image(crop_id: str, request: Request) -> FileResponse:
    """Serve only an image resolved beneath its recorded crop root."""
    run_data, item = _find_crop(request, crop_id)
    provenance = item.get("provenance")
    crop_root = run_data.get("crop_root")
    relative = (
        provenance.get("crop_original_image_path")
        if isinstance(provenance, dict)
        else None
    )
    if not isinstance(crop_root, str) or not isinstance(relative, str):
        raise APIError(404, "not_found", "The stored crop image was not found.")
    root = Path(crop_root).resolve()
    candidate = Path(relative)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        image_path = candidate.resolve(strict=True)
        image_path.relative_to(root)
    except OSError, ValueError:
        raise APIError(
            404, "not_found", "The stored crop image was not found."
        ) from None
    if not image_path.is_file():
        raise APIError(404, "not_found", "The stored crop image was not found.")
    media_type = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }.get(image_path.suffix.casefold())
    if media_type is None:
        raise APIError(404, "not_found", "The stored crop image was not found.")
    return FileResponse(image_path, media_type=media_type)


def _find_crop(request: Request, crop_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        store = request.app.state.resources.get_store()
        for summary in store.list_runs():
            run_id = UUID(summary["run_id"])
            try:
                run_data, items = store.inspect_run(run_id, crop_id)
            except Exception as error:
                if "not found" in str(error).casefold():
                    continue
                raise
            if items:
                return run_data, items[0]
    except APIError:
        raise
    except Exception:
        raise APIError(
            503, "database_unavailable", "Crop metadata is unavailable."
        ) from None
    raise APIError(404, "not_found", "The crop was not found.")
