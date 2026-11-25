"""Shared helpers for the video and review routers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import Request

from bird_recognition.api.errors import APIError
from bird_recognition.api.review_schemas import (
    CropCorrection,
    Review,
    VideoCrop,
    VideoDetail,
    VideoSettings,
    VideoSummary,
)
from bird_recognition.review.catalog import (
    ManifestUnavailableError,
    VideoCatalog,
    VideoRecord,
)
from bird_recognition.review.store import (
    CropCorrectionRecord,
    ReviewRecord,
    ReviewStorageError,
)


def catalog(request: Request) -> VideoCatalog:
    return request.app.state.resources.get_catalog()


def review_store(request: Request) -> Any:
    return request.app.state.resources.get_review_store()


def review_states(request: Request) -> dict[str, str]:
    try:
        return review_store(request).review_states()
    except ReviewStorageError:
        raise APIError(
            503, "database_unavailable", "The review database is unavailable."
        ) from None


def manifest_error() -> APIError:
    return APIError(503, "manifest_unavailable", "The video manifest is unavailable.")


def guarded[T](action: Any) -> T:
    """Run a catalog or store call and translate infrastructure failures."""
    try:
        return action()
    except ManifestUnavailableError:
        raise manifest_error() from None
    except ReviewStorageError:
        raise APIError(
            503, "database_unavailable", "The review database is unavailable."
        ) from None


def summary_fields(request: Request, video: VideoRecord) -> dict[str, Any]:
    resources = request.app.state.resources
    return {
        "source_id": video.source_id,
        "path_id": video.path_id,
        "path": video.path,
        "basename": video.basename,
        "folder": video.folder,
        "capture_start": video.capture_start,
        "status": video.status,
        "failure_reason": video.failure_reason,
        "crop_count": video.crop_count,
        "top_label": video.top_label,
        "run_id": video.run_id,
        "ingested_at": video.ingested_at,
        "settings": VideoSettings(
            interval=video.interval, animal_threshold=video.animal_threshold
        ),
        "settings_differ": video.settings_differ,
        "review_state": video.review_state,
        "playback_status": resources.playback_status(video),
        "source_available": video.source_available,
    }


def to_summary(request: Request, video: VideoRecord) -> VideoSummary:
    return VideoSummary(**summary_fields(request, video))


def review_model(record: ReviewRecord) -> Review:
    return Review(**asdict(record))


def correction_model(record: CropCorrectionRecord) -> CropCorrection:
    return CropCorrection(**asdict(record))


def to_detail(request: Request, video: VideoRecord) -> VideoDetail:
    """Build the full detail for an ingested video."""
    cat = catalog(request)
    store = review_store(request)
    source_id = video.source_id or ""
    history = guarded(lambda: store.history(source_id))
    corrections = guarded(lambda: store.current_corrections(source_id))
    current = next((item for item in history if not item.undone), None)
    crops = [
        VideoCrop(
            crop_id=crop.crop_id,
            frame_number=crop.frame_number,
            elapsed_seconds=crop.elapsed_seconds,
            confidence=crop.confidence,
            lighting=crop.lighting,
            image_url=f"/v1/videos/{source_id}/crops/{crop.crop_id}/image",
            current_correction=(
                correction_model(corrections[crop.crop_id])
                if crop.crop_id in corrections
                else None
            ),
        )
        for crop in guarded(lambda: cat.crops(video))
    ]
    return VideoDetail(
        **summary_fields(request, video),
        detection_counts=guarded(lambda: cat.detection_counts(video)),
        crops=crops,
        current_review=review_model(current) if current else None,
        review_history=[review_model(item) for item in history],
    )


def auto_result(video: VideoRecord) -> dict[str, Any]:
    """Snapshot of the automatic result stored with each review."""
    return {
        "status": video.status,
        "crop_count": video.crop_count,
        "top_label": video.top_label,
        "run_id": video.run_id,
        "settings": {
            "interval": video.interval,
            "animal_threshold": video.animal_threshold,
        },
    }
