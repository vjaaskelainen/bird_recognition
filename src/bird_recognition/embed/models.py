"""Typed domain records and interfaces for crop embedding and species tagging."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol
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


class SearchError(EmbedError):
    """Base error for text-search failures."""


class SearchValidationError(SearchError, ValueError):
    """Raised when a search query, filter, or result contract is invalid."""


class SearchContextError(SearchValidationError):
    """Raised when a selected run or tagging context is invalid or incompatible."""


class SearchOperationalError(SearchError):
    """Raised when search cannot complete because of an operational failure."""


class SearchRepresentationError(SearchOperationalError):
    """Raised when the selected run has no compatible crop representations."""


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

    @property
    def case_id(self) -> Sha256:
        """Return the stable identity shared by crop-policy variants."""
        from bird_recognition.ingest.manifest import stable_case_id

        return stable_case_id(
            self.source_content_sha256,
            self.frame_number,
            self.detection_id,
            self.detection_box_normalized,
        )


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
    """One explicitly configured species or coarse-category candidate."""

    id: str
    name: str | None = None
    kind: Literal["species", "category"] = "species"
    common_name: str | None = None
    taxonomic_description: str | None = None
    category: Literal["bird", "mammal"] | None = None

    def __post_init__(self) -> None:
        candidate_id = self.id.strip() if isinstance(self.id, str) else ""
        if not candidate_id or candidate_id.casefold() == "unknown":
            raise EmbedValidationError("candidate ID must be nonblank and not unknown")
        object.__setattr__(self, "id", candidate_id)
        if self.kind not in ("species", "category"):
            raise EmbedValidationError("candidate kind must be species or category")
        common_name = self.common_name
        name = self.name
        if common_name is None and name is not None:
            common_name = name
        if name is None and common_name is not None:
            name = common_name
        if name is None or common_name is None:
            raise EmbedValidationError("candidate name or common name is required")
        if name.strip() != common_name.strip():
            raise EmbedValidationError("candidate name and common name must match")
        for field_name, value in (("name", name), ("common name", common_name)):
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise EmbedValidationError(
                        f"candidate {field_name} must not be blank"
                    )
        if common_name is not None:
            common_name = common_name.strip()
            name = common_name
        if self.taxonomic_description is not None:
            if (
                not isinstance(self.taxonomic_description, str)
                or not self.taxonomic_description.strip()
            ):
                raise EmbedValidationError(
                    "candidate taxonomic description must not be blank"
                )
            object.__setattr__(
                self, "taxonomic_description", self.taxonomic_description.strip()
            )
        if self.kind == "category":
            if self.category not in ("bird", "mammal"):
                raise EmbedValidationError("category candidates require bird or mammal")
        elif self.category is not None:
            raise EmbedValidationError("species candidates cannot have a category")
        object.__setattr__(self, "common_name", common_name)
        object.__setattr__(self, "name", name)


@dataclass(frozen=True, slots=True)
class SpeciesCandidateSet:
    """Canonical, versioned nonempty set of typed candidates."""

    candidate_set_fingerprint: Sha256
    schema_version: int
    candidates: tuple[SpeciesCandidate, ...]
    candidates_json: str
    canonical_json: str
    created_at: datetime

    def __post_init__(self) -> None:
        _validate_sha256("candidate_set_fingerprint", self.candidate_set_fingerprint)
        if type(self.schema_version) is not int or self.schema_version not in (1, 2):
            raise EmbedValidationError("unsupported candidate-set schema version")
        if not self.candidates:
            raise EmbedValidationError("candidate set must not be empty")
        candidate_ids = [candidate.id.casefold() for candidate in self.candidates]
        candidate_names = [
            (candidate.common_name or candidate.name or "").casefold()
            for candidate in self.candidates
        ]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise EmbedValidationError("candidate IDs must be unique")
        if len(set(candidate_names)) != len(candidate_names):
            raise EmbedValidationError("candidate names must be unique")
        if self.schema_version == 1:
            if any(
                candidate.kind != "species"
                or candidate.name is None
                or candidate.taxonomic_description is not None
                or candidate.category is not None
                for candidate in self.candidates
            ):
                raise EmbedValidationError("schema-1 candidates must use legacy names")
            return
        if any(
            candidate.common_name is None or candidate.taxonomic_description is None
            for candidate in self.candidates
        ):
            raise EmbedValidationError(
                "schema-2 candidates require common names and taxonomic descriptions"
            )
        categories = [
            candidate.category
            for candidate in self.candidates
            if candidate.kind == "category"
        ]
        if sorted(categories) != ["bird", "mammal"]:
            raise EmbedValidationError(
                "schema-2 candidate sets require one bird and one mammal category"
            )


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
    minimum_crop_width: int = 32
    minimum_crop_height: int = 32
    reference_set_fingerprint: Sha256 | None = None
    reference_split_mode: Literal["source_video", "recording_day"] | None = None
    reference_min_similarity: float | None = None
    reference_min_agreement: float | None = None

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
        if (
            type(self.minimum_crop_width) is not int
            or type(self.minimum_crop_height) is not int
            or self.minimum_crop_width <= 0
            or self.minimum_crop_height <= 0
        ):
            raise EmbedValidationError(
                "minimum crop dimensions must be positive integers"
            )
        reference_values = (
            self.reference_set_fingerprint,
            self.reference_split_mode,
            self.reference_min_similarity,
            self.reference_min_agreement,
        )
        if any(value is not None for value in reference_values):
            if (
                self.reference_set_fingerprint is None
                or not _SHA256_PATTERN.fullmatch(self.reference_set_fingerprint)
                or self.reference_split_mode not in {"source_video", "recording_day"}
                or any(
                    value is None or not math.isfinite(value) or not 0 <= value <= 1
                    for value in (
                        self.reference_min_similarity,
                        self.reference_min_agreement,
                    )
                )
            ):
                raise EmbedValidationError("reference setup identity is invalid")


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
    confidence: float | None
    tied_candidate_ids: tuple[str, ...]
    candidate_scores: tuple[CandidateScore, ...]
    reason: str
    warnings: tuple[str, ...]
    processed_at: datetime
    created_run_id: UUID
    decision_path: Literal["zero_shot", "reference_match", "zero_shot_fallback"] = (
        "zero_shot"
    )
    reference_set_fingerprint: Sha256 | None = None
    reference_split_mode: Literal["source_video", "recording_day"] | None = None
    reference_similarity: float | None = None
    reference_agreement: float | None = None
    reference_neighbor_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_sha256("config_fingerprint", self.config_fingerprint)
        if self.decision_path not in {
            "zero_shot",
            "reference_match",
            "zero_shot_fallback",
        }:
            raise EmbedValidationError("decision path is invalid")
        if self.decision_path == "zero_shot":
            if (
                any(
                    value is not None
                    for value in (
                        self.reference_set_fingerprint,
                        self.reference_split_mode,
                        self.reference_similarity,
                        self.reference_agreement,
                    )
                )
                or self.reference_neighbor_ids
            ):
                raise EmbedValidationError(
                    "zero-shot decision has reference provenance"
                )
        else:
            if (
                self.reference_set_fingerprint is None
                or not _SHA256_PATTERN.fullmatch(self.reference_set_fingerprint)
                or self.reference_split_mode not in {"source_video", "recording_day"}
            ):
                raise EmbedValidationError(
                    "reference decision provenance is incomplete"
                )
            for name in ("reference_similarity", "reference_agreement"):
                value = getattr(self, name)
                if value is not None and not math.isfinite(value):
                    raise EmbedValidationError(
                        "reference decision metrics must be finite"
                    )
            if (
                self.reference_similarity is not None
                and not -1 <= self.reference_similarity <= 1
            ):
                raise EmbedValidationError(
                    "reference similarity must be within [-1, 1]"
                )
            if (
                self.reference_agreement is not None
                and not 0 <= self.reference_agreement <= 1
            ):
                raise EmbedValidationError("reference agreement must be within [0, 1]")
            if self.decision_path == "reference_match" and (
                self.assigned_species_id is None
                or self.reason != "reference_match"
                or self.reference_similarity is None
                or self.reference_agreement is None
                or len(self.reference_neighbor_ids) < 3
            ):
                raise EmbedValidationError(
                    "reference match must assign a species candidate"
                )
            if len(set(self.reference_neighbor_ids)) != len(
                self.reference_neighbor_ids
            ) or any(
                not isinstance(value, str) or not value.strip()
                for value in self.reference_neighbor_ids
            ):
                raise EmbedValidationError(
                    "reference neighbor IDs must be unique and nonblank"
                )
            if (
                self.decision_path == "zero_shot_fallback"
                and self.reason == "reference_match"
            ):
                raise EmbedValidationError(
                    "fallback decision cannot use reference-match reason"
                )


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Validated transient search query, selected run, and explicit filters."""

    query: str
    run_id: UUID
    start_date: date | None = None
    end_date: date | None = None
    lighting: Lighting | None = None
    species_id: str | None = None
    limit: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise SearchValidationError("search query must not be blank")
        if not isinstance(self.run_id, UUID):
            raise SearchValidationError("search run ID must be a UUID")
        for name in ("start_date", "end_date"):
            value = getattr(self, name)
            if value is not None and type(value) is not date:
                raise SearchValidationError(f"{name.replace('_', ' ')} must be a date")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise SearchValidationError("start date must not be after end date")
        if self.lighting is not None and (
            not isinstance(self.lighting, Lighting) or self.lighting is Lighting.UNKNOWN
        ):
            raise SearchValidationError("lighting filter must be day or night")
        if self.species_id is not None and (
            not isinstance(self.species_id, str) or not self.species_id.strip()
        ):
            raise SearchValidationError("species ID filter must not be blank")
        if type(self.limit) is not int or self.limit <= 0:
            raise SearchValidationError("search limit must be a positive whole number")


