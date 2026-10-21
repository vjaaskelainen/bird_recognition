from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.embed.config import load_species_candidates
from bird_recognition.embed.models import (
    EmbeddingModelRecord,
    EmbedValidationError,
    IngestedCropSnapshot,
    Lighting,
    RunStatus,
    SharedModelError,
    StorageError,
    UnconfirmedCommitError,
)
from bird_recognition.embed.pipeline import index_crops
from tests.unit.embed.fakes import FakeModel, FakeStore, FakeStoreState


def _snapshot(crop_id: str, path: Path, image_bytes: bytes) -> IngestedCropSnapshot:
    digest = hashlib.sha256(image_bytes).hexdigest()
    values = {
        "crop_id": crop_id,
        "crop_sha256": digest,
        "source_id": f"source-{crop_id}",
        "source_content_sha256": "1" * 64,
        "source_original_path": "private-source.mp4",
        "source_basename": "private-source.mp4",
        "ingest_settings_fingerprint": "2" * 64,
        "ingestion_run_id": "ingestion-run",
        "frame_number": 0,
        "elapsed_seconds": 0.0,
        "detection_id": f"detection-{crop_id}",
        "detection_category": "animal",
        "detection_confidence": 0.9,
        "detection_box_normalized": (0.1, 0.1, 0.9, 0.9),
        "crop_box_pixels": (0, 0, 32, 24),
        "frame_width": 32,
        "frame_height": 24,
        "crop_original_image_path": path.name,
        "capture_time": None,
        "capture_timezone": None,
        "source_capture_start": None,
        "source_capture_timezone": None,
        "lighting": Lighting.DAY,
    }
    provenance = hashlib.sha256(repr(sorted(values.items())).encode()).hexdigest()
    return IngestedCropSnapshot(
        snapshot_id=hashlib.sha256(f"{crop_id}\0{provenance}".encode()).hexdigest(),
        provenance_sha256=provenance,
        imported_at=datetime.now(UTC),
        **values,
    )


def _candidate_file(tmp_path: Path, species: list[dict[str, str]]) -> Path:
    import json

    path = tmp_path / "species.json"
    path.write_text(
        json.dumps({"schema_version": 1, "species": species}), encoding="utf-8"
    )
    return path


def _new_crops(tmp_path: Path, count: int) -> tuple[list[IngestedCropSnapshot], Path]:
    root = tmp_path / "crops"
    root.mkdir()
    snapshots = []
    for index in range(count):
        crop_id = f"crop-{index:03}"
        path = root / f"{crop_id}.png"
        Image.new("RGB", (32, 24), (20 + index % 200, 80, 130)).save(path)
        image_bytes = path.read_bytes()
        snapshots.append(_snapshot(crop_id, path, image_bytes))
    return snapshots, root


def test_index_crops_persists_100_results_and_restart_inspects_provenance(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 100)
    candidates = load_species_candidates(
        _candidate_file(
            tmp_path,
            [{"id": "bird-a", "name": "Bird A"}, {"id": "bird-b", "name": "Bird B"}],
        )
    )
    state = FakeStoreState()
    model = FakeModel(model_record)
    store = FakeStore(state)

    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=model,
        store=store,
    )
    restarted_store = FakeStore(state)

    assert run.status is RunStatus.COMPLETE
    assert (run.selected_count, run.completed_count, run.assigned_count) == (
        100,
        100,
        100,
    )
    assert run.unknown_count == run.skipped_count == run.failed_count == 0
    assert (
        len(state.snapshots)
        == len(state.representations)
        == len(state.decisions)
        == 100
    )
    assert len(state.items) == 100
    assert next(iter(state.snapshots.values())).source_content_sha256 == "1" * 64
    assert restarted_store.state.runs[run.run_id].completed_count == 100


