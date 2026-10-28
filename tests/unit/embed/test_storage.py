from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from bird_recognition.embed.models import SearchContextError
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


def _crop_row() -> dict[str, object]:
    return {
        "crop_id": "crop-1",
        "snapshot_id": "d" * 64,
        "representation_id": UUID("00000000-0000-0000-0000-000000000002"),
        "decision_id": UUID("00000000-0000-0000-0000-000000000003"),
        "decision_config": "b" * 64,
        "assigned_species_id": None,
        "species_confidence": 0.4,
        "resolved_input_locator": "C:/private/crop.jpg",
        "source_id": "source-1",
        "source_basename": "camera.mp4",
        "source_original_path": "recordings/camera.mp4",
        "frame_number": 10,
        "elapsed_seconds": 5.0,
        "capture_time": None,
        "capture_timezone": None,
        "lighting": "unknown",
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

    context, candidates = store.load_search_collection(run["run_id"])

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
        store.load_search_collection(run["run_id"])


def test_load_search_collection_accepts_valid_no_input_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run_row("no_input")
    run["completed_count"] = 0
    run["skipped_count"] = 0
    run["selected_count"] = 0
    _mock_store_connection(monkeypatch, run, [])
    store = PgVectorStore("postgresql://bird@localhost/bird_db")

    context, candidates = store.load_search_collection(run["run_id"])

    assert context.selected_crop_ids == ()
    assert candidates == ()


def test_load_search_collection_rejects_missing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = PgVectorStore("postgresql://bird@localhost/bird_db")
    _mock_store_connection(monkeypatch, None, [])

    with pytest.raises(SearchContextError):
        store.load_search_collection(UUID("00000000-0000-0000-0000-000000000001"))
