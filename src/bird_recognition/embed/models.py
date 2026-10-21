"""Typed domain records and interfaces for crop embedding and species tagging."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

type Vector = tuple[float, ...]
type Sha256 = str

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class EmbedError(Exception):
    """Base error for embedding and species-tagging failures."""


class EmbedValidationError(EmbedError, ValueError):
    """Raised when embedding input or a persisted record is invalid."""


class IsolatedCropError(EmbedError):
    """Raised when one crop cannot be read, validated, or processed."""


class SharedModelError(EmbedError):
    """Raised when the shared model cannot be loaded or used for inference."""


class StorageError(EmbedError):
    """Raised when persisted state cannot be read or safely written."""


class PreflightError(StorageError):
    """Raised when a command cannot safely begin because preflight failed."""


class UnconfirmedCommitError(StorageError):
    """Raised when a commit may be durable but its acknowledgement was lost."""


class Lighting(StrEnum):
    """Lighting classification copied from the ingestion manifest."""

    DAY = "day"
    NIGHT = "night"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    """Durable processing-run lifecycle states."""

    RUNNING = "running"
    COMPLETE = "complete"
    NO_INPUT = "no_input"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class RunItemStatus(StrEnum):
    """Durable per-crop lifecycle states."""

    PENDING = "pending"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestedCropSnapshot:
    """Immutable ingestion provenance captured for one retained crop."""

    snapshot_id: Sha256
    crop_id: str
    provenance_sha256: Sha256
    crop_sha256: Sha256
    source_id: str
    source_content_sha256: Sha256
    source_original_path: str
    source_basename: str
    ingest_settings_fingerprint: Sha256
    ingestion_run_id: str
    frame_number: int
    elapsed_seconds: float
    detection_id: str
    detection_category: str
    detection_confidence: float
    detection_box_normalized: tuple[float, float, float, float]
    crop_box_pixels: tuple[int, int, int, int]
    frame_width: int
    frame_height: int
    crop_original_image_path: str
    capture_time: str | None
    capture_timezone: str | None
    source_capture_start: str | None
    source_capture_timezone: str | None
    lighting: Lighting
    imported_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "provenance_sha256",
            "crop_sha256",
            "source_content_sha256",
            "ingest_settings_fingerprint",
        ):
            _validate_sha256(name, getattr(self, name))
        if not self.crop_id or not self.source_id or not self.detection_id:
            raise EmbedValidationError("crop, source, and detection IDs are required")
        if self.frame_number < 0:
            raise EmbedValidationError("frame number must be non-negative")
        if not math.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0:
            raise EmbedValidationError("elapsed time must be finite and non-negative")
        if (
            not math.isfinite(self.detection_confidence)
            or not 0 <= self.detection_confidence <= 1
        ):
            raise EmbedValidationError(
                "detection confidence must be finite and within [0, 1]"
            )
        if len(self.detection_box_normalized) != 4 or any(
            not math.isfinite(value) for value in self.detection_box_normalized
        ):
            raise EmbedValidationError(
                "detection box must contain four finite coordinates"
            )
        if len(self.crop_box_pixels) != 4:
            raise EmbedValidationError("crop bounds must contain four coordinates")
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise EmbedValidationError("frame dimensions must be positive")
        if self.detection_category != "animal":
            raise EmbedValidationError("crop snapshots require an animal detection")


@dataclass(frozen=True, slots=True)
class EmbeddingModelRecord:
    """Versioned identity and runtime contract for an embedding model."""

    model_fingerprint: Sha256
    upstream_name: str
    upstream_revision: str
    checkpoint_sha256: Sha256
    config_sha256: Sha256
    tokenizer_sha256: Sha256
    architecture: str
    dimension: int
    preprocessing_json: str
    tokenizer_json: str
    adapter_version: str
    runtime_json: str
    logit_scale: float
    canonical_json: str

    def __post_init__(self) -> None:
        for name in (
            "model_fingerprint",
            "checkpoint_sha256",
            "config_sha256",
            "tokenizer_sha256",
        ):
            _validate_sha256(name, getattr(self, name))
        if self.dimension <= 0:
            raise EmbedValidationError("model dimension must be positive")
        if not math.isfinite(self.logit_scale) or self.logit_scale <= 0:
            raise EmbedValidationError("model logit scale must be finite and positive")


@dataclass(frozen=True, slots=True)
class SpeciesCandidate:
    """One explicitly configured species identifier and display name."""

    id: str
    name: str


@dataclass(frozen=True, slots=True)
class SpeciesCandidateSet:
    """Canonical, versioned nonempty set of species candidates."""

    candidate_set_fingerprint: Sha256
    schema_version: int
    candidates: tuple[SpeciesCandidate, ...]
    candidates_json: str
    canonical_json: str
    created_at: datetime

    def __post_init__(self) -> None:
        _validate_sha256("candidate_set_fingerprint", self.candidate_set_fingerprint)
        if self.schema_version != 1:
            raise EmbedValidationError("unsupported candidate-set schema version")
        if not self.candidates:
            raise EmbedValidationError("candidate set must not be empty")


@dataclass(frozen=True, slots=True)
class TaggingConfig:
    """Complete immutable model, candidate, scoring, and threshold identity."""

    config_fingerprint: Sha256
    model_fingerprint: Sha256
    candidate_set_fingerprint: Sha256
    scoring_fingerprint: Sha256
    prompt_template: str
    prompt_version: str
    effective_logit_scale: float
    scoring_json: str
    threshold: float
    canonical_json: str

    def __post_init__(self) -> None:
        for name in (
            "config_fingerprint",
            "model_fingerprint",
            "candidate_set_fingerprint",
            "scoring_fingerprint",
        ):
            _validate_sha256(name, getattr(self, name))
        if (
            not math.isfinite(self.effective_logit_scale)
            or self.effective_logit_scale <= 0
        ):
            raise EmbedValidationError(
                "effective logit scale must be finite and positive"
            )
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1:
            raise EmbedValidationError("threshold must be finite and within [0, 1]")


@dataclass(frozen=True, slots=True)
class CropRepresentation:
    """One completed image embedding tied to an immutable crop and model."""

    representation_id: UUID
    snapshot_id: Sha256
    model_fingerprint: Sha256
    embedding: Vector
    processed_at: datetime
    created_run_id: UUID

    def __post_init__(self) -> None:
        _validate_sha256("snapshot_id", self.snapshot_id)
        _validate_sha256("model_fingerprint", self.model_fingerprint)


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Logit and candidate-relative softmax score for one species candidate."""

    id: str
    logit: float
    score: float