@dataclass(frozen=True, slots=True)
class SearchContext:
    """One selected run's exact model/tagging context and eligible crop identities."""

    run_id: UUID
    model_fingerprint: Sha256
    config_fingerprint: Sha256
    candidate_set_fingerprint: Sha256
    candidate_ids: tuple[str, ...]
    selected_crop_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, UUID):
            raise SearchContextError("search context run ID must be a UUID")
        for name in (
            "model_fingerprint",
            "config_fingerprint",
            "candidate_set_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
                raise SearchContextError(
                    "search context "
                    f"{name.replace('_', ' ')} must be a lowercase SHA-256 digest"
                )
        if any(
            not isinstance(candidate_id, str) or not candidate_id
            for candidate_id in self.candidate_ids
        ):
            raise SearchContextError("search context candidate IDs must not be blank")
        if not self.candidate_ids:
            raise SearchContextError("search context candidate set must not be empty")
        if tuple(sorted(set(self.candidate_ids))) != self.candidate_ids:
            raise SearchContextError(
                "search context candidate IDs must be unique and sorted"
            )
        if any(
            not isinstance(crop_id, str) or not crop_id
            for crop_id in self.selected_crop_ids
        ):
            raise SearchContextError("search context crop IDs must not be blank")
        if len(set(self.selected_crop_ids)) != len(self.selected_crop_ids):
            raise SearchContextError("search context crop IDs must be unique")


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One ranked crop match with its selected decision and source provenance."""

    rank: int
    similarity: float
    crop_id: str
    snapshot_id: Sha256
    representation_id: UUID
    decision_id: UUID
    config_fingerprint: Sha256
    assigned_species_id: str | None
    species_confidence: float
    crop_path: Path
    image_status: Literal["available", "unavailable"]
    source_id: str
    source_video: str
    source_original_path: str
    frame_number: int
    elapsed_seconds: float
    capture_time: str | None
    capture_timezone: str | None
    lighting: Lighting
    detection_id: str
    detection_category: str
    detection_confidence: float
    detection_box_normalized: tuple[float, float, float, float]
    crop_box_pixels: tuple[int, int, int, int]
    frame_width: int
    frame_height: int

    def __post_init__(self) -> None:
        if type(self.rank) is not int or self.rank <= 0:
            raise SearchValidationError("search result rank must be positive")
        if (
            not isinstance(self.similarity, (int, float))
            or isinstance(self.similarity, bool)
            or not math.isfinite(self.similarity)
            or not -1 <= self.similarity <= 1
        ):
            raise SearchValidationError("similarity must be finite and within [-1, 1]")
        if (
            not isinstance(self.species_confidence, (int, float))
            or isinstance(self.species_confidence, bool)
            or not math.isfinite(self.species_confidence)
            or not 0 <= self.species_confidence <= 1
        ):
            raise SearchValidationError(
                "species confidence must be finite and within [0, 1]"
            )
        if (
            not isinstance(self.detection_confidence, (int, float))
            or isinstance(self.detection_confidence, bool)
            or not math.isfinite(self.detection_confidence)
            or not 0 <= self.detection_confidence <= 1
        ):
            raise SearchValidationError(
                "detection confidence must be finite and within [0, 1]"
            )
        for name in ("snapshot_id", "config_fingerprint"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
                raise SearchValidationError(
                    f"{name.replace('_', ' ')} must be a lowercase SHA-256 digest"
                )
        if not all((self.crop_id, self.source_id, self.detection_id)):
            raise SearchValidationError(
                "search result crop, source, and detection IDs are required"
            )
        if self.assigned_species_id is not None and not self.assigned_species_id:
            raise SearchValidationError("assigned species ID must not be blank")
        if not isinstance(self.crop_path, Path):
            raise SearchValidationError("crop path must be a local path")
        if self.image_status not in ("available", "unavailable"):
            raise SearchValidationError("image status must be available or unavailable")
        if not isinstance(self.lighting, Lighting):
            raise SearchValidationError(
                "search result lighting must be a Lighting value"
            )
        if (
            type(self.frame_number) is not int
            or self.frame_number < 0
            or not isinstance(self.elapsed_seconds, (int, float))
            or isinstance(self.elapsed_seconds, bool)
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise SearchValidationError(
                "frame number and elapsed time must be non-negative"
            )
        if self.frame_width <= 0 or self.frame_height <= 0:
            raise SearchValidationError("frame dimensions must be positive")
        if len(self.detection_box_normalized) != 4 or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            for value in self.detection_box_normalized
        ):
            raise SearchValidationError(
                "detection box must contain four finite coordinates"
            )
        if len(self.crop_box_pixels) != 4 or any(
            type(value) is not int for value in self.crop_box_pixels
        ):
            raise SearchValidationError(
                "crop bounds must contain four integer coordinates"
            )


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    """Successful search result, including successful searches with no matches."""

    request: SearchRequest
    context: SearchContext
    results: tuple[SearchResult, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.request.run_id != self.context.run_id:
            raise SearchContextError("search outcome run ID does not match its context")
        if self.request.species_id not in (
            None,
            "unknown",
            *self.context.candidate_ids,
        ):
            raise SearchContextError("species ID is not in the selected candidate set")
        if len(self.results) > self.request.limit:
            raise SearchValidationError("search outcome exceeds the requested limit")
        crop_ids = tuple(result.crop_id for result in self.results)
        if len(set(crop_ids)) != len(crop_ids):
            raise SearchValidationError(
                "search outcome contains duplicate crop identities"
            )
        if any(crop_id not in self.context.selected_crop_ids for crop_id in crop_ids):
            raise SearchContextError("search result is outside the selected run")
        if any(
            result.rank != index for index, result in enumerate(self.results, start=1)
        ):
            raise SearchValidationError(
                "search result ranks must be contiguous and one-based"
            )
        if any(
            result.config_fingerprint != self.context.config_fingerprint
            for result in self.results
        ):
            raise SearchContextError(
                "search result decision does not match the selected context"
            )
        if any(
            left.similarity < right.similarity
            or (left.similarity == right.similarity and left.crop_id > right.crop_id)
            for left, right in zip(self.results, self.results[1:], strict=False)
        ):
            raise SearchValidationError(
                "search results must be sorted by score and crop ID"
            )

    @property
    def returned_count(self) -> int:
        """Return the number of ranked crop matches."""
        return len(self.results)


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
    candidate_schema_version: int = 1
    prompt_template: str = "a photo of {name}."
    prompt_version: str = "species-photo-v1"
    reference_set_fingerprint: Sha256 | None = None
    reference_split_mode: Literal["source_video", "recording_day"] | None = None

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
        if self.candidate_schema_version not in (1, 2):
            raise EmbedValidationError("unsupported candidate schema version")
        if not self.prompt_template or not self.prompt_version:
            raise EmbedValidationError("candidate prompt identity is required")
        if (self.reference_set_fingerprint is None) != (
            self.reference_split_mode is None
        ):
            raise EmbedValidationError("run reference setup identity is incomplete")
        if self.reference_set_fingerprint is not None:
            _validate_sha256(
                "reference_set_fingerprint", self.reference_set_fingerprint
            )
            if self.reference_split_mode not in {"source_video", "recording_day"}:
                raise EmbedValidationError("run reference split mode is invalid")
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
    lighting: Lighting

    def __post_init__(self) -> None:
        _validate_sha256("expected_provenance_sha256", self.expected_provenance_sha256)
        if self.expected_snapshot_id is not None:
            _validate_sha256("expected_snapshot_id", self.expected_snapshot_id)
        if not self.crop_id:
            raise EmbedValidationError("run item crop ID is required")
        if not isinstance(self.lighting, Lighting):
            raise EmbedValidationError(
                "run item lighting must be copied from the snapshot"
            )
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

    def recover_stale_runs(self) -> None:
        """Mark earlier running batches interrupted while holding the writer lock."""

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
