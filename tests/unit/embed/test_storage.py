from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from bird_recognition.embed.models import Lighting, SearchContextError, SearchRequest
from bird_recognition.embed.storage import PgVectorStore


def _run_row(status: str = "complete") -> dict[str, object]:
    return {
        "status": status,
        "run_id": UUID("00000000-0000-0000-0000-000000000001"),
        "completed_count": 1,
        "skipped_count": 0,
        "selected_count": 1,
        "model_fingerprint": "a" * 64,
        "config_fingerprint": "b" * 64,
        "candidate_set_fingerprint": "c" * 64,
        "candidates_json": [{"id": "crow"}, {"id": "owl"}],
        "canonical_json": {"preprocessing": {"input_view": {"version": "fit-pad-v1"}}},
    }


def _crop_row(
    crop_id: str = "crop-1",
    *,
    assigned_species_id: str | None = None,
    species_confidence: float | None = 0.4,
    capture_time: str | None = None,
    capture_timezone: str | None = None,
    lighting: str = "unknown",
) -> dict[str, object]:
    return {
        "crop_id": crop_id,
        "snapshot_id": "d" * 64,
        "representation_id": UUID("00000000-0000-0000-0000-000000000002"),
        "decision_id": UUID("00000000-0000-0000-0000-000000000003"),
        "decision_config": "b" * 64,
        "assigned_species_id": assigned_species_id,
        "species_confidence": species_confidence,
        "resolved_input_locator": "C:/private/crop.jpg",
        "source_id": "source-1",
        "source_basename": "camera.mp4",
        "source_original_path": "recordings/camera.mp4",
        "frame_number": 10,
        "elapsed_seconds": 5.0,
        "capture_time": capture_time,
        "capture_timezone": capture_timezone,
        "lighting": lighting,
        "detection_id": "detection-1",
        "detection_category": "animal",
        "detection_confidence": 0.9,
        "detection_box_normalized": [0.1, 0.2, 0.5, 0.6],
        "crop_box_pixels": [10, 20, 50, 60],
        "frame_width": 100,
        "frame_height": 100,
        "embedding": SimpleNamespace(to_list=lambda: [1.0] + [0.0] * 511),
    }


def _mock_store_connection(
    monkeypatch: pytest.MonkeyPatch,
    run: dict[str, object] | None,
    rows: list[dict[str, object]],
) -> list[str]:
    statements: list[str] = []

    def execute(query: str, params: object = None) -> object:
        statements.append(query)
        if query.startswith("SET TRANSACTION"):
            return None
        if "FROM bird_embed.processing_run AS r" in query:
            return SimpleNamespace(fetchone=lambda: run)
        return SimpleNamespace(fetchall=lambda: rows)

    connection = SimpleNamespace(execute=execute)
    monkeypatch.setattr(
        "bird_recognition.embed.storage.psycopg.connect",
        lambda *args, **kwargs: nullcontext(connection),
    )
    monkeypatch.setattr(
        "bird_recognition.embed.storage.register_vector", lambda connection: None
    )
    return statements


def test_load_search_collection_uses_one_read_only_run_and_model_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    statements = _mock_store_connection(monkeypatch, run, [_crop_row()])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    request = SearchRequest(query="owl", run_id=run["run_id"])
    context, candidates = store.load_search_collection(request)

    assert context.run_id == run["run_id"]
    assert context.model_fingerprint == "a" * 64
    assert context.config_fingerprint == "b" * 64
    assert context.selected_crop_ids == ("crop-1",)
    assert len(candidates) == 1
    assert candidates[0].result.crop_path == Path("C:/private/crop.jpg")
    assert statements[0] == "SET TRANSACTION READ ONLY"
    assert all(
        statement.startswith(("SET TRANSACTION", "SELECT")) for statement in statements
    )
    assert "i.status IN ('completed','skipped')" in statements[2]


def test_load_search_collection_rejects_non_searchable_run_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row("running")
    _mock_store_connection(monkeypatch, run, [_crop_row()])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    with pytest.raises(SearchContextError):
        store.load_search_collection(SearchRequest(query="owl", run_id=run["run_id"]))


def test_load_search_collection_accepts_valid_no_input_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row("no_input")
    run["completed_count"] = 0
    run["skipped_count"] = 0
    run["selected_count"] = 0
    _mock_store_connection(monkeypatch, run, [])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    request = SearchRequest(query="owl", run_id=run["run_id"])
    context, candidates = store.load_search_collection(request)

    assert context.selected_crop_ids == ()
    assert candidates == ()