@dataclass(frozen=True, slots=True)
class SpeciesDecision:
    """Persistable species assignment and complete candidate score map."""

    decision_id: UUID
    representation_id: UUID
    config_fingerprint: Sha256
    assigned_species_id: str | None
    best_candidate_id: str | None
    confidence: float
    tied_candidate_ids: tuple[str, ...]
    candidate_scores: tuple[CandidateScore, ...]
    reason: str
    warnings: tuple[str, ...]
    processed_at: datetime
    created_run_id: UUID

    def __post_init__(self) -> None:
        _validate_sha256("config_fingerprint", self.config_fingerprint)


@dataclass(frozen=True, slots=True)
class RunFailure:
    """Sanitized, stable summary of a crop or run failure."""

    crop_id: str | None
    code: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    """Durable processing-run status, configuration, and aggregate counters."""

    run_id: UUID
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    config_fingerprint: Sha256
    manifest_locator: Path
    crop_root: Path | None
    selection_fingerprint: Sha256
    selected_count: int
    completed_count: int
    skipped_count: int
    failed_count: int
    assigned_count: int
    unknown_count: int
    failures: tuple[RunFailure, ...]
    sanitized_settings_json: str
    durable_status_confirmed: bool = True
    unconfirmed_crop_ids: tuple[str, ...] = ()
    model_fingerprint: Sha256 | None = None
    candidate_set_fingerprint: Sha256 | None = None
    scoring_fingerprint: Sha256 | None = None
    threshold: float | None = None
    candidate_count: int = 0

    def __post_init__(self) -> None:
        _validate_sha256("config_fingerprint", self.config_fingerprint)
        _validate_sha256("selection_fingerprint", self.selection_fingerprint)
        counts = (
            self.selected_count,
            self.completed_count,
            self.skipped_count,
            self.failed_count,
            self.assigned_count,
            self.unknown_count,
        )
        if any(count < 0 for count in counts):
            raise EmbedValidationError("run counts must be non-negative")
        if self.assigned_count + self.unknown_count != self.completed_count:
            raise EmbedValidationError(
                "assigned and unknown counts must equal completed"
            )
        for name in (
            "model_fingerprint",
            "candidate_set_fingerprint",
            "scoring_fingerprint",
        ):
            value = getattr(self, name)
            if value is not None:
                _validate_sha256(name, value)
        if self.threshold is not None and (
            not math.isfinite(self.threshold) or not 0 <= self.threshold <= 1
        ):
            raise EmbedValidationError("run threshold must be finite and within [0, 1]")
        if self.candidate_count < 0:
            raise EmbedValidationError("candidate count must be non-negative")
        if (
            self.completed_count + self.skipped_count + self.failed_count
            > self.selected_count
        ):
            raise EmbedValidationError("run outcome counts exceed selected crops")
        if (
            self.status
            in (
                RunStatus.COMPLETE,
                RunStatus.NO_INPUT,
                RunStatus.PARTIAL_FAILURE,
            )
            and self.pending_count
        ):
            raise EmbedValidationError("finished run states cannot have pending crops")
        if self.status is RunStatus.NO_INPUT and self.selected_count != 0:
            raise EmbedValidationError("no-input runs must not select crops")
        if self.status is RunStatus.COMPLETE and self.failed_count:
            raise EmbedValidationError("complete runs cannot contain failed crops")
        if self.status is RunStatus.PARTIAL_FAILURE and (
            self.failed_count == 0 or self.completed_count + self.skipped_count == 0
        ):
            raise EmbedValidationError(
                "partial-failure runs require both failures and successful items"
            )

    @property
    def pending_count(self) -> int:
        """Return selected crops that have not completed, skipped, or failed."""
        return (
            self.selected_count
            - self.completed_count
            - self.skipped_count
            - self.failed_count
        )


