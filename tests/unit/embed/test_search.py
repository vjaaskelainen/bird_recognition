from __future__ import annotations

from dataclasses import replace
from datetime import date
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
from bird_recognition.embed.search import execute_search, parse_search_date


def _context(crop_ids: tuple[str, ...]) -> SearchContext:
    return SearchContext(
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("crow", "owl"),
        selected_crop_ids=tuple(sorted(crop_ids)),
    )


def _result(
    crop_id: str,
    *,
    assigned_species_id: str | None = None,
    capture_time: str | None = None,
    lighting: Lighting = Lighting.UNKNOWN,
) -> SearchResult:
    return SearchResult(
        rank=1,
        similarity=0.0,
        crop_id=crop_id,
        snapshot_id="d" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        config_fingerprint="b" * 64,
        assigned_species_id=assigned_species_id,
        species_confidence=0.4,
        crop_path=Path("crops/crop.jpg"),
        image_status="available",
        source_id="source-1",
        source_video="camera.mp4",
        source_original_path="recordings/camera.mp4",
        frame_number=10,
        elapsed_seconds=5.0,
        capture_time=capture_time,
        capture_timezone=None,
        lighting=lighting,
        detection_id="detection-1",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.1, 0.2, 0.5, 0.6),
        crop_box_pixels=(10, 20, 50, 60),
        frame_width=100,
        frame_height=100,
    )


def _candidate(
    crop_id: str,
    embedding: tuple[float, ...],
    *,
    assigned_species_id: str | None = None,
    capture_time: str | None = None,
    lighting: Lighting = Lighting.UNKNOWN,
) -> object:
    return SimpleNamespace(
        result=_result(
            crop_id,
            assigned_species_id=assigned_species_id,
            capture_time=capture_time,
            lighting=lighting,
        ),
        embedding=embedding,
    )


def _run(
    crop_vectors: tuple[tuple[str, tuple[float, ...]], ...],
    *,
    query_vector: tuple[float, ...] | None = None,
    limit: int = 5,
    start_date: date | None = None,
    end_date: date | None = None,
    lighting: Lighting | None = None,
    species_id: str | None = None,
) -> tuple[object, MagicMock, MagicMock]:
    context = _context(tuple(crop_id for crop_id, _ in crop_vectors))
    request = SearchRequest(
        query="  owl at dusk  ",
        run_id=context.run_id,
        start_date=start_date,
        end_date=end_date,
        lighting=lighting,
        species_id=species_id,
        limit=limit,
    )
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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-02", date(2026, 1, 2)),
        ("2024-02-29", date(2024, 2, 29)),
    ],
)
def test_parse_search_date_accepts_strict_calendar_dates(
    value: str, expected: date
) -> None:
    assert parse_search_date(value) == expected


@pytest.mark.parametrize(
    "value",
    ["2026-1-02", "2026-01-2", "2026/01/02", "2026-02-29", "tomorrow", ""],
)
def test_parse_search_date_rejects_malformed_or_impossible_dates(value: str) -> None:
    with pytest.raises(SearchValidationError, match="YYYY-MM-DD"):
        parse_search_date(value)


@pytest.mark.parametrize(
    ("start_date", "end_date", "lighting", "limit"),
    [
        (date(2026, 2, 2), date(2026, 2, 1), None, 5),
        (None, None, Lighting.UNKNOWN, 5),
        (None, None, None, 0),
        (None, None, None, 1.5),
    ],
)
def test_search_request_rejects_invalid_filter_ranges_values_and_limits(
    start_date: date | None,
    end_date: date | None,
    lighting: Lighting | None,
    limit: int,
) -> None:
    with pytest.raises(SearchValidationError):
        SearchRequest(
            query="owl",
            run_id=UUID("00000000-0000-0000-0000-000000000001"),
            start_date=start_date,
            end_date=end_date,
            lighting=lighting,
            limit=limit,
        )


