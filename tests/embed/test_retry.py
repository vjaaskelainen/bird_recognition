from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from bird_recognition.embed.config import load_species_candidates
from bird_recognition.embed.models import (
    EmbeddingModelRecord,
    IngestedCropSnapshot,
    Lighting,
    RunStatus,
)
from bird_recognition.embed.pipeline import index_crops
from tests.embed.fakes import FakeModel, FakeStore, FakeStoreState


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
        crop_box_pixels=(0, 0, 32, 24),
        frame_width=32,
        frame_height=24,
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
    Image.new("RGB", (32, 24), (40, 120, 210)).save(image_path)
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
    Image.new("RGB", (32, 24), (40, 120, 210)).save(image_path)
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
    Image.new("RGB", (32, 24), (40, 120, 210)).save(image_path)
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
    Image.new("RGB", (32, 24), (40, 120, 210)).save(original_path)
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
    Image.new("RGB", (32, 24), (40, 120, 210)).save(image_path)
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
