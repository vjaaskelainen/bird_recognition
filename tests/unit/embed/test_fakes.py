import socket
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image

from bird_recognition.embed.models import (
    CandidateScore,
    CropRepresentation,
    EmbeddingModelRecord,
    IngestedCropSnapshot,
    Lighting,
    ProcessingRun,
    RunItem,
    RunItemStatus,
    RunStatus,
    SpeciesDecision,
    UnconfirmedCommitError,
)
from tests.unit.embed.fakes import FakeModel, FakeStore, FakeStoreState


def _create_run(now: datetime) -> ProcessingRun:
    return ProcessingRun(
        run_id=uuid4(),
        started_at=now,
        completed_at=None,
        status=RunStatus.RUNNING,
        config_fingerprint="1" * 64,
        manifest_locator=Path("manifest.sqlite3"),
        crop_root=None,
        selection_fingerprint="2" * 64,
        selected_count=1,
        completed_count=0,
        skipped_count=0,
        failed_count=0,
        assigned_count=0,
        unknown_count=0,
        failures=(),
        sanitized_settings_json="{}",
    )


def _create_crop_result(
    run: ProcessingRun, model_fingerprint: str, now: datetime
) -> tuple[IngestedCropSnapshot, CropRepresentation, SpeciesDecision, RunItem]:
    snapshot_id = "3" * 64
    provenance_sha256 = "4" * 64
    snapshot = IngestedCropSnapshot(
        snapshot_id=snapshot_id,
        crop_id="crop-1",
        provenance_sha256=provenance_sha256,
        crop_sha256="5" * 64,
        source_id="source-1",
        source_content_sha256="6" * 64,
        source_original_path="source.mp4",
        source_basename="source.mp4",
        ingest_settings_fingerprint="7" * 64,
        ingestion_run_id="ingest-run-1",
        frame_number=0,
        elapsed_seconds=0.0,
        detection_id="detection-1",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.0, 0.0, 1.0, 1.0),
        crop_box_pixels=(0, 0, 32, 24),
        frame_width=32,
        frame_height=24,
        crop_original_image_path="crops/crop-1.png",
        capture_time=None,
        capture_timezone=None,
        source_capture_start=None,
        source_capture_timezone=None,
        lighting=Lighting.DAY,
        imported_at=now,
    )
    representation_id = uuid4()
    representation = CropRepresentation(
        representation_id=representation_id,
        snapshot_id=snapshot_id,
        model_fingerprint=model_fingerprint,
        embedding=(1.0, 0.0, 0.0),
        processed_at=now,
        created_run_id=run.run_id,
    )
    decision = SpeciesDecision(
        decision_id=uuid4(),
        representation_id=representation_id,
        config_fingerprint=run.config_fingerprint,
        assigned_species_id="bird",
        best_candidate_id="bird",
        confidence=1.0,
        tied_candidate_ids=(),
        candidate_scores=(CandidateScore("bird", 1.0, 1.0),),
        reason="assigned",
        warnings=(),
        processed_at=now,
        created_run_id=run.run_id,
    )
    item = RunItem(
        run_id=run.run_id,
        crop_id=snapshot.crop_id,
        expected_snapshot_id=snapshot_id,
        expected_provenance_sha256=provenance_sha256,
        resolved_input_locator=Path("crop.png"),
        status=RunItemStatus.COMPLETED,
        decision_id=decision.decision_id,
        failure_code=None,
        failure_reason=None,
        started_at=now,
        completed_at=now,
        lighting=snapshot.lighting,
    )
    return snapshot, representation, decision, item


def test_fake_model_counts_calls_and_returns_repeatable_vectors(
    fake_model: FakeModel,
) -> None:
    first_image = fake_model.encode_image(object())
    second_image = fake_model.encode_image(object())
    first_text = fake_model.encode_texts(("a photo of a bird.", "a photo of a duck."))
    second_text = fake_model.encode_texts(("a photo of a bird.", "a photo of a duck."))

    assert first_image == second_image == (1.0, 0.0, 0.0)
    assert first_text == second_text
    assert fake_model.image_calls == 2
    assert fake_model.text_calls == 2
    assert fake_model.inference_count == 4


