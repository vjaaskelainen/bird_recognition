from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from pgvector import Vector
from pgvector.psycopg import register_vector

from bird_recognition.embed.config import (
    build_tagging_config,
    load_species_candidates,
    validate_local_database_url,
)
from bird_recognition.embed.models import (
    CropRepresentation,
    EmbeddingModelRecord,
    IngestedCropSnapshot,
    Lighting,
    ProcessingRun,
    RunItem,
    RunItemStatus,
    RunStatus,
    SpeciesDecision,
    StorageError,
)
from bird_recognition.embed.scoring import score_embeddings
from bird_recognition.embed.storage import PgVectorStore, initialize_database


@pytest.fixture
def database_url() -> str:
    value = os.environ.get("BIRD_RECOGNITION_TEST_DATABASE_URL")
    if not value:
        pytest.skip("explicit disposable test database URL is required")
    validate_local_database_url(value)
    if "test" not in urlsplit(value).path.strip("/").casefold():
        pytest.skip("test database name must include 'test' before schema cleanup")
    return value


@pytest.fixture
def disposable_embed_schema(database_url: str) -> str:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS bird_embed CASCADE")
    yield database_url
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS bird_embed CASCADE")


@pytest.mark.real_database
def test_database_init_is_transactional_and_idempotent(
    disposable_embed_schema: str,
) -> None:
    first = initialize_database(disposable_embed_schema)
    second = initialize_database(disposable_embed_schema)

    assert first.schema_version == 1
    assert first.vector_available
    assert first.changes_applied
    assert not second.changes_applied


