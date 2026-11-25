"""Response and request models for the owner review UI endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VideoStatus = Literal["not_ingested", "no_animals", "animals", "failed"]
ReviewState = Literal["unreviewed", "confirmed", "corrected"]
PlaybackStatus = Literal[
    "ready", "converting", "failed", "unavailable", "source_missing", "not_started"
]


class VideoSettings(BaseModel):
    """Effective ingestion settings of a video's latest run."""

    interval: float | None
    animal_threshold: float | None


class VideoSummary(BaseModel):
    """One video in a list."""

    source_id: str | None
    path_id: str
    path: str
    basename: str
    folder: str
    capture_start: str | None
    status: VideoStatus
    failure_reason: str | None
    crop_count: int
    top_label: str | None
    run_id: str | None
    ingested_at: str | None
    settings: VideoSettings
    settings_differ: bool
    review_state: ReviewState
    playback_status: PlaybackStatus
    source_available: bool


class VideoPage(BaseModel):
    """Paged video list."""

    items: list[VideoSummary]
    limit: int
    offset: int
    total: int


class CropCorrection(BaseModel):
    """A stored per-crop truth label."""

    correction_id: str
    crop_id: str
    source_id: str
    truth_kind: Literal["species", "out_of_list", "unidentifiable"]
    species_id: str | None
    created_at: str


class VideoCrop(BaseModel):
    """A privacy-screened crop of a video."""

    crop_id: str
    frame_number: int
    elapsed_seconds: float
    confidence: float
    lighting: str
    image_url: str
    current_correction: CropCorrection | None


class Review(BaseModel):
    """A stored owner review."""

    review_id: str
    source_id: str
    outcome: Literal["confirmed", "corrected"]
    correction_kind: Literal["no_animal", "animal_missed", "species_present"] | None
    species: list[str]
    missed_times: list[float]
    note: str | None
    auto_result: dict[str, object]
    created_at: str
    bulk_id: str | None
    undone: bool


class VideoDetail(VideoSummary):
    """A video with crops and review history."""

    detection_counts: dict[str, int]
    crops: list[VideoCrop]
    current_review: Review | None
    review_history: list[Review]


class VideoQueue(BaseModel):
    """The next videos to review."""

    items: list[VideoDetail]
    remaining: int


class ReviewRequest(BaseModel):
    """A reviewer decision."""

    model_config = ConfigDict(extra="forbid")

    outcome: Literal["confirmed", "corrected"]
    correction_kind: Literal["no_animal", "animal_missed", "species_present"] | None = (
        None
    )
    species: list[str] = Field(default_factory=list, max_length=50)
    missed_times: list[float] = Field(default_factory=list, max_length=200)
    note: str | None = None


class BulkReviewRequest(BaseModel):
    """Bulk confirmation of automatic no-animal results."""

    model_config = ConfigDict(extra="forbid")

    source_ids: list[str] = Field(min_length=1, max_length=500)
    outcome: Literal["confirmed"]


class BulkReviewResponse(BaseModel):
    """Bulk confirmation result."""

    bulk_id: str
    reviews: list[Review]


class CorrectionRequest(BaseModel):
    """A per-crop truth label."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    truth_kind: Literal["species", "out_of_list", "unidentifiable"]
    species_id: str | None = None


class SheetBox(BaseModel):
    """A normalized detection box."""

    left: float
    top: float
    right: float
    bottom: float
    confidence: float
    category: str
    qualifies: bool


class SheetTile(BaseModel):
    """One contact sheet tile."""

    index: int
    frame_number: int
    elapsed_seconds: float
    boxes: list[SheetBox]


class SheetLayout(BaseModel):
    """Contact sheet geometry so the UI can overlay boxes."""

    columns: int
    tile_width: int
    tile_height: int
    tiles: list[SheetTile]


class Playback(BaseModel):
    """Playback conversion state."""

    status: PlaybackStatus
    reason: str | None = None
    url: str | None = None
