"""Deterministic local text-to-crop search over stored representations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from bird_recognition.embed.models import (
    EmbeddingModelRecord,
    SearchContext,
    SearchContextError,
    SearchOperationalError,
    SearchOutcome,
    SearchRequest,
    SearchResult,
    SearchValidationError,
    Vector,
)

_VECTOR_DIMENSION = 512
_NORMALIZATION_TOLERANCE = 1e-5
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_SEARCH_WARNINGS = (
    "Species confidence is relative to the selected candidate set, not a calibrated "
    "probability of biological correctness.",
    "Retrieval similarity, species confidence, and detection confidence are distinct "
    "scores; none proves a species or event.",
)


class SearchModel(Protocol):
    """Locally loaded text-embedding model used by the search operation."""

    @property
    def identity(self) -> EmbeddingModelRecord:
        """Return the immutable loaded model identity."""

    def encode_texts(self, prompts: tuple[str, ...]) -> tuple[Vector, ...]:
        """Encode each supplied query into a normalized vector."""


@dataclass(frozen=True, slots=True)
class SearchCandidate:
    """Stored representation and provenance for one selected crop."""

    result: SearchResult
    embedding: Vector


class SearchStore(Protocol):
    """Read-only provider for one selected run's context and crop candidates."""

    def load_search_collection(
        self, request: SearchRequest
    ) -> tuple[SearchContext, tuple[SearchCandidate, ...]]:
        """Load a compatible collection scoped to the supplied run."""


def execute_search(
    request: SearchRequest,
    model: SearchModel,
    store: SearchStore,
    *,
    context: SearchContext | None = None,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> SearchOutcome:
    """Encode one query and return the exact deterministic top-N crop matches."""
    if not isinstance(request, SearchRequest):
        raise SearchValidationError("search request is invalid")
    if context is None or candidates is None:
        loaded_context, loaded_candidates = store.load_search_collection(request)
        context = context or loaded_context
        candidates = candidates if candidates is not None else loaded_candidates
    if context.run_id != request.run_id:
        raise SearchContextError("search context does not match the selected run")
    if model.identity.model_fingerprint != context.model_fingerprint:
        raise SearchContextError(
            "loaded model fingerprint does not match the selected run context"
        )
    if request.species_id is not None and request.species_id not in {
        *context.candidate_ids,
        "unknown",
    }:
        raise SearchValidationError(
            "species ID must be in the selected candidate set or unknown"
        )
    try:
        encoded = model.encode_texts((request.query,))
    except Exception as error:
        raise SearchOperationalError("query embedding failed") from error
    if not isinstance(encoded, (tuple, list)) or len(encoded) != 1:
        raise SearchOperationalError("query encoder returned an invalid vector batch")
    query_vector = _validated_vector(encoded[0], "query")

    filtered_candidates = tuple(
        candidate
        for candidate in candidates
        if _matches_filters(candidate.result, request)
    )
    crop_ids = tuple(candidate.result.crop_id for candidate in filtered_candidates)
    if len(set(crop_ids)) != len(crop_ids):
        raise SearchValidationError(
            "search candidates contain duplicate crop identities"
        )
    if any(crop_id not in context.selected_crop_ids for crop_id in crop_ids):
        raise SearchContextError("search candidate is outside the selected run")

    scored: list[tuple[float, str, SearchResult]] = []
    for candidate in filtered_candidates:
        crop_vector = _validated_vector(candidate.embedding, "crop")
        similarity = _cosine_similarity(query_vector, crop_vector)
        if not math.isfinite(similarity):
            raise SearchOperationalError("similarity score is not finite")
        scored.append((similarity, candidate.result.crop_id, candidate.result))
    scored.sort(key=lambda item: (-item[0], item[1]))
    results = tuple(
        replace(
            result,
            rank=rank,
            similarity=similarity,
            image_status=(
                "available" if _is_readable_file(result.crop_path) else "unavailable"
            ),
        )
        for rank, (similarity, _, result) in enumerate(scored[: request.limit], start=1)
    )
    return SearchOutcome(
        request=request,
        context=context,
        results=results,
        warnings=_SEARCH_WARNINGS,
    )


def parse_search_date(value: str) -> date:
    """Parse one strict YYYY-MM-DD calendar date for search filters."""
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise SearchValidationError("date must use YYYY-MM-DD format")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise SearchValidationError(
            "date must be a valid YYYY-MM-DD calendar date"
        ) from error


def _matches_filters(result: SearchResult, request: SearchRequest) -> bool:
    if request.start_date is not None or request.end_date is not None:
        capture_date = _recorded_capture_date(result.capture_time)
        if capture_date is None:
            return False
        if request.start_date is not None and capture_date < request.start_date:
            return False
        if request.end_date is not None and capture_date > request.end_date:
            return False
    if request.lighting is not None and result.lighting is not request.lighting:
        return False
    if request.species_id is not None:
        assigned_species_id = result.assigned_species_id or "unknown"
        if assigned_species_id != request.species_id:
            return False
    return True


def _recorded_capture_date(value: str | None) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _validated_vector(value: object, label: str) -> Vector:
    if not isinstance(value, (tuple, list)) or len(value) != _VECTOR_DIMENSION:
        raise SearchOperationalError(f"{label} vector must contain 512 values")
    if any(
        isinstance(component, bool)
        or not isinstance(component, (int, float))
        or not math.isfinite(component)
        for component in value
    ):
        raise SearchOperationalError(f"{label} vector must contain finite values")
    vector = tuple(float(component) for component in value)
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise SearchOperationalError(f"{label} vector must be nonzero")
    if abs(norm - 1.0) > _NORMALIZATION_TOLERANCE:
        raise SearchOperationalError(f"{label} vector must be L2-normalized")
    return vector


def _cosine_similarity(first: Vector, second: Vector) -> float:
    dot_product = math.fsum(
        left * right for left, right in zip(first, second, strict=True)
    )
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    value = dot_product / (first_norm * second_norm)
    return max(-1.0, min(1.0, value))


def _is_readable_file(path: Path) -> bool:
    try:
        if not path.is_file():
            return False
        with path.open("rb"):
            return True
    except OSError:
        return False