def test_embed_fixtures_create_image_and_real_ingestion_schema(
    generated_crop: Path, ingestion_schema: Path
) -> None:
    with Image.open(generated_crop) as image:
        assert image.size == (32, 24)
        assert image.getpixel((0, 0)) == (40, 120, 210)

    with sqlite3.connect(ingestion_schema) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert {
        "ingestion_run",
        "source_video",
        "run_source",
        "sampled_frame",
        "detection",
        "animal_crop",
    } <= tables


def test_embed_tests_deny_network_by_default() -> None:
    with pytest.raises(OSError, match="network access is disabled"):
        socket.getaddrinfo("example.invalid", 443)


def test_fake_store_rolls_back_insert_failures_and_survives_restart(
    model_record: EmbeddingModelRecord,
) -> None:
    now = datetime.now(UTC)
    run = _create_run(now)
    snapshot, representation, decision, completed_item = _create_crop_result(
        run, model_record.model_fingerprint, now
    )
    pending_item = RunItem(
        run_id=run.run_id,
        crop_id=snapshot.crop_id,
        expected_snapshot_id=snapshot.snapshot_id,
        expected_provenance_sha256=snapshot.provenance_sha256,
        resolved_input_locator=Path("crop.png"),
        status=RunItemStatus.PENDING,
        decision_id=None,
        failure_code=None,
        failure_reason=None,
        started_at=now,
        completed_at=None,
        lighting=snapshot.lighting,
    )
    state = FakeStoreState()

    def fail_after_representation_insert(stage: str) -> None:
        if stage == "after_representation_insert":
            raise RuntimeError("simulated transaction failure")

    store = FakeStore(state, fail_after_representation_insert)
    store.register_run(run, (pending_item,))

    with pytest.raises(RuntimeError, match="simulated transaction failure"):
        store.commit_crop_result(snapshot, representation, decision, completed_item)

    assert state.snapshots == {}
    assert state.representations == {}
    assert state.decisions == {}
    assert state.items[(run.run_id, snapshot.crop_id)] == pending_item
    assert state.runs[run.run_id].completed_count == 0

    restarted_store = FakeStore(state)
    restarted_store.commit_crop_result(
        snapshot, representation, decision, completed_item
    )

    assert (
        restarted_store.get_completed_decision(
            snapshot.snapshot_id,
            representation.model_fingerprint,
            decision.config_fingerprint,
        )
        == decision
    )
    assert (
        restarted_store.get_compatible_representation(
            snapshot.snapshot_id, representation.model_fingerprint
        )
        == representation
    )
    assert state.items[(run.run_id, snapshot.crop_id)] == completed_item
    assert state.runs[run.run_id].completed_count == 1


def test_fake_store_reconciles_lost_commit_acknowledgement_after_restart(
    model_record: EmbeddingModelRecord,
) -> None:
    now = datetime.now(UTC)
    run = _create_run(now)
    snapshot, representation, decision, completed_item = _create_crop_result(
        run, model_record.model_fingerprint, now
    )
    pending_item = RunItem(
        run_id=run.run_id,
        crop_id=snapshot.crop_id,
        expected_snapshot_id=snapshot.snapshot_id,
        expected_provenance_sha256=snapshot.provenance_sha256,
        resolved_input_locator=Path("crop.png"),
        status=RunItemStatus.PENDING,
        decision_id=None,
        failure_code=None,
        failure_reason=None,
        started_at=now,
        completed_at=None,
        lighting=snapshot.lighting,
    )
    state = FakeStoreState()

    def lose_acknowledgement(stage: str) -> None:
        if stage == "after_crop_commit":
            raise UnconfirmedCommitError("simulated lost acknowledgement")

    store = FakeStore(state, lose_acknowledgement)
    store.register_run(run, (pending_item,))

    with pytest.raises(UnconfirmedCommitError, match="simulated lost acknowledgement"):
        store.commit_crop_result(snapshot, representation, decision, completed_item)

    restarted_store = FakeStore(state)

    assert (
        restarted_store.get_completed_decision(
            snapshot.snapshot_id,
            representation.model_fingerprint,
            decision.config_fingerprint,
        )
        == decision
    )
    assert state.runs[run.run_id].completed_count == 1
