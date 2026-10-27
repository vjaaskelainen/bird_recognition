from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.embed.config import load_species_candidates
from bird_recognition.embed.models import (
    EmbeddingModelRecord,
    IngestedCropSnapshot,
    Lighting,
    RunItemStatus,
    RunStatus,
    SharedModelError,
    StorageError,
    UnconfirmedCommitError,
)
from bird_recognition.embed.pipeline import index_crops
from tests.unit.embed.fakes import FakeModel, FakeStore, FakeStoreState


def _snapshot(crop_id: str, path: Path) -> IngestedCropSnapshot:
    crop_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    provenance_sha256 = hashlib.sha256(f"provenance:{crop_id}".encode()).hexdigest()
    return IngestedCropSnapshot(
        snapshot_id=hashlib.sha256(
            f"{crop_id}\0{provenance_sha256}".encode()
        ).hexdigest(),
        crop_id=crop_id,
        provenance_sha256=provenance_sha256,
        crop_sha256=crop_sha256,
        source_id=f"source-{crop_id}",
        source_content_sha256="1" * 64,
        source_original_path="private-source.mp4",
        source_basename="private-source.mp4",
        ingest_settings_fingerprint="2" * 64,
        ingestion_run_id="ingestion-run",
        frame_number=0,
        elapsed_seconds=0.0,
        detection_id=f"detection-{crop_id}",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.1, 0.1, 0.9, 0.9),
        crop_box_pixels=(0, 0, 32, 32),
        frame_width=32,
        frame_height=32,
        crop_original_image_path=path.name,
        capture_time=None,
        capture_timezone=None,
        source_capture_start=None,
        source_capture_timezone=None,
        lighting=Lighting.DAY,
        imported_at=datetime.now(UTC),
    )


def _candidate_file(path: Path, candidates: list[dict[str, str]]) -> Path:
    path.write_text(
        json.dumps({"schema_version": 1, "species": candidates}), encoding="utf-8"
    )
    return path


def _index(
    snapshot: IngestedCropSnapshot,
    root: Path,
    candidates: list[dict[str, str]],
    model: FakeModel,
    store: FakeStore,
    *,
    threshold: float = 0.5,
) -> object:
    candidate_set = load_species_candidates(
        _candidate_file(
            root.parent / f"species-{len(store.state.runs)}.json", candidates
        )
    )
    return index_crops(
        (snapshot,),
        crop_root=root,
        manifest_locator=root.parent / "manifest.sqlite3",
        candidates=candidate_set,
        model=model,
        store=store,
        threshold=threshold,
    )


