from __future__ import annotations

import os
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID, uuid4

import psycopg
import pytest
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.sql import SQL, Identifier, Literal
from psycopg.types.json import Jsonb

from bird_recognition.embed.config import (
    build_tagging_config,
    load_species_candidates,
    validate_local_database_url,
)
from bird_recognition.embed.migrate import apply_pending_migrations
from bird_recognition.embed.models import (
    CropRepresentation,
    EmbeddingModelRecord,
    EmbedValidationError,
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


class _ConnectionWithFailureAfterStatement:
    def __init__(self, connection: Any, statement: str) -> None:
        self._connection = connection
        self._statement = statement
        self._failed = False

    def transaction(self) -> Any:
        return self._connection.transaction()

    def execute(self, query: Any, *args: Any, **kwargs: Any) -> Any:
        result = self._connection.execute(query, *args, **kwargs)
        if not self._failed and self._statement in str(query):
            self._failed = True
            self._connection.close()
            raise psycopg.OperationalError("simulated connection loss during write")
        return result

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


def _drop_temporary_test_roles(connection: psycopg.Connection[Any]) -> None:
    roles = connection.execute(
        "SELECT rolname FROM pg_roles WHERE rolname LIKE 'bird_embed_test_%'"
    ).fetchall()
    for (role_name,) in roles:
        role = Identifier(role_name)
        connection.execute(SQL("DROP OWNED BY {}").format(role))
        connection.execute(
            SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                Identifier(connection.info.dbname), role
            )
        )
        connection.execute(SQL("DROP ROLE IF EXISTS {}").format(role))


def _insert_representation_prerequisites(
    connection: psycopg.Connection[Any],
) -> tuple[str, str, str, UUID]:
    now = datetime.now(UTC)
    model_fingerprint = "a" * 64
    candidate_fingerprint = "b" * 64
    config_fingerprint = "c" * 64
    snapshot_id = "d" * 64
    run_id = uuid4()
    connection.execute(
        "INSERT INTO bird_embed.embedding_model "
        "(model_fingerprint,upstream_name,upstream_revision,checkpoint_sha256,"
        "config_sha256,tokenizer_sha256,architecture,dimension,preprocessing_json,"
        "tokenizer_json,adapter_version,runtime_json,logit_scale,canonical_json) "
        "VALUES (%s,'test','revision',%s,%s,%s,'ViT-B-16',512,'{}','{}','test',"
        "'{}',1,'{}')",
        (model_fingerprint, "1" * 64, "2" * 64, "3" * 64),
    )
    connection.execute(
        "INSERT INTO bird_embed.candidate_set "
        "(candidate_set_fingerprint,schema_version,candidates_json,canonical_json) "
        'VALUES (%s,1,\'[{"id":"bird","name":"Bird"}]\',\'{}\')',
        (candidate_fingerprint,),
    )
    connection.execute(
        "INSERT INTO bird_embed.tagging_config "
        "(config_fingerprint,model_fingerprint,candidate_set_fingerprint,"
        "scoring_fingerprint,prompt_template,prompt_version,effective_logit_scale,"
        "scoring_json,threshold,canonical_json) "
        "VALUES (%s,%s,%s,%s,'a photo of {name}.','species-photo-v1',1,'{}',0.5,'{}')",
        (config_fingerprint, model_fingerprint, candidate_fingerprint, "e" * 64),
    )
    connection.execute(
        "INSERT INTO bird_embed.processing_run "
        "(run_id,started_at,status,config_fingerprint,manifest_locator,"
        "selection_fingerprint,selected_count,completed_count,skipped_count,"
        "failed_count,assigned_count,unknown_count,failures_json,"
        "sanitized_settings_json) "
        "VALUES (%s,%s,'running',%s,'manifest',%s,0,0,0,0,0,0,'[]','{}')",
        (run_id, now, config_fingerprint, "f" * 64),
    )
    connection.execute(
        "INSERT INTO bird_embed.crop_snapshot "
        "(snapshot_id,crop_id,provenance_sha256,crop_sha256,source_id,"
        "source_content_sha256,source_original_path,source_basename,"
        "ingest_settings_fingerprint,ingestion_run_id,frame_number,elapsed_seconds,"
        "detection_id,detection_category,detection_confidence,"
        "detection_box_normalized,crop_box_pixels,frame_width,frame_height,"
        "crop_original_image_path,lighting,imported_at) "
        "VALUES (%s,'crop',%s,%s,'source',%s,'source.mp4','source.mp4',%s,'ingest',"
        "0,0,'detection','animal',0.9,'[0.1,0.1,0.9,0.9]','[0,0,20,20]',"
        "20,20,'crop.png','unknown',%s)",
        (snapshot_id, "4" * 64, "5" * 64, "6" * 64, "7" * 64, now),
    )
    return snapshot_id, model_fingerprint, config_fingerprint, run_id


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
def test_migration_runner_applies_only_missing_revisions(
    disposable_embed_schema: str, tmp_path: Path
) -> None:
    initialize_database(disposable_embed_schema)
    initial_migration = files("bird_recognition.embed").joinpath(
        "migrations", "001_initial.sql"
    )
    (tmp_path / "001_initial.sql").write_text(
        initial_migration.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "002_test_marker.sql").write_text(
        "CREATE TABLE bird_embed.migration_002_test_marker (id integer PRIMARY KEY);",
        encoding="utf-8",
    )

    with psycopg.connect(disposable_embed_schema, autocommit=True) as connection:
        first = apply_pending_migrations(connection, tmp_path)
        second = apply_pending_migrations(connection, tmp_path)

    assert first.version == 2
    assert first.applied_versions == (2,)
    assert second.version == 2
    assert second.applied_versions == ()