def test_search_filters_before_limit_and_preserves_recorded_date() -> None:
    east = (1.0,) + (0.0,) * 511
    weaker = (0.0, 1.0) + (0.0,) * 510
    vectors = (
        _candidate(
            "unfiltered-best",
            east,
            assigned_species_id="crow",
            capture_time="2026-01-02T00:30:00+14:00",
            lighting=Lighting.NIGHT,
        ),
        _candidate(
            "eligible-a",
            weaker,
            assigned_species_id="owl",
            capture_time="2026-01-02T23:30:00-10:00",
            lighting=Lighting.DAY,
        ),
        _candidate(
            "eligible-b",
            weaker,
            assigned_species_id="owl",
            capture_time="2026-01-03T00:00:00Z",
            lighting=Lighting.DAY,
        ),
        _candidate(
            "unknown-date",
            east,
            assigned_species_id="owl",
            lighting=Lighting.DAY,
        ),
    )
    context = _context(tuple(candidate.result.crop_id for candidate in vectors))
    context = SearchContext(
        run_id=context.run_id,
        model_fingerprint=context.model_fingerprint,
        config_fingerprint=context.config_fingerprint,
        candidate_set_fingerprint=context.candidate_set_fingerprint,
        candidate_ids=("crow", "owl"),
        selected_crop_ids=context.selected_crop_ids,
    )
    request = SearchRequest(
        query="owl at night on January 2",
        run_id=context.run_id,
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        lighting=Lighting.DAY,
        species_id="owl",
        limit=1,
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(east,)),
    )

    outcome = execute_search(
        request, model, MagicMock(), context=context, candidates=vectors
    )

    assert [result.crop_id for result in outcome.results] == ["eligible-a"]


def test_unknown_filter_uses_final_assignment_not_best_candidate() -> None:
    east = (1.0,) + (0.0,) * 511
    candidates = (
        _candidate("assigned", east, assigned_species_id="crow"),
        _candidate("unassigned", east),
    )
    context = _context(("assigned", "unassigned"))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(east,)),
    )

    outcome = execute_search(
        SearchRequest(query="crow", run_id=context.run_id, species_id="unknown"),
        model,
        MagicMock(),
        context=context,
        candidates=candidates,
    )

    assert [result.crop_id for result in outcome.results] == ["unassigned"]


def test_execute_search_rejects_species_outside_selected_candidate_set() -> None:
    east = (1.0,) + (0.0,) * 511
    context = _context(("crop-1",))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(east,)),
    )
    request = SearchRequest(query="owl", run_id=context.run_id, species_id="eagle")

    with pytest.raises(SearchValidationError, match="candidate set"):
        execute_search(
            request,
            model,
            MagicMock(),
            context=context,
            candidates=(_candidate("crop-1", east),),
        )


def test_execute_search_returns_successful_zero_results_for_valid_filter() -> None:
    east = (1.0,) + (0.0,) * 511

    outcome, _, _ = _run(
        (("crop-1", east),),
        lighting=Lighting.NIGHT,
    )

    assert outcome.results == ()
    assert outcome.returned_count == 0


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_crop_ids"),
    [
        (date(2026, 1, 2), None, ["after-boundary", "on-boundary"]),
        (None, date(2026, 1, 2), ["before-boundary", "on-boundary"]),
        (date(2026, 1, 2), date(2026, 1, 2), ["on-boundary"]),
    ],
)
def test_execute_search_applies_inclusive_recorded_date_bounds(
    start_date: date | None,
    end_date: date | None,
    expected_crop_ids: list[str],
) -> None:
    east = (1.0,) + (0.0,) * 511
    candidates = (
        _candidate("before-boundary", east, capture_time="2026-01-01T23:59:59-10:00"),
        _candidate("on-boundary", east, capture_time="2026-01-02T00:00:00+14:00"),
        _candidate("after-boundary", east, capture_time="2026-01-03T00:00:00Z"),
        _candidate("missing-date", east),
    )
    context = _context(tuple(candidate.result.crop_id for candidate in candidates))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(east,)),
    )
    request = SearchRequest(
        query="owl",
        run_id=context.run_id,
        start_date=start_date,
        end_date=end_date,
    )

    outcome = execute_search(
        request, model, MagicMock(), context=context, candidates=candidates
    )

    assert [result.crop_id for result in outcome.results] == expected_crop_ids


@pytest.mark.parametrize(
    ("lighting", "expected_crop_ids"),
    [
        (None, ["day", "night", "unknown"]),
        (Lighting.DAY, ["day"]),
        (Lighting.NIGHT, ["night"]),
    ],
)
def test_execute_search_matches_exact_lighting_filter(
    lighting: Lighting | None, expected_crop_ids: list[str]
) -> None:
    east = (1.0,) + (0.0,) * 511
    candidates = tuple(
        _candidate(crop_id, east, lighting=crop_lighting)
        for crop_id, crop_lighting in (
            ("day", Lighting.DAY),
            ("night", Lighting.NIGHT),
            ("unknown", Lighting.UNKNOWN),
        )
    )
    context = _context(tuple(candidate.result.crop_id for candidate in candidates))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(east,)),
    )
    request = SearchRequest(query="owl", run_id=context.run_id, lighting=lighting)

    outcome = execute_search(
        request, model, MagicMock(), context=context, candidates=candidates
    )

    assert [result.crop_id for result in outcome.results] == expected_crop_ids