def test_threshold_only_retag_reuses_persisted_score_map_without_inference(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    candidates = [
        {"id": "bird-a", "name": "Bird A"},
        {"id": "bird-b", "name": "Bird B"},
    ]
    state = FakeStoreState()
    first = _index(
        snapshot, root, candidates, FakeModel(model_record), FakeStore(state)
    )
    retag_model = FakeModel(model_record)
    second = _index(
        snapshot,
        root,
        candidates,
        retag_model,
        FakeStore(state),
        threshold=0.99,
    )

    assert first.status is RunStatus.COMPLETE
    assert second.status is RunStatus.COMPLETE
    assert second.completed_count == 1
    assert second.skipped_count == 0
    assert retag_model.inference_count == 0
    assert len(state.representations) == 1
    assert len(state.decisions) == 2
    prior, current = sorted(
        state.decisions.values(), key=lambda item: item.processed_at
    )
    assert prior.config_fingerprint != current.config_fingerprint
    assert prior.representation_id == current.representation_id
    assert prior.candidate_scores == current.candidate_scores
    assert current.reason == "below_threshold"


def test_changed_candidates_reuse_only_image_vector_and_keep_history(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    state = FakeStoreState()
    first = _index(
        snapshot,
        root,
        [{"id": "bird-a", "name": "Bird A"}, {"id": "bird-b", "name": "Bird B"}],
        FakeModel(model_record),
        FakeStore(state),
    )
    changed_model = FakeModel(model_record)
    second = _index(
        snapshot,
        root,
        [{"id": "bird-a", "name": "Bird A"}, {"id": "bird-c", "name": "Bird C"}],
        changed_model,
        FakeStore(state),
    )

    assert first.status is second.status is RunStatus.COMPLETE
    assert second.completed_count == 1
    assert (changed_model.image_calls, changed_model.text_calls) == (0, 1)
    assert len(state.representations) == 1
    assert len(state.decisions) == 2
    first_decision = next(
        decision
        for decision in state.decisions.values()
        if decision.config_fingerprint == first.config_fingerprint
    )
    second_decision = next(
        decision
        for decision in state.decisions.values()
        if decision.config_fingerprint == second.config_fingerprint
    )
    assert first_decision.representation_id == second_decision.representation_id
    assert {score.id for score in second_decision.candidate_scores} == {
        "bird-a",
        "bird-c",
    }


def test_changed_model_requires_new_image_representation(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    candidates = [{"id": "bird", "name": "Bird"}]
    state = FakeStoreState()
    _index(snapshot, root, candidates, FakeModel(model_record), FakeStore(state))
    other_identity = replace(
        model_record,
        model_fingerprint="5" * 64,
        checkpoint_sha256="6" * 64,
    )
    changed_model = FakeModel(other_identity)

    run = _index(snapshot, root, candidates, changed_model, FakeStore(state))

    assert run.status is RunStatus.COMPLETE
    assert changed_model.image_calls == 1
    assert changed_model.text_calls == 1
    assert len(state.representations) == 2


def test_candidate_reorder_and_crop_relocation_keep_semantic_identity(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    original_root = tmp_path / "original"
    original_root.mkdir()
    original_path = original_root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(original_path)
    snapshot = _snapshot("crop-1", original_path)
    candidates = [
        {"id": "bird-a", "name": "Bird A"},
        {"id": "bird-b", "name": "Bird B"},
    ]
    state = FakeStoreState()
    first = _index(
        snapshot, original_root, candidates, FakeModel(model_record), FakeStore(state)
    )
    relocated_root = tmp_path / "relocated"
    relocated_root.mkdir()
    shutil.copyfile(original_path, relocated_root / original_path.name)
    second_model = FakeModel(model_record)
    second = _index(
        snapshot,
        relocated_root,
        list(reversed(candidates)),
        second_model,
        FakeStore(state),
    )

    assert first.config_fingerprint == second.config_fingerprint
    assert second.skipped_count == 1
    assert second_model.inference_count == 0
    assert len(state.representations) == len(state.decisions) == 1


def test_changed_provenance_invalidates_vector_and_decision_reuse(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    candidates = [{"id": "bird", "name": "Bird"}]
    state = FakeStoreState()
    _index(snapshot, root, candidates, FakeModel(model_record), FakeStore(state))
    changed_snapshot = replace(
        snapshot,
        snapshot_id="8" * 64,
        provenance_sha256="9" * 64,
    )
    changed_model = FakeModel(model_record)

    run = _index(changed_snapshot, root, candidates, changed_model, FakeStore(state))

    assert run.status is RunStatus.COMPLETE
    assert changed_model.image_calls == 1
    assert changed_model.text_calls == 1
    assert len(state.representations) == 2
    assert len(state.decisions) == 2


def test_unchanged_retry_skips_all_completed_crops_without_inference(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    snapshots = []
    for index in range(100):
        image_path = root / f"crop-{index:03}.png"
        Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
        snapshots.append(_snapshot(f"crop-{index:03}", image_path))
    candidates = load_species_candidates(
        _candidate_file(tmp_path / "species.json", [{"id": "bird", "name": "Bird"}])
    )
    state = FakeStoreState()
    store = FakeStore(state)
    first_model = FakeModel(model_record)
    first = index_crops(
        snapshots,
        crop_root=root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=first_model,
        store=store,
    )
    retry_model = FakeModel(model_record)
    retry = index_crops(
        snapshots,
        crop_root=root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=retry_model,
        store=FakeStore(state),
    )

    assert first.completed_count == 100
    assert retry.skipped_count == 100
    assert retry.completed_count == retry.failed_count == 0
    assert retry_model.inference_count == 0
    assert len(state.decisions) == len(state.representations) == 100


def test_newly_unreadable_completed_crop_fails_instead_of_skipping(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    candidates = [{"id": "bird", "name": "Bird"}]
    state = FakeStoreState()
    _index(snapshot, root, candidates, FakeModel(model_record), FakeStore(state))
    image_path.unlink()

    retry = _index(
        snapshot, root, candidates, FakeModel(model_record), FakeStore(state)
    )

    assert retry.status is RunStatus.FAILED
    assert retry.failed_count == 1
    assert retry.skipped_count == 0
    assert state.items[(retry.run_id, snapshot.crop_id)].status is RunItemStatus.FAILED


def test_interrupted_run_recovers_stale_status_and_retries_pending_items(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    snapshots = []
    for index in range(3):
        image_path = root / f"crop-{index}.png"
        Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
        snapshots.append(_snapshot(f"crop-{index}", image_path))
    candidates = load_species_candidates(
        _candidate_file(tmp_path / "species.json", [{"id": "bird", "name": "Bird"}])
    )
    state = FakeStoreState()
    commits = 0

    def interrupt_after_first_commit(stage: str) -> None:
        nonlocal commits
        if stage == "after_crop_commit":
            commits += 1
            if commits == 1:
                raise InterruptedError

    first_store = FakeStore(state, interrupt_after_first_commit)
    with pytest.raises(InterruptedError):
        index_crops(
            snapshots,
            crop_root=root,
            manifest_locator=tmp_path / "manifest.sqlite3",
            candidates=candidates,
            model=FakeModel(model_record),
            store=first_store,
        )
    abandoned_run_id = next(iter(state.runs))

    retry_model = FakeModel(model_record)
    retry = index_crops(
        snapshots,
        crop_root=root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=retry_model,
        store=FakeStore(state),
    )

    assert state.runs[abandoned_run_id].status is RunStatus.INTERRUPTED
    assert state.runs[abandoned_run_id].completed_count == 1
    assert retry.status is RunStatus.COMPLETE
    assert retry.completed_count == 2
    assert retry.skipped_count == 1
    assert retry_model.image_calls == 2
    assert retry_model.text_calls == 1
    assert len(state.decisions) == 3


def test_lost_commit_acknowledgement_is_not_counted_and_retry_reconciles(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    candidates = [{"id": "bird", "name": "Bird"}]
    state = FakeStoreState()

    def lose_acknowledgement(stage: str) -> None:
        if stage == "after_crop_commit":
            raise UnconfirmedCommitError("connection lost after commit")

    uncertain = _index(
        snapshot,
        root,
        candidates,
        FakeModel(model_record),
        FakeStore(state, lose_acknowledgement),
    )
    retry_model = FakeModel(model_record)
    retry = _index(snapshot, root, candidates, retry_model, FakeStore(state))

    assert uncertain.completed_count == 0
    assert uncertain.unconfirmed_crop_ids == (snapshot.crop_id,)
    assert not uncertain.durable_status_confirmed
    assert retry.skipped_count == 1
    assert retry_model.inference_count == 0
    assert len(state.decisions) == 1


def test_shared_model_failure_stops_batch_and_leaves_pending_remainder(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    snapshots = []
    for index in range(3):
        image_path = root / f"crop-{index}.png"
        Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
        snapshots.append(_snapshot(f"crop-{index}", image_path))
    candidates = load_species_candidates(
        _candidate_file(tmp_path / "species.json", [{"id": "bird", "name": "Bird"}])
    )
    state = FakeStoreState()

    run = index_crops(
        snapshots,
        crop_root=root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=FakeModel(model_record, text_results=(SharedModelError("broken model"),)),
        store=FakeStore(state),
    )

    assert run.status is RunStatus.FAILED
    assert run.pending_count == 3
    assert run.failed_count == run.completed_count == 0
    assert all(
        state.items[(run.run_id, snapshot.crop_id)].status is RunItemStatus.PENDING
        for snapshot in snapshots
    )


def test_retag_write_rollback_preserves_previously_committed_representation(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    image_path = root / "crop.png"
    Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
    snapshot = _snapshot("crop-1", image_path)
    candidates = [
        {"id": "bird-a", "name": "Bird A"},
        {"id": "bird-b", "name": "Bird B"},
    ]
    state = FakeStoreState()
    first = _index(
        snapshot, root, candidates, FakeModel(model_record), FakeStore(state)
    )
    original_representation = next(iter(state.representations.values()))

    def fail_retag(stage: str) -> None:
        if stage == "after_decision_insert":
            raise StorageError("write failed")

    failed = _index(
        snapshot,
        root,
        candidates,
        FakeModel(model_record),
        FakeStore(state, fail_retag),
        threshold=0.99,
    )

    assert first.status is RunStatus.COMPLETE
    assert not failed.durable_status_confirmed
    assert state.representations == {
        original_representation.representation_id: original_representation
    }
    assert len(state.decisions) == 1


def test_storage_failure_stops_after_confirmed_commits_and_leaves_pending_items(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    root = tmp_path / "crops"
    root.mkdir()
    snapshots = []
    for index in range(3):
        image_path = root / f"crop-{index}.png"
        Image.new("RGB", (32, 32), (40, 120, 210)).save(image_path)
        snapshots.append(_snapshot(f"crop-{index}", image_path))
    candidates = load_species_candidates(
        _candidate_file(tmp_path / "species.json", [{"id": "bird", "name": "Bird"}])
    )
    state = FakeStoreState()
    commit_attempts = 0

    def fail_second_commit(stage: str) -> None:
        nonlocal commit_attempts
        if stage == "before_crop_commit":
            commit_attempts += 1
            if commit_attempts == 2:
                raise StorageError("simulated storage loss")

    run = index_crops(
        snapshots,
        crop_root=root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=FakeModel(model_record),
        store=FakeStore(state, fail_second_commit),
    )

    persisted_items = [
        state.items[(run.run_id, snapshot.crop_id)] for snapshot in snapshots
    ]
    assert run.status is RunStatus.FAILED
    assert not run.durable_status_confirmed
    assert run.completed_count == 1
    assert run.pending_count == 2
    assert sum(item.status is RunItemStatus.COMPLETED for item in persisted_items) == 1
    assert sum(item.status is RunItemStatus.PENDING for item in persisted_items) == 2
    assert len(state.decisions) == len(state.representations) == 1