@pytest.mark.real_database
def test_storage_preflight_rejects_unknown_schema_version(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    with psycopg.connect(disposable_embed_schema) as connection:
        connection.execute(
            "UPDATE bird_embed.schema_version SET version = 999 WHERE singleton"
        )

    with pytest.raises(StorageError):
        PgVectorStore(disposable_embed_schema).preflight()


@pytest.mark.real_database
def test_pgvector_roundtrips_normalized_512_float_vector(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    values = [0.0] * 512
    values[0] = 1.0
    with psycopg.connect(disposable_embed_schema) as connection:
        register_vector(connection)
        vector = connection.execute("SELECT %s::vector", (Vector(values),)).fetchone()[
            0
        ]

    assert len(vector) == 512
    assert vector[0] == pytest.approx(1.0)
    assert sum(value * value for value in vector) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.real_database
def test_storage_atomically_persists_and_inspects_crop_across_connections(
    disposable_embed_schema: str, tmp_path: Path
) -> None:
    initialize_database(disposable_embed_schema)
    now = datetime.now(UTC)
    model = EmbeddingModelRecord(
        model_fingerprint="1" * 64,
        upstream_name="imageomics/bioclip",
        upstream_revision="a" * 40,
        checkpoint_sha256="2" * 64,
        config_sha256="3" * 64,
        tokenizer_sha256="4" * 64,
        architecture="ViT-B-16",
        dimension=512,
        preprocessing_json="{}",
        tokenizer_json="{}",
        adapter_version="integration-test-v1",
        runtime_json="{}",
        logit_scale=1.0,
        canonical_json="{}",
    )
    species_path = tmp_path / "species.json"
    species_path.write_text(
        '{"schema_version":1,"species":['
        '{"id":"bird-a","name":"Bird A"},'
        '{"id":"bird-b","name":"Bird B"}]}',
        encoding="utf-8",
    )
    candidates = load_species_candidates(species_path)
    config = build_tagging_config(model, candidates, 0.5)
    run_id = uuid4()
    snapshot = IngestedCropSnapshot(
        snapshot_id="5" * 64,
        crop_id="crop-integration-1",
        provenance_sha256="6" * 64,
        crop_sha256="7" * 64,
        source_id="source-1",
        source_content_sha256="8" * 64,
        source_original_path="synthetic/source.mp4",
        source_basename="source.mp4",
        ingest_settings_fingerprint="9" * 64,
        ingestion_run_id="ingest-run-1",
        frame_number=0,
        elapsed_seconds=0.0,
        detection_id="detection-1",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.1, 0.1, 0.9, 0.9),
        crop_box_pixels=(1, 1, 20, 20),
        frame_width=20,
        frame_height=20,
        crop_original_image_path="crops/crop.png",
        capture_time=None,
        capture_timezone=None,
        source_capture_start=None,
        source_capture_timezone=None,
        lighting=Lighting.UNKNOWN,
        imported_at=now,
    )
    vector = (1.0,) + (0.0,) * 511
    text_vectors = (vector, (0.0, 1.0) + (0.0,) * 510)
    scored = score_embeddings(
        vector,
        text_vectors,
        candidates.candidates,
        logit_scale=config.effective_logit_scale,
        threshold=config.threshold,
    )
    representation = CropRepresentation(
        representation_id=uuid4(),
        snapshot_id=snapshot.snapshot_id,
        model_fingerprint=model.model_fingerprint,
        embedding=vector,
        processed_at=now,
        created_run_id=run_id,
    )
    decision = SpeciesDecision(
        decision_id=uuid4(),
        representation_id=representation.representation_id,
        config_fingerprint=config.config_fingerprint,
        assigned_species_id=scored.assigned_species_id,
        best_candidate_id=scored.best_candidate_id,
        confidence=scored.confidence,
        tied_candidate_ids=scored.tied_candidate_ids,
        candidate_scores=scored.scores,
        reason=scored.reason,
        warnings=scored.warnings,
        processed_at=now,
        created_run_id=run_id,
    )
    run = ProcessingRun(
        run_id=run_id,
        started_at=now,
        completed_at=None,
        status=RunStatus.RUNNING,
        config_fingerprint=config.config_fingerprint,
        manifest_locator=tmp_path / "manifest.sqlite3",
        crop_root=tmp_path,
        selection_fingerprint="a" * 64,
        selected_count=1,
        completed_count=0,
        skipped_count=0,
        failed_count=0,
        assigned_count=0,
        unknown_count=0,
        failures=(),
        sanitized_settings_json="{}",
    )
    pending_item = RunItem(
        run_id=run_id,
        crop_id=snapshot.crop_id,
        expected_snapshot_id=snapshot.snapshot_id,
        expected_provenance_sha256=snapshot.provenance_sha256,
        resolved_input_locator=tmp_path / "crops" / "crop.png",
        status=RunItemStatus.PENDING,
        decision_id=None,
        failure_code=None,
        failure_reason=None,
        started_at=now,
        completed_at=None,
    )
    complete_item = RunItem(
        run_id=run_id,
        crop_id=snapshot.crop_id,
        expected_snapshot_id=snapshot.snapshot_id,
        expected_provenance_sha256=snapshot.provenance_sha256,
        resolved_input_locator=pending_item.resolved_input_locator,
        status=RunItemStatus.COMPLETED,
        decision_id=decision.decision_id,
        failure_code=None,
        failure_reason=None,
        started_at=now,
        completed_at=now,
    )
    writer = PgVectorStore(disposable_embed_schema)
    writer.preflight()
    writer.acquire_writer_lock()
    try:
        writer.register_run(run, (pending_item,), model, candidates, config)
        assert writer.commit_crop_result(
            snapshot, representation, decision, complete_item
        )
    finally:
        writer.release_writer_lock()

    reader = PgVectorStore(disposable_embed_schema)
    persisted = reader.get_completed_decision(
        snapshot.snapshot_id, model.model_fingerprint, config.config_fingerprint
    )

    assert persisted == decision
    assert (
        reader.get_compatible_representation(
            snapshot.snapshot_id, model.model_fingerprint
        )
        == representation
    )
    run_summary, items = reader.inspect_run(run_id)
    assert run_summary["counts"]["completed"] == 1
    assert items[0]["provenance"]["lighting"] == "unknown"
    assert items[0]["provenance"]["capture_time"] is None
