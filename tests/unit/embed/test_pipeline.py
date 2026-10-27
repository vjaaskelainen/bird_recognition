from __future__ import annotations

import hashlib
import json
from dataclasses import replace
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
from bird_recognition.embed.reference import (
    ReferenceExample,
    ReferenceSet,
    input_view_fingerprint,
)
from tests.unit.embed.fakes import FakeModel, FakeStore, FakeStoreState


def _snapshot(
    crop_id: str,
    path: Path,
    image_bytes: bytes,
    size: tuple[int, int] = (40, 40),
) -> IngestedCropSnapshot:
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
        "crop_box_pixels": (0, 0, *size),
        "frame_width": size[0],
        "frame_height": size[1],
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


def _typed_candidate_file(tmp_path: Path) -> Path:
    path = tmp_path / "typed-candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "candidates": [
                    {
                        "id": "great_tit",
                        "kind": "species",
                        "common_name": "Great tit",
                        "taxonomic_description": "Parus major",
                    },
                    {
                        "id": "broad_bird",
                        "kind": "category",
                        "category": "bird",
                        "common_name": "Bird",
                        "taxonomic_description": "An unidentified bird",
                    },
                    {
                        "id": "broad_mammal",
                        "kind": "category",
                        "category": "mammal",
                        "common_name": "Mammal",
                        "taxonomic_description": "An unidentified mammal",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _new_crops(
    tmp_path: Path,
    count: int,
    size: tuple[int, int] = (40, 40),
) -> tuple[list[IngestedCropSnapshot], Path]:
    root = tmp_path / "crops"
    root.mkdir()
    snapshots = []
    for index in range(count):
        crop_id = f"crop-{index:03}"
        path = root / f"{crop_id}.png"
        Image.new("RGB", size, (20 + index % 200, 80, 130)).save(path)
        image_bytes = path.read_bytes()
        snapshots.append(_snapshot(crop_id, path, image_bytes, size))
    return snapshots, root


def test_index_crops_uses_typed_taxonomy_prompts_and_preserves_coarse_candidate(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1)
    candidates = load_species_candidates(_typed_candidate_file(tmp_path))
    state = FakeStoreState()
    model = FakeModel(model_record)

    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=model,
        store=FakeStore(state),
        threshold=0.1,
    )

    decision = next(iter(state.decisions.values()))
    assert model.prompts == [
        (
            "a photo of Bird (An unidentified bird).",
            "a photo of Mammal (An unidentified mammal).",
            "a photo of Great tit (Parus major).",
        )
    ]
    assert run.candidate_schema_version == 2
    assert run.prompt_version == "species-taxonomy-photo-v2"
    assert run.prompt_template == "a photo of {common_name} ({taxonomic_description})."
    assert decision.assigned_species_id == "broad_bird"
    assert state.candidate_sets[candidates.candidate_set_fingerprint].candidates[
        0
    ].kind == ("category")


@pytest.mark.parametrize(
    ("reference_examples", "expected_path", "expected_species"),
    [
        (3, "reference_match", "bird"),
        (2, "zero_shot_fallback", "bird"),
    ],
)
def test_index_crops_records_reference_path_and_falls_back_when_too_few_neighbors(
    tmp_path: Path,
    model_record: EmbeddingModelRecord,
    reference_examples: int,
    expected_path: str,
    expected_species: str,
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1)
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    model_identity = replace(
        model_record,
        preprocessing_json=json.dumps({"input_view": {"version": "fit-pad-v1"}}),
    )
    model = FakeModel(model_identity)
    references = ReferenceSet(
        set_id="set",
        fingerprint="5" * 64,
        model_fingerprint=model_identity.model_fingerprint,
        input_view_fingerprint=input_view_fingerprint(model),
        review_provenance="owner-reviewed",
        examples=tuple(
            ReferenceExample(
                f"reference-{index}",
                "reference-video",
                "2025-01-01",
                "bird",
                tmp_path / f"reference-{index}.png",
                (1.0, 0.0, 0.0),
            )
            for index in range(reference_examples)
        ),
    )
    state = FakeStoreState()

    run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=model,
        store=FakeStore(state),
        reference_set=references,
        reference_min_similarity=0.8,
        reference_min_agreement=0.75,
    )

    decision = next(iter(state.decisions.values()))
    assert run.completed_count == 1
    assert decision.assigned_species_id == expected_species
    assert decision.decision_path == expected_path
    assert decision.reference_set_fingerprint == references.fingerprint
    assert decision.reference_split_mode == "source_video"
    assert (decision.reason == "reference_match") == (
        expected_path == "reference_match"
    )


def test_index_crops_persists_100_results_and_restart_inspects_provenance(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 100)
    source_bytes = {
        snapshot.crop_id: (crop_root / snapshot.crop_original_image_path).read_bytes()
        for snapshot in snapshots
    }
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
    assert {
        snapshot.crop_id: (crop_root / snapshot.crop_original_image_path).read_bytes()
        for snapshot in snapshots
    } == source_bytes
    settings = json.loads(run.sanitized_settings_json)
    assert set(settings) == {
        "candidate_set_fingerprint",
        "minimum_crop_height",
        "minimum_crop_width",
        "model_fingerprint",
        "threshold",
    }
    assert "private-password" not in run.sanitized_settings_json
    assert "postgresql://" not in run.sanitized_settings_json


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
    model = FakeModel(
        model_record,
        text_results=(
            SharedModelError(
                "connection failed for "
                "postgresql://private-user:private-password@db.example/private_db"
            ),
        ),
    )
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
    exposed_output = run.sanitized_settings_json + json.dumps(
        [failure.reason for failure in run.failures]
    )
    assert "private-user" not in exposed_output
    assert "private-password" not in exposed_output
    assert "db.example" not in exposed_output


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


def test_index_crops_marks_undersized_crop_low_quality_without_scores(
    tmp_path: Path, model_record: EmbeddingModelRecord
) -> None:
    snapshots, crop_root = _new_crops(tmp_path, 1, size=(20, 40))
    candidates = load_species_candidates(
        _candidate_file(tmp_path, [{"id": "bird", "name": "Bird"}])
    )
    state = FakeStoreState()
    first_run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=FakeModel(model_record),
        store=FakeStore(state),
        minimum_crop_width=10,
        minimum_crop_height=10,
    )
    model = FakeModel(model_record)
    quality_run = index_crops(
        snapshots,
        crop_root=crop_root,
        manifest_locator=tmp_path / "manifest.sqlite3",
        candidates=candidates,
        model=model,
        store=FakeStore(state),
    )

    decision = max(state.decisions.values(), key=lambda item: item.processed_at)
    assert first_run.status is quality_run.status is RunStatus.COMPLETE
    assert (
        quality_run.completed_count,
        quality_run.assigned_count,
        quality_run.unknown_count,
    ) == (1, 0, 1)
    assert next(iter(state.decisions.values())).assigned_species_id is not None
    assert decision.reason == "low_quality"
    assert decision.assigned_species_id is None
    assert decision.best_candidate_id is None
    assert decision.confidence is None
    assert decision.candidate_scores == ()
    assert model.image_calls == 0
    assert model.text_calls == 0


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