@pytest.mark.real_database
def test_storage_preflight_rejects_missing_schema(disposable_embed_schema: str) -> None:
    with pytest.raises(StorageError, match="schema_mismatch"):
        PgVectorStore(disposable_embed_schema).preflight()


@pytest.mark.real_database
def test_storage_preflight_rejects_insufficient_table_permissions(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    role_name = f"bird_embed_test_{uuid4().hex}"
    password = secrets.token_urlsafe(32)
    with psycopg.connect(disposable_embed_schema, autocommit=True) as connection:
        _drop_temporary_test_roles(connection)
        can_create_role = connection.execute(
            "SELECT rolsuper OR rolcreaterole FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        if not can_create_role:
            pytest.skip("database account cannot create a disposable restricted role")
        connection.execute(
            SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                Identifier(role_name), Literal(password)
            )
        )
        try:
            connection.execute(
                SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    Identifier(connection.info.dbname), Identifier(role_name)
                )
            )
            connection.execute(
                SQL("GRANT USAGE ON SCHEMA bird_embed TO {}").format(
                    Identifier(role_name)
                )
            )
            connection.execute(
                SQL("GRANT SELECT ON ALL TABLES IN SCHEMA bird_embed TO {}").format(
                    Identifier(role_name)
                )
            )
            connection.execute(
                SQL("REVOKE SELECT ON bird_embed.crop_snapshot FROM {}").format(
                    Identifier(role_name)
                )
            )
            parsed_url = urlsplit(disposable_embed_schema)
            host = parsed_url.hostname
            authority_host = f"[{host}]" if host and ":" in host else host
            port = f":{parsed_url.port}" if parsed_url.port else ""
            restricted_url = urlunsplit(
                (
                    parsed_url.scheme,
                    f"{quote(role_name, safe='')}:{quote(password, safe='')}@"
                    f"{authority_host}{port}",
                    parsed_url.path,
                    parsed_url.query,
                    parsed_url.fragment,
                )
            )
            with pytest.raises(StorageError, match="permissions"):
                PgVectorStore(restricted_url).preflight(read_only=True)
        finally:
            connection.execute(SQL("DROP OWNED BY {}").format(Identifier(role_name)))
            connection.execute(
                SQL("REVOKE CONNECT ON DATABASE {} FROM {}").format(
                    Identifier(connection.info.dbname), Identifier(role_name)
                )
            )
            connection.execute(SQL("DROP OWNED BY {}").format(Identifier(role_name)))
            connection.execute(
                SQL("DROP ROLE IF EXISTS {}").format(Identifier(role_name))
            )


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
def test_storage_preflight_rejects_incompatible_vector_dimension(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    with psycopg.connect(disposable_embed_schema) as connection:
        connection.execute(
            "ALTER TABLE bird_embed.crop_representation "
            "ALTER COLUMN embedding TYPE vector(511) USING embedding::vector(511)"
        )

    with pytest.raises(StorageError, match="dimension"):
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
@pytest.mark.parametrize(
    ("values", "expected_error"),
    [
        ((0.0,) * 512, True),
        ((2.0,) + (0.0,) * 511, True),
        ((float("nan"),) + (0.0,) * 511, True),
        ((float("inf"),) + (0.0,) * 511, True),
        ((1.0,) + (0.0,) * 510, True),
        ((1.0,) + (0.0,) * 511, False),
    ],
)
def test_representation_rejects_invalid_embedding_values(
    disposable_embed_schema: str,
    values: tuple[float, ...],
    expected_error: bool,
) -> None:
    initialize_database(disposable_embed_schema)
    with psycopg.connect(disposable_embed_schema) as connection:
        register_vector(connection)
        snapshot_id, model_fingerprint, _, run_id = (
            _insert_representation_prerequisites(connection)
        )
        statement = (
            "INSERT INTO bird_embed.crop_representation "
            "(representation_id,snapshot_id,model_fingerprint,embedding,processed_at,"
            "created_run_id) VALUES (%s,%s,%s,%s,%s,%s)"
        )
        parameters = (
            uuid4(),
            snapshot_id,
            model_fingerprint,
            Vector(list(values)),
            datetime.now(UTC),
            run_id,
        )
        if expected_error:
            with pytest.raises(psycopg.Error):
                with connection.transaction():
                    connection.execute(statement, parameters)
        else:
            connection.execute(statement, parameters)


@pytest.mark.real_database
def test_representation_uniqueness_is_enforced_by_database(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    now = datetime.now(UTC)
    with psycopg.connect(disposable_embed_schema) as connection:
        register_vector(connection)
        snapshot_id, model_fingerprint, _, run_id = (
            _insert_representation_prerequisites(connection)
        )
        statement = (
            "INSERT INTO bird_embed.crop_representation "
            "(representation_id,snapshot_id,model_fingerprint,embedding,processed_at,"
            "created_run_id) VALUES (%s,%s,%s,%s,%s,%s)"
        )
        vector = Vector([1.0] + [0.0] * 511)
        connection.execute(
            statement, (uuid4(), snapshot_id, model_fingerprint, vector, now, run_id)
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    statement,
                    (uuid4(), snapshot_id, model_fingerprint, vector, now, run_id),
                )


@pytest.mark.real_database
def test_decision_uniqueness_is_enforced_by_database(
    disposable_embed_schema: str,
) -> None:
    initialize_database(disposable_embed_schema)
    now = datetime.now(UTC)
    with psycopg.connect(disposable_embed_schema) as connection:
        register_vector(connection)
        snapshot_id, model_fingerprint, config_fingerprint, run_id = (
            _insert_representation_prerequisites(connection)
        )
        representation_id = uuid4()
        connection.execute(
            "INSERT INTO bird_embed.crop_representation "
            "(representation_id,snapshot_id,model_fingerprint,embedding,processed_at,"
            "created_run_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (
                representation_id,
                snapshot_id,
                model_fingerprint,
                Vector([1.0] + [0.0] * 511),
                now,
                run_id,
            ),
        )
        statement = (
            "INSERT INTO bird_embed.species_decision "
            "(decision_id,representation_id,config_fingerprint,assigned_species_id,"
            "best_candidate_id,confidence,tied_candidate_ids,candidate_scores_json,"
            "reason,warnings_json,processed_at,created_run_id) "
            "VALUES (%s,%s,%s,'bird','bird',1,'[]',"
            '\'[{"id":"bird","logit":1,"score":1}]\','
            "'assigned','[]',%s,%s)"
        )
        connection.execute(
            statement, (uuid4(), representation_id, config_fingerprint, now, run_id)
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                connection.execute(
                    statement,
                    (uuid4(), representation_id, config_fingerprint, now, run_id),
                )


@pytest.mark.real_database
@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        (
            "candidate_set",
            "candidate_set_fingerprint,schema_version,candidates_json,canonical_json",
            ("a" * 64, 1, Jsonb([]), Jsonb({})),
        ),
        (
            "tagging_config",
            "config_fingerprint,model_fingerprint,candidate_set_fingerprint,"
            "scoring_fingerprint,prompt_template,prompt_version,effective_logit_scale,"
            "scoring_json,threshold,canonical_json",
            (
                "b" * 64,
                "a" * 64,
                "b" * 64,
                "f" * 64,
                "a photo of {name}.",
                "species-photo-v1",
                1.0,
                Jsonb({}),
                1.5,
                Jsonb({}),
            ),
        ),
    ],
)
def test_candidate_and_configuration_constraints_reject_invalid_records(
    disposable_embed_schema: str,
    table: str,
    columns: str,
    values: tuple[Any, ...],
) -> None:
    initialize_database(disposable_embed_schema)
    placeholders = ",".join("%s" for _ in values)
    with psycopg.connect(disposable_embed_schema) as connection:
        if table == "tagging_config":
            _insert_representation_prerequisites(connection)
            values = (
                "e" * 64,
                "a" * 64,
                "b" * 64,
                "f" * 64,
                "a photo of {name}.",
                "species-photo-v1",
                1.0,
                Jsonb({}),
                1.5,
                Jsonb({}),
            )
        with pytest.raises(psycopg.Error):
            with connection.transaction():
                connection.execute(
                    f"INSERT INTO bird_embed.{table} ({columns}) "
                    f"VALUES ({placeholders})",
                    values,
                )


