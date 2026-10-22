from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
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
    UnconfirmedCommitError,
)
from bird_recognition.embed.scoring import score_embeddings
from bird_recognition.embed.storage import PgVectorStore, initialize_database


class _LostCommitAcknowledgement:
    def __init__(
        self, transaction: Any, connection: Any, *, after_commit: bool
    ) -> None:
        self._transaction = transaction
        self._connection = connection
        self._after_commit = after_commit

    def __enter__(self) -> Any:
        return self._transaction.__enter__()

    def __exit__(self, error_type: Any, error: Any, traceback: Any) -> Any:
        if error_type is None and not self._after_commit:
            self._connection.close()
            try:
                self._transaction.__exit__(error_type, error, traceback)
            except Exception:
                pass
            raise psycopg.OperationalError("simulated connection loss during commit")
        result = self._transaction.__exit__(error_type, error, traceback)
        if error_type is None and self._after_commit:
            self._connection.close()
            raise psycopg.OperationalError("simulated commit acknowledgement loss")
        return result


class _ConnectionWithLostCommitAcknowledgement:
    def __init__(self, connection: Any, *, after_commit: bool) -> None:
        self._connection = connection
        self._after_commit = after_commit

    def transaction(self) -> _LostCommitAcknowledgement:
        return _LostCommitAcknowledgement(
            self._connection.transaction(),
            self._connection,
            after_commit=self._after_commit,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


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

    vector_values = vector.to_list()
    assert len(vector_values) == 512
    assert vector_values[0] == pytest.approx(1.0)
    assert sum(value * value for value in vector_values) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.real_database
def test_writer_lock_rejects_concurrent_writer_and_releases_on_connection_death(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    first = PgVectorStore(disposable_embed_schema)
    second = PgVectorStore(disposable_embed_schema)
    first.preflight()
    first.acquire_writer_lock()

    with pytest.raises(StorageError, match="writer_busy"):
        second.acquire_writer_lock()

    assert first._writer_connection is not None
    first._writer_connection.close()
    second.acquire_writer_lock()
    second.release_writer_lock()


@pytest.mark.real_database
def test_stale_run_recovery_preserves_pending_items_and_lighting(
    disposable_embed_schema: str, tmp_path: Path
) -> None:
    initialize_database(disposable_embed_schema)
    now = datetime.now(UTC)
    model = EmbeddingModelRecord(
        model_fingerprint="a" * 64,
        upstream_name="imageomics/bioclip",
        upstream_revision="a" * 40,
        checkpoint_sha256="b" * 64,
        config_sha256="c" * 64,
        tokenizer_sha256="d" * 64,
        architecture="ViT-B-16",
        dimension=512,
        preprocessing_json="{}",
        tokenizer_json="{}",
        adapter_version="integration-test-v1",
        runtime_json="{}",
        logit_scale=1.0,
        canonical_json="{}",
    )
    species_path = tmp_path / "recovery-species.json"
    species_path.write_text(
        '{"schema_version":1,"species":[{"id":"bird","name":"Bird"}]}',
        encoding="utf-8",
    )
    candidates = load_species_candidates(species_path)
    config = build_tagging_config(model, candidates, 0.5)
    run_id = uuid4()
    run = ProcessingRun(
        run_id=run_id,
        started_at=now,
        completed_at=None,
        status=RunStatus.RUNNING,
        config_fingerprint=config.config_fingerprint,
        manifest_locator=tmp_path / "manifest.sqlite3",
        crop_root=tmp_path,
        selection_fingerprint="e" * 64,
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
        crop_id="pending-crop",
        expected_snapshot_id=None,
        expected_provenance_sha256="f" * 64,
        resolved_input_locator=tmp_path / "unread-crop.png",
        status=RunItemStatus.PENDING,
        decision_id=None,
        failure_code=None,
        failure_reason=None,
        started_at=now,
        completed_at=None,
        lighting=Lighting.NIGHT,
    )
    store = PgVectorStore(disposable_embed_schema)
    store.preflight()
    store.acquire_writer_lock()
    try:
        store.register_run(run, (pending_item,), model, candidates, config)
        store.recover_stale_runs()
    finally:
        store.release_writer_lock()

    summary, items = PgVectorStore(disposable_embed_schema).inspect_run(run_id)

    assert summary["status"] == "interrupted"
    assert summary["counts"]["pending"] == 1
    assert items[0]["status"] == "pending"
    assert items[0]["lighting"] == "night"
    assert items[0]["decision"] is None


@pytest.mark.real_database
@pytest.mark.parametrize("after_commit", [False, True])
def test_storage_atomically_persists_and_inspects_crop_across_connections(
    disposable_embed_schema: str, tmp_path: Path, after_commit: bool
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
        lighting=snapshot.lighting,
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
        lighting=snapshot.lighting,
    )
    writer = PgVectorStore(disposable_embed_schema)
    writer.preflight()
    writer.acquire_writer_lock()
    try:
        writer.register_run(run, (pending_item,), model, candidates, config)
        assert writer._writer_connection is not None
        writer._writer_connection = _ConnectionWithLostCommitAcknowledgement(
            writer._writer_connection, after_commit=after_commit
        )
        with pytest.raises(UnconfirmedCommitError, match="unconfirmed"):
            writer.commit_crop_result(snapshot, representation, decision, complete_item)
        writer._writer_connection = None
        writer = PgVectorStore(disposable_embed_schema)
        writer.acquire_writer_lock()
        writer.recover_stale_runs()
        retry_run_id = uuid4()
        retry_run = ProcessingRun(
            run_id=retry_run_id,
            started_at=now,
            completed_at=None,
            status=RunStatus.RUNNING,
            config_fingerprint=config.config_fingerprint,
            manifest_locator=tmp_path / "manifest.sqlite3",
            crop_root=tmp_path,
            selection_fingerprint="b" * 64,
            selected_count=1,
            completed_count=0,
            skipped_count=0,
            failed_count=0,
            assigned_count=0,
            unknown_count=0,
            failures=(),
            sanitized_settings_json="{}",
        )
        retry_item = RunItem(
            run_id=retry_run_id,
            crop_id=snapshot.crop_id,
            expected_snapshot_id=snapshot.snapshot_id,
            expected_provenance_sha256=snapshot.provenance_sha256,
            resolved_input_locator=pending_item.resolved_input_locator,
            status=RunItemStatus.PENDING,
            decision_id=None,
            failure_code=None,
            failure_reason=None,
            started_at=now,
            completed_at=None,
            lighting=snapshot.lighting,
        )
        writer.register_run(retry_run, (retry_item,), model, candidates, config)
        durable_decision = writer.get_completed_decision(
            snapshot.snapshot_id, model.model_fingerprint, config.config_fingerprint
        )
        if after_commit:
            assert durable_decision == decision
            expected_representation = representation
            expected_decision = decision
            writer.mark_item_skipped(
                RunItem(
                    run_id=retry_run_id,
                    crop_id=snapshot.crop_id,
                    expected_snapshot_id=snapshot.snapshot_id,
                    expected_provenance_sha256=snapshot.provenance_sha256,
                    resolved_input_locator=pending_item.resolved_input_locator,
                    status=RunItemStatus.SKIPPED,
                    decision_id=decision.decision_id,
                    failure_code=None,
                    failure_reason=None,
                    started_at=now,
                    completed_at=now,
                    lighting=snapshot.lighting,
                )
            )
            final_retry_run = replace(
                retry_run, completed_at=now, status=RunStatus.COMPLETE, skipped_count=1
            )
        else:
            assert durable_decision is None
            expected_representation = replace(
                representation, representation_id=uuid4(), created_run_id=retry_run_id
            )
            expected_decision = replace(
                decision,
                decision_id=uuid4(),
                representation_id=expected_representation.representation_id,
                created_run_id=retry_run_id,
            )
            completed_retry_item = replace(
                retry_item,
                status=RunItemStatus.COMPLETED,
                decision_id=expected_decision.decision_id,
                completed_at=now,
            )
            assert writer.commit_crop_result(
                snapshot,
                expected_representation,
                expected_decision,
                completed_retry_item,
            )
            final_retry_run = replace(
                retry_run,
                completed_at=now,
                status=RunStatus.COMPLETE,
                completed_count=1,
                assigned_count=1,
            )
        writer.finalize_run(final_retry_run)
    finally:
        writer.release_writer_lock()

    reader = PgVectorStore(disposable_embed_schema)
    persisted = reader.get_completed_decision(
        snapshot.snapshot_id, model.model_fingerprint, config.config_fingerprint
    )

    assert (
        reader.get_compatible_representation(
            snapshot.snapshot_id, model.model_fingerprint
        )
        == expected_representation
    )
    assert persisted == expected_decision
    run_summary, items = reader.inspect_run(retry_run_id)
    recovered_summary, _ = reader.inspect_run(run_id)
    assert recovered_summary["status"] == "interrupted"
    assert recovered_summary["counts"]["completed"] == int(after_commit)
    assert run_summary["counts"]["skipped"] == int(after_commit)
    assert run_summary["counts"]["completed"] == int(not after_commit)
    assert items[0]["status"] == ("skipped" if after_commit else "completed")
    assert items[0]["provenance"]["lighting"] == "unknown"
    assert items[0]["provenance"]["capture_time"] is None
