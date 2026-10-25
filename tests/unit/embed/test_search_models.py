from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from bird_recognition.embed.models import (
    Lighting,
    SearchContext,
    SearchContextError,
    SearchError,
    SearchOperationalError,
    SearchOutcome,
    SearchRequest,
    SearchResult,
    SearchValidationError,
)


def _context() -> SearchContext:
    return SearchContext(
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("crow", "owl"),
        selected_crop_ids=("crop-1",),
    )


def _result(*, rank: int = 1, similarity: float = 0.75) -> SearchResult:
    return SearchResult(
        rank=rank,
        similarity=similarity,
        crop_id="crop-1",
        snapshot_id="d" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        config_fingerprint="b" * 64,
        assigned_species_id=None,
        species_confidence=0.4,
        crop_path=Path("crops/crop-1.jpg"),
        image_status="available",
        source_id="source-1",
        source_video="camera.mp4",
        source_original_path="recordings/camera.mp4",
        frame_number=10,
        elapsed_seconds=5.0,
        capture_time="2026-10-25T12:00:00",
        capture_timezone=None,
        lighting=Lighting.UNKNOWN,
        detection_id="detection-1",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.1, 0.2, 0.5, 0.6),
        crop_box_pixels=(10, 20, 50, 60),
        frame_width=100,
        frame_height=100,
    )


def test_search_request_preserves_query_and_default_limit() -> None:
    request = SearchRequest(
        query="  owl at dusk  ",
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert request.query == "  owl at dusk  "
    assert request.limit == 5


@pytest.mark.parametrize("query", ["", "   ", "\t\n"])
def test_search_request_blank_query_raises_validation_error(query: str) -> None:
    with pytest.raises(SearchValidationError):
        SearchRequest(
            query=query,
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
        )


def test_search_request_rejects_invalid_dates_lighting_and_limit() -> None:
    run_id = UUID("00000000-0000-0000-0000-000000000001")

    with pytest.raises(SearchValidationError):
        SearchRequest(
            query="owl",
            run_id=run_id,
            start_date=date(2026, 10, 26),
            end_date=date(2026, 10, 25),
        )

    with pytest.raises(SearchValidationError):
        SearchRequest(query="owl", run_id=run_id, lighting=Lighting.UNKNOWN)

    with pytest.raises(SearchValidationError):
        SearchRequest(query="owl", run_id=run_id, limit=True)


def test_search_context_validates_fingerprints_and_canonical_candidate_ids() -> None:
    with pytest.raises(SearchValidationError):
        SearchContext(
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            model_fingerprint="invalid",
            config_fingerprint="b" * 64,
            candidate_set_fingerprint="c" * 64,
            candidate_ids=("owl",),
            selected_crop_ids=(),
        )

    with pytest.raises(SearchValidationError):
        SearchContext(
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            model_fingerprint="a" * 64,
            config_fingerprint="b" * 64,
            candidate_set_fingerprint="c" * 64,
            candidate_ids=("owl", "crow"),
            selected_crop_ids=(),
        )


def test_search_result_validates_score_confidences_and_provenance() -> None:
    assert _result().similarity == 0.75

    with pytest.raises(SearchValidationError):
        _result(similarity=float("nan"))


def test_search_outcome_validates_request_context_and_ordered_result_count() -> None:
    request = SearchRequest(
        query="owl",
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
    )
    result = _result()

    outcome = SearchOutcome(
        request=request,
        context=_context(),
        results=(result,),
        warnings=("Similarity is relative relevance, not a probability.",),
    )

    assert outcome.returned_count == 1
    assert issubclass(SearchValidationError, ValueError)


def test_search_failures_distinguish_context_from_operational_errors() -> None:
    assert issubclass(SearchContextError, SearchValidationError)
    assert issubclass(SearchOperationalError, SearchError)
