from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from bird_recognition.embed.models import (
    Lighting,
    SearchContext,
    SearchOperationalError,
    SearchRequest,
    SearchResult,
    SearchValidationError,
)
from bird_recognition.embed.search import execute_search


def _context(crop_ids: tuple[str, ...]) -> SearchContext:
    return SearchContext(
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("crow", "owl"),
        selected_crop_ids=tuple(sorted(crop_ids)),
    )


def _result(crop_id: str) -> SearchResult:
    return SearchResult(
        rank=1,
        similarity=0.0,
        crop_id=crop_id,
        snapshot_id="d" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        config_fingerprint="b" * 64,
        assigned_species_id=None,
        species_confidence=0.4,
        crop_path=Path("crops/crop.jpg"),
        image_status="available",
        source_id="source-1",
        source_video="camera.mp4",
        source_original_path="recordings/camera.mp4",
        frame_number=10,
        elapsed_seconds=5.0,
        capture_time=None,
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


def _candidate(crop_id: str, embedding: tuple[float, ...]) -> object:
    return SimpleNamespace(result=_result(crop_id), embedding=embedding)


def _run(
    crop_vectors: tuple[tuple[str, tuple[float, ...]], ...],
    *,
    query_vector: tuple[float, ...] | None = None,
    limit: int = 5,
) -> tuple[object, MagicMock, MagicMock]:
    context = _context(tuple(crop_id for crop_id, _ in crop_vectors))
    request = SearchRequest(query="  owl at dusk  ", run_id=context.run_id, limit=limit)
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(query_vector or (1.0,) + (0.0,) * 511,)),
    )
    store = MagicMock()
    store.get_search_context.return_value = context
    candidates = tuple(_candidate(crop_id, vector) for crop_id, vector in crop_vectors)
    store.load_search_collection.return_value = (context, candidates)
    return execute_search(request, model, store), model, store


def test_execute_search_encodes_query_and_ranks_by_float64_cosine() -> None:
    east = (1.0,) + (0.0,) * 511
    north = (0.0, 1.0) + (0.0,) * 510

    outcome, model, store = _run((("crop-b", north), ("crop-a", east)))

    model.encode_texts.assert_called_once_with(("  owl at dusk  ",))
    store.load_search_collection.assert_called_once()
    assert [
        (result.rank, result.crop_id, result.similarity) for result in outcome.results
    ] == [
        (1, "crop-a", 1.0),
        (2, "crop-b", 0.0),
    ]


def test_execute_search_breaks_equal_score_ties_by_crop_id_before_limit() -> None:
    same = (1.0,) + (0.0,) * 511

    outcome, _, _ = _run((("crop-z", same), ("crop-a", same)), limit=1)

    assert [result.crop_id for result in outcome.results] == ["crop-a"]


def test_execute_search_defaults_to_five_results() -> None:
    same = (1.0,) + (0.0,) * 511

    outcome, _, _ = _run(tuple((f"crop-{index}", same) for index in range(6)))

    assert [result.crop_id for result in outcome.results] == [
        "crop-0",
        "crop-1",
        "crop-2",
        "crop-3",
        "crop-4",
    ]


@pytest.mark.parametrize(
    "invalid_vector",
    [
        (0.0,) * 512,
        (2.0,) + (0.0,) * 511,
        (float("nan"),) + (0.0,) * 511,
        (float("inf"),) + (0.0,) * 511,
        (1.0,) + (0.0,) * 510,
    ],
)
def test_execute_search_rejects_invalid_query_vectors(
    invalid_vector: tuple[float, ...],
) -> None:
    with pytest.raises(SearchOperationalError):
        _run((), query_vector=invalid_vector)


def test_execute_search_rejects_invalid_eligible_crop_scores() -> None:
    valid_crop = (1.0,) + (0.0,) * 511
    invalid_crop = (float("nan"),) + (0.0,) * 511

    with pytest.raises(SearchOperationalError):
        _run((("crop-1", valid_crop), ("crop-2", invalid_crop)), limit=1)


def test_execute_search_rejects_model_fingerprint_mismatch() -> None:
    vector = (1.0,) + (0.0,) * 511
    _, model, store = _run((("crop-1", vector),))
    context = store.load_search_collection.return_value[0]
    model.identity.model_fingerprint = "e" * 64
    store.load_search_collection.return_value = (context, ())

    with pytest.raises(SearchValidationError, match="model fingerprint"):
        execute_search(SearchRequest(query="owl", run_id=context.run_id), model, store)


def test_execute_search_returns_successful_empty_outcome() -> None:
    outcome, _, _ = _run(())

    assert outcome.results == ()
    assert outcome.returned_count == 0


def test_execute_search_rejects_duplicate_crop_identities() -> None:
    vector = (1.0,) + (0.0,) * 511
    context = _context(("crop-1",))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(vector,)),
    )
    store = MagicMock()
    store.load_search_collection.return_value = (
        context,
        (
            _candidate("crop-1", vector),
            _candidate("crop-1", vector),
        ),
    )

    with pytest.raises(SearchValidationError, match="duplicate"):
        execute_search(SearchRequest(query="owl", run_id=context.run_id), model, store)


def test_execute_search_reports_missing_context_as_validation_failure() -> None:
    context = _context(())
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=((1.0,) + (0.0,) * 511,)),
    )
    store = MagicMock()
    store.load_search_collection.side_effect = SearchValidationError("run not found")

    with pytest.raises(SearchValidationError, match="run not found"):
        execute_search(SearchRequest(query="owl", run_id=context.run_id), model, store)
