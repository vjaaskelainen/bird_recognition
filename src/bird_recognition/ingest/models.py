"""Validated records and settings shared by ingestion components."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class IngestError(Exception):
    """Base error for ingestion failures."""


class ValidationError(IngestError, ValueError):
    """Raised when user input or a persisted record is invalid."""


class ProcessingError(IngestError):
    """Raised when a source frame cannot be safely processed."""


class DetectionError(ProcessingError):
    """Raised when detector setup or inference fails."""


class StorageError(ProcessingError):
    """Raised when a complete result cannot be persisted."""


class DetectionCategory(StrEnum):
    ANIMAL = "animal"
    PERSON = "person"
    OTHER = "other"


class FrameOutcome(StrEnum):
    PERSON_EXCLUDED = "person_excluded"
    NO_ANIMAL = "no_animal"
    RETAINED = "retained"
    FAILED = "failed"


class Lighting(StrEnum):
    DAY = "day"
    NIGHT = "night"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IngestSettings:
    interval: float = 1.0
    animal_threshold: float = 0.2
    person_threshold: float = 0.2
    crop_context: float | None = None
    crop_policy: str = "context-v1"
    extensions: tuple[str, ...] = (
        ".mp4",
        ".mov",
        ".m4v",
        ".mkv",
        ".avi",
        ".mpeg",
        ".mpg",
    )
    model_path: Path | None = None
    model_config_path: Path | None = None
    model_variant: str = "unconfigured"
    detector_name: str = "MegaDetector"
    detector_version: str = "unconfigured"
    model_sha256: str | None = None
    model_config_sha256: str | None = None
    lighting_rule: str = "pixel-evidence-v1"
    lighting_settings: tuple[tuple[str, float], ...] = (
        ("day_min_mean_saturation", 0.16),
        ("day_min_luma", 0.28),
        ("night_max_mean_saturation", 0.09),
        ("night_max_luma", 0.82),
        ("night_min_luma", 0.03),
    )

    def __post_init__(self) -> None:
        if not math.isfinite(self.interval) or self.interval <= 0:
            raise ValidationError("sampling interval must be positive and finite")
        for name, value in (
            ("animal threshold", self.animal_threshold),
            ("person threshold", self.person_threshold),
        ):
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValidationError(f"{name} must be finite and within [0, 1]")
        normalized = tuple(
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in self.extensions
        )
        if not normalized or any(extension == "." for extension in normalized):
            raise ValidationError("at least one valid video extension is required")
        object.__setattr__(self, "extensions", tuple(sorted(set(normalized))))
        if self.crop_policy not in {"legacy-tight-v1", "context-v1"}:
            raise ValidationError("unsupported crop policy version")
        context = self.crop_context
        if context is None:
            context = 0.1 if self.crop_policy == "context-v1" else 0.0
        if (
            isinstance(context, bool)
            or not isinstance(context, (int, float))
            or not math.isfinite(context)
            or context < 0
        ):
            raise ValidationError("crop context must be finite and non-negative")
        if self.crop_policy == "legacy-tight-v1" and context != 0:
            raise ValidationError("legacy-tight-v1 requires zero crop context")
        object.__setattr__(self, "crop_context", context)


@dataclass(frozen=True, slots=True)
class Detection:
    category: DetectionCategory
    confidence: float
    box: tuple[float, float, float, float]
    detection_id: str = ""
    qualifies: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValidationError(
                "detection confidence must be finite and within [0, 1]"
            )
        if len(self.box) != 4 or any(not math.isfinite(value) for value in self.box):
            raise ValidationError("detection box must contain four finite coordinates")
        if self.box[2] <= self.box[0] or self.box[3] <= self.box[1]:
            raise ValidationError("detection box must have positive area")


@dataclass(frozen=True, slots=True)
class SampledFrame:
    frame_number: int
    elapsed_seconds: float
    width: int
    height: int
    image: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.frame_number < 0:
            raise ValidationError("frame number must be non-negative")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise ValidationError("elapsed time must be finite and non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValidationError("frame dimensions must be positive")


@dataclass(frozen=True, slots=True)
class CaptureTime:
    local_time: str | None = None
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class FrameResult:
    frame_number: int
    outcome: FrameOutcome
    detections: tuple[Detection, ...] = ()
    crops: tuple[object, ...] = field(default_factory=tuple, repr=False)
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        if self.frame_number < 0:
            raise ValidationError("frame number must be non-negative")
        if self.outcome is FrameOutcome.FAILED and not self.failure_reason:
            raise ValidationError("failed frames require a failure reason")
        if self.outcome is not FrameOutcome.FAILED and self.failure_reason is not None:
            raise ValidationError("only failed frames may have a failure reason")
        if self.outcome is not FrameOutcome.RETAINED and self.crops:
            raise ValidationError("only retained frames may contain crops")


@dataclass(frozen=True, slots=True)
class RunSummary:
    processed_sources: int = 0
    skipped_sources: int = 0
    failed_sources: int = 0
    sampled_frames: int = 0
    person_excluded_frames: int = 0
    no_animal_frames: int = 0
    retained_frames: int = 0
    failed_frames: int = 0
    crops: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.processed_sources,
            self.skipped_sources,
            self.failed_sources,
            self.sampled_frames,
            self.person_excluded_frames,
            self.no_animal_frames,
            self.retained_frames,
            self.failed_frames,
            self.crops,
        )
        if any(count < 0 for count in counts):
            raise ValidationError("summary counts must be non-negative")
        if self.sampled_frames != sum(
            (
                self.person_excluded_frames,
                self.no_animal_frames,
                self.retained_frames,
                self.failed_frames,
            )
        ):
            raise ValidationError("frame outcome counts must equal sampled frames")