def test_load_search_collection_rejects_missing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PgVectorStore("postgresql://bird@localhost/bird_db")
    _mock_store_connection(monkeypatch, None, [])

    with pytest.raises(SearchContextError):
        store.load_search_collection(
            SearchRequest(
                query="owl",
                run_id=UUID("00000000-0000-0000-0000-000000000001"),
            )
        )


def test_load_search_collection_filters_complete_candidate_set_before_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    run["completed_count"] = 4
    run["selected_count"] = 4
    rows = [
        _crop_row(
            "top-unassigned",
            capture_time="2026-01-02T00:30:00+14:00",
            lighting="day",
        ),
        _crop_row(
            "eligible-a",
            assigned_species_id="owl",
            capture_time="2026-01-02T23:30:00-10:00",
            lighting="day",
        ),
        _crop_row(
            "eligible-b",
            assigned_species_id="owl",
            capture_time="2026-01-02T12:00:00Z",
            lighting="day",
        ),
        _crop_row(
            "wrong-lighting",
            assigned_species_id="owl",
            capture_time="2026-01-02T12:00:00Z",
            lighting="night",
        ),
    ]
    statements = _mock_store_connection(monkeypatch, run, rows)
    store = PgVectorStore("postgresql://bird@localhost/bird_db")
    request = SearchRequest(
        query="owl at night",
        run_id=run["run_id"],
        start_date=date(2026, 1, 2),
        end_date=date(2026, 1, 2),
        lighting=Lighting.DAY,
        species_id="owl",
        limit=1,
    )

    context, candidates = store.load_search_collection(request)

    assert set(context.selected_crop_ids) == {row["crop_id"] for row in rows}
    assert [candidate.result.crop_id for candidate in candidates] == [
        "eligible-a",
        "eligible-b",
    ]
    assert "LIMIT" not in statements[2].upper()
    assert all(
        statement.startswith(("SET TRANSACTION", "SELECT")) for statement in statements
    )


def test_load_search_collection_matches_unknown_only_for_unassigned_decisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    run["completed_count"] = 2
    run["selected_count"] = 2
    rows = [
        _crop_row("assigned", assigned_species_id="crow"),
        _crop_row("unassigned", assigned_species_id=None),
    ]
    _mock_store_connection(monkeypatch, run, rows)
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    _, candidates = store.load_search_collection(
        SearchRequest(query="crow", run_id=run["run_id"], species_id="unknown")
    )

    assert [candidate.result.crop_id for candidate in candidates] == ["unassigned"]


def test_load_search_collection_rejects_unknown_species_before_candidate_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    statements = _mock_store_connection(monkeypatch, run, [_crop_row()])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    with pytest.raises(SearchContextError, match="candidate set"):
        store.load_search_collection(
            SearchRequest(query="owl", run_id=run["run_id"], species_id="eagle")
        )

    assert len(statements) == 2


def test_load_search_collection_preserves_full_source_and_detection_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    run["completed_count"] = 1
    run["selected_count"] = 1
    row = _crop_row(
        assigned_species_id="owl",
        capture_time="2026-01-02T03:04:05-08:00",
        capture_timezone="America/Los_Angeles",
        lighting="night",
    )
    _mock_store_connection(monkeypatch, run, [row])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    context, candidates = store.load_search_collection(
        SearchRequest(query="owl", run_id=run["run_id"])
    )

    result = candidates[0].result
    assert result.crop_id == "crop-1"
    assert result.snapshot_id == "d" * 64
    assert result.representation_id == row["representation_id"]
    assert result.decision_id == row["decision_id"]
    assert result.config_fingerprint == context.config_fingerprint
    assert result.source_id == "source-1"
    assert result.source_video == "camera.mp4"
    assert result.source_original_path == "recordings/camera.mp4"
    assert (result.frame_number, result.elapsed_seconds) == (10, 5.0)
    assert (result.capture_time, result.capture_timezone) == (
        "2026-01-02T03:04:05-08:00",
        "America/Los_Angeles",
    )
    assert result.lighting is Lighting.NIGHT
    assert result.detection_id == "detection-1"
    assert result.detection_category == "animal"
    assert result.detection_confidence == 0.9
    assert result.detection_box_normalized == (0.1, 0.2, 0.5, 0.6)
    assert result.crop_box_pixels == (10, 20, 50, 60)
    assert (result.frame_width, result.frame_height) == (100, 100)


def test_load_search_collection_preserves_unknown_assignment_and_null_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row()
    run["completed_count"] = 1
    run["selected_count"] = 1
    row = _crop_row(species_confidence=None)
    _mock_store_connection(monkeypatch, run, [row])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    _, candidates = store.load_search_collection(
        SearchRequest(query="owl", run_id=run["run_id"])
    )

    assert candidates[0].result.assigned_species_id is None
    assert candidates[0].result.species_confidence is None