@pytest.mark.real_database
@pytest.mark.parametrize(
    ("architecture", "dimension", "logit_scale"),
    [
        ("other", 512, 1.0),
        ("ViT-B-16", 511, 1.0),
        ("ViT-B-16", 512, 0.0),
        ("ViT-B-16", 512, float("inf")),
        ("ViT-B-16", 512, float("nan")),
    ],
)
def test_model_constraints_reject_incompatible_identity(
    disposable_embed_schema: str,
    architecture: str,
    dimension: int,
    logit_scale: float,
) -> None:
    initialize_database(disposable_embed_schema)
    with psycopg.connect(disposable_embed_schema) as connection:
        with pytest.raises(psycopg.Error):
            with connection.transaction():
                connection.execute(
                    "INSERT INTO bird_embed.embedding_model "
                    "(model_fingerprint,upstream_name,upstream_revision,"
                    "checkpoint_sha256,config_sha256,tokenizer_sha256,architecture,"
                    "dimension,preprocessing_json,tokenizer_json,adapter_version,"
                    "runtime_json,logit_scale,canonical_json) "
                    "VALUES (%s,'test','revision',%s,%s,%s,%s,%s,'{}','{}','test',"
                    "'{}',%s,'{}')",
                    (
                        "a" * 64,
                        "1" * 64,
                        "2" * 64,
                        "3" * 64,
                        architecture,
                        dimension,
                        logit_scale,
                    ),
                )


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
@pytest.mark.parametrize(
    ("after_commit", "failure_statement"),
    [
        (False, None),
        (True, None),
        (False, "INSERT INTO bird_embed.crop_snapshot"),
        (False, "INSERT INTO bird_embed.crop_representation"),
        (False, "INSERT INTO bird_embed.species_decision"),
        (False, "UPDATE bird_embed.run_item"),
        (False, "UPDATE bird_embed.processing_run"),
    ],
)
def test_storage_atomically_persists_and_inspects_crop_across_connections(
    disposable_embed_schema: str,
    tmp_path: Path,
    after_commit: bool,
    failure_statement: str | None,
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
        with pytest.raises(EmbedValidationError):
            writer.commit_crop_result(
                snapshot,
                representation,
                replace(
                    decision,
                    assigned_species_id="outside-candidates",
                    best_candidate_id="outside-candidates",
                ),
                complete_item,
            )
        with pytest.raises(StorageError, match="does not match its run"):
            writer.commit_crop_result(
                snapshot,
                replace(representation, model_fingerprint="9" * 64),
                decision,
                complete_item,
            )
        if failure_statement is None:
            writer._writer_connection = _ConnectionWithLostCommitAcknowledgement(
                writer._writer_connection, after_commit=after_commit
            )
        else:
            writer._writer_connection = _ConnectionWithFailureAfterStatement(
                writer._writer_connection, failure_statement
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
        committed_durably = after_commit and failure_statement is None
        if committed_durably:
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
    assert recovered_summary["counts"]["completed"] == int(committed_durably)
    assert run_summary["counts"]["skipped"] == int(committed_durably)
    assert run_summary["counts"]["completed"] == int(not committed_durably)
    assert items[0]["status"] == ("skipped" if committed_durably else "completed")
    assert items[0]["provenance"]["lighting"] == "unknown"
    assert items[0]["provenance"]["capture_time"] is None