def test_index_crops_skips_exact_completed_decision_without_inference(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    state = FakeStoreState()
    first_model = FakeModel(model_record)
    first_run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=first_model,
        store=FakeStore(state),
    )
    second_model = FakeModel(model_record)
    second_run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=second_model,
        store=FakeStore(state),
    )

    assert first_run.completed_count == 1
    assert second_run.status is RunStatus.COMPLETE
    assert second_run.completed_count == 0
    assert second_run.skipped_count == 1
    assert second_model.inference_count == 0


def test_index_crops_zero_input_still_runs_full_preflight(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    store = FakeStore()
    run = index_crops(
        [],
        crop_root=tmp_path,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=FakeModel(model_record),
        store=store,
    )

    assert run.status is RunStatus.NO_INPUT
    assert run.selected_count == 0
    assert store.state.snapshots == {}
    assert store.state.decisions == {}


def test_index_crops_isolates_one_corrupt_image_and_completes_others(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 100)
    (crop_root / "crop-050.png").write_bytes(b"corrupt crop")
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    store = FakeStore()

    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=FakeModel(model_record),
        store=store,
    )

    assert run.status is RunStatus.PARTIAL_FAILURE
    assert (run.completed_count, run.failed_count, run.unknown_count) == (99, 1, 0)
    assert run.failures[0].code == "crop_hash_mismatch"


@pytest.mark.parametrize("failure_stage", ["preflight", "acquire_writer_lock"])
def test_index_crops_preflight_failure_writes_no_crop_results(
    tmp_path: Path, model_record: EmbeddingModelRecord, failure_stage: str
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )

    def fail(stage: str) -> None:
        if stage == failure_stage:
            raise StorageError("preflight failure")

    store = FakeStore(failure_hook=fail)
    with pytest.raises(StorageError):
        index_crops(
            snapshots,
            crop_root=crop_root,
            manifest_locator=tmp_path / "manifest.sqlite3",
            candidates=candidates,
            model=FakeModel(model_record),
            store=store,
        )

    assert store.state.snapshots == {}
    assert store.state.decisions == {}
    assert store.state.runs == {}


@pytest.mark.parametrize("threshold", [float("nan"), -0.1, 1.1])
def test_index_crops_invalid_threshold_fails_before_any_store_writes(
    tmp_path: Path, model_record: EmbeddingModelRecord, threshold: float
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    store = FakeStore()

    with pytest.raises(EmbedValidationError):
        index_crops(
            snapshots,
            crop_root=crop_root,
            manifest_locator=tmp_path / "manifest.sqlite3",
            candidates=candidates,
            model=FakeModel(model_record),
            store=store,
            threshold=threshold,
        )

    assert store.state.runs == {}
    assert store.state.snapshots == {}
    assert store.state.decisions == {}


def test_index_crops_stops_after_fatal_shared_model_error(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 3)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    model = FakeModel(model_record, text_results=(SharedModelError("broken model"),))
    store = FakeStore()

    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=model,
        store=store,
    )

    assert run.status is RunStatus.FAILED
    assert run.pending_count == 3
    assert model.image_calls == 0
    assert model.text_calls == 1


def test_index_crops_isolates_invalid_image_vector_and_continues(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 2)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    model = FakeModel(model_record, image_results=((0.0, 0.0, 0.0),))
    store = FakeStore()

    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=model,
        store=store,
    )

    assert run.status is RunStatus.PARTIAL_FAILURE
    assert (run.completed_count, run.failed_count) == (1, 1)
    assert run.failures[0].code == "invalid_vector"


def test_index_crops_reports_lost_commit_acknowledgement_as_unconfirmed(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )

    def lose_acknowledgement(stage: str) -> None:
        if stage == "after_crop_commit":
            raise UnconfirmedCommitError("acknowledgement lost")

    state = FakeStoreState()
    store = FakeStore(state, lose_acknowledgement)
    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=FakeModel(model_record),
        store=store,
    )

    assert run.status is RunStatus.FAILED
    assert not run.durable_status_confirmed
    assert run.unconfirmed_crop_ids == (snapshots[0].crop_id,)
    assert run.completed_count == 0
    assert len(state.decisions) == 1