@dataclass(frozen=True, slots=True)
class RunItem:
    """Per-crop run state and its expected provenance or completed decision."""

    run_id: UUID
    crop_id: str
    expected_snapshot_id: Sha256 | None
    expected_provenance_sha256: Sha256
    resolved_input_locator: Path
    status: RunItemStatus
    decision_id: UUID | None
    failure_code: str | None
    failure_reason: str | None
    started_at: datetime
    completed_at: datetime | None

    def __post_init__(self) -> None:
        _validate_sha256("expected_provenance_sha256", self.expected_provenance_sha256)
        if self.expected_snapshot_id is not None:
            _validate_sha256("expected_snapshot_id", self.expected_snapshot_id)
        if not self.crop_id:
            raise EmbedValidationError("run item crop ID is required")
        has_decision = self.decision_id is not None
        has_failure = self.failure_code is not None and self.failure_reason is not None
        if self.status in (RunItemStatus.COMPLETED, RunItemStatus.SKIPPED):
            if (
                not has_decision
                or self.expected_snapshot_id is None
                or self.failure_code is not None
                or self.failure_reason is not None
            ):
                raise EmbedValidationError(
                    "completed and skipped items require a decision only"
                )
        elif has_decision:
            raise EmbedValidationError(
                "pending and failed items cannot reference a decision"
            )
        if self.status is RunItemStatus.FAILED and not has_failure:
            raise EmbedValidationError("failed items require a failure code and reason")
        if self.status is not RunItemStatus.FAILED and (
            self.failure_code is not None or self.failure_reason is not None
        ):
            raise EmbedValidationError("only failed items may contain failure details")


class ModelProtocol(Protocol):
    """Inference interface implemented by the local model and test doubles."""

    @property
    def identity(self) -> EmbeddingModelRecord:
        """Return the validated, immutable model identity."""

    def encode_image(self, image: object) -> Vector:
        """Return the normalized image embedding for one crop image."""

    def encode_texts(self, prompts: tuple[str, ...]) -> tuple[Vector, ...]:
        """Return normalized text embeddings in prompt order."""


class StoreProtocol(Protocol):
    """Persistence interface for preflight, indexing, and durable run updates."""

    def preflight(self, *, read_only: bool = False) -> None:
        """Verify the existing database contract without changing its schema."""

    def acquire_writer_lock(self) -> None:
        """Acquire the nonblocking database-wide indexing lock."""

    def release_writer_lock(self) -> None:
        """Release the indexing lock when held by this store session."""

    def register_run(
        self,
        run: ProcessingRun,
        items: tuple[RunItem, ...],
        model: EmbeddingModelRecord,
        candidates: SpeciesCandidateSet,
        config: TaggingConfig,
    ) -> None:
        """Persist a run and its pending items after successful preflight."""

    def get_completed_decision(
        self,
        snapshot_id: Sha256,
        model_fingerprint: Sha256,
        config_fingerprint: Sha256,
    ) -> SpeciesDecision | None:
        """Return an exact compatible durable decision, if one exists."""

    def get_compatible_representation(
        self, snapshot_id: Sha256, model_fingerprint: Sha256
    ) -> CropRepresentation | None:
        """Return a persisted image vector compatible with snapshot and model."""

    def get_compatible_score_map(
        self, representation_id: UUID, scoring_fingerprint: Sha256
    ) -> tuple[CandidateScore, ...] | None:
        """Return a validated score map for the exact scoring identity, if any."""

    def commit_crop_result(
        self,
        snapshot: IngestedCropSnapshot,
        representation: CropRepresentation,
        decision: SpeciesDecision,
        item: RunItem,
    ) -> bool:
        """Atomically persist crop provenance, result, item, and run counters."""

    def mark_item_failed(self, item: RunItem) -> None:
        """Persist one isolated crop failure and update its run counters."""

    def mark_item_skipped(self, item: RunItem) -> None:
        """Persist a skipped item linked to its existing durable decision."""

    def finalize_run(self, run: ProcessingRun) -> None:
        """Persist the final run state and counters."""

    def list_runs(self) -> list[dict[str, object]]:
        """Return persisted run summaries newest first."""

    def inspect_run(
        self, run_id: UUID, crop_id: str | None = None
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Return persisted run and item details without external asset access."""


def _validate_sha256(name: str, value: Sha256) -> None:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise EmbedValidationError(f"{name} must be a lowercase SHA-256 digest")