def test_execute_search_filters_only_final_assigned_species() -> None:
    east = (1.0,) + (0.0,) * 511
    candidates = (
        _candidate("assigned-crow", east, assigned_species_id="crow"),
        _candidate("unassigned-best-crow", east),
    )
    context = _context(tuple(candidate.result.crop_id for candidate in candidates))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(east,)),
    )
    request = SearchRequest(query="owl", run_id=context.run_id, species_id="crow")

    outcome = execute_search(
        request, model, MagicMock(), context=context, candidates=candidates
    )

    assert [result.crop_id for result in outcome.results] == ["assigned-crow"]


def test_execute_search_retains_result_when_crop_locator_is_unavailable(
    tmp_path: Path,
) -> None:
    vector = (1.0,) + (0.0,) * 511
    candidate = _candidate("crop-1", vector)
    missing_path = tmp_path / "moved-crop.jpg"
    candidate = SimpleNamespace(
        result=replace(candidate.result, crop_path=missing_path),
        embedding=candidate.embedding,
    )
    context = _context(("crop-1",))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(vector,)),
    )

    outcome = execute_search(
        SearchRequest(query="owl", run_id=context.run_id),
        model,
        MagicMock(),
        context=context,
        candidates=(candidate,),
    )

    result = outcome.results[0]
    assert result.image_status == "unavailable"
    assert result.crop_path == missing_path
    assert (result.rank, result.similarity, result.crop_id) == (1, 1.0, "crop-1")
    assert result.snapshot_id == "d" * 64
    assert result.representation_id == UUID("00000000-0000-0000-0000-000000000002")
    assert result.decision_id == UUID("00000000-0000-0000-0000-000000000003")
    assert result.source_id == "source-1"
    assert result.source_video == "camera.mp4"
    assert result.frame_number == 10
    assert result.capture_time is None
    assert result.capture_timezone is None
    assert result.lighting is Lighting.UNKNOWN
    assert result.detection_id == "detection-1"


def test_execute_search_checks_existing_crop_with_read_only_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector = (1.0,) + (0.0,) * 511
    candidate = _candidate("crop-1", vector)
    crop_path = tmp_path / "crop.jpg"
    crop_path.write_bytes(b"crop-bytes")
    candidate = SimpleNamespace(
        result=replace(candidate.result, crop_path=crop_path),
        embedding=candidate.embedding,
    )
    modes: list[str] = []
    original_open = Path.open

    def record_open(
        path: Path, mode: str = "r", *args: object, **kwargs: object
    ) -> object:
        modes.append(mode)
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", record_open)
    context = _context(("crop-1",))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(vector,)),
    )

    outcome = execute_search(
        SearchRequest(query="owl", run_id=context.run_id),
        model,
        MagicMock(),
        context=context,
        candidates=(candidate,),
    )

    assert outcome.results[0].image_status == "available"
    assert modes == ["rb"]
    assert crop_path.read_bytes() == b"crop-bytes"


def test_execute_search_retains_result_when_crop_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vector = (1.0,) + (0.0,) * 511
    candidate = _candidate("crop-1", vector)
    crop_path = tmp_path / "unreadable-crop.jpg"
    crop_path.write_bytes(b"crop-bytes")
    candidate = SimpleNamespace(
        result=replace(candidate.result, crop_path=crop_path),
        embedding=candidate.embedding,
    )
    original_open = Path.open

    def reject_crop_read(
        path: Path, mode: str = "r", *args: object, **kwargs: object
    ) -> object:
        if path == crop_path:
            raise PermissionError("crop access denied")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_crop_read)
    context = _context(("crop-1",))
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=MagicMock(return_value=(vector,)),
    )

    outcome = execute_search(
        SearchRequest(query="owl", run_id=context.run_id),
        model,
        MagicMock(),
        context=context,
        candidates=(candidate,),
    )

    assert len(outcome.results) == 1
    assert outcome.results[0].image_status == "unavailable"
    assert outcome.results[0].rank == 1
    assert outcome.results[0].similarity == 1.0
