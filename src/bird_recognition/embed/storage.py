"""PostgreSQL persistence for versioned crop representations and decisions."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from bird_recognition.embed.config import (
    sanitize_error,
    validate_local_database_url,
)
from bird_recognition.embed.migrate import (
    apply_pending_migrations,
    latest_migration_version,
)
from bird_recognition.embed.models import (
    CandidateScore,
    CropRepresentation,
    EmbeddingModelRecord,
    EmbedValidationError,
    IngestedCropSnapshot,
    ProcessingRun,
    RunFailure,
    RunItem,
    RunItemStatus,
    RunStatus,
    Sha256,
    SpeciesCandidate,
    SpeciesCandidateSet,
    SpeciesDecision,
    StorageError,
    TaggingConfig,
    UnconfirmedCommitError,
)
from bird_recognition.embed.scoring import validate_decision

_ADVISORY_LOCK_KEY = 0x4252495244454D42


@dataclass(frozen=True, slots=True)
class DatabaseInitResult:
    """Explicit database initialization outcome."""

    schema_version: int
    vector_available: bool
    changes_applied: bool


class PgVectorStore:
    """Direct-SQL store using a session lock and per-crop transactions."""

    def __init__(self, database_url: str) -> None:
        validate_local_database_url(database_url)
        self._database_url = database_url
        self._writer_connection: psycopg.Connection[Any] | None = None

    def preflight(self, *, read_only: bool = False) -> None:
        """Check schema, pgvector type, dimension, and required permissions."""
        try:
            with psycopg.connect(self._database_url) as connection:
                self._preflight_connection(connection, read_only=read_only)
        except StorageError:
            raise
        except Exception as error:
            raise StorageError(_safe_database_error(error)) from None

    def acquire_writer_lock(self) -> None:
        """Acquire the nonblocking database-wide session advisory lock."""
        if self._writer_connection is not None:
            raise StorageError("writer lock is already held")
        try:
            connection = psycopg.connect(self._database_url, autocommit=True)
            register_vector(connection)
            acquired = connection.execute(
                "SELECT pg_try_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,)
            ).fetchone()[0]
            if not acquired:
                connection.close()
                raise StorageError("writer_busy: another index writer is active")
            self._writer_connection = connection
        except StorageError:
            raise
        except Exception as error:
            raise StorageError(_safe_database_error(error)) from None

    def release_writer_lock(self) -> None:
        """Release the held session lock and close its connection."""
        connection = self._writer_connection
        self._writer_connection = None
        if connection is None:
            return
        try:
            connection.execute("SELECT pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
        except Exception as error:
            raise StorageError(_safe_database_error(error)) from None
        finally:
            connection.close()

    def recover_stale_runs(self) -> None:
        """Mark earlier running batches interrupted without changing their items."""
        connection = self._require_writer()
        try:
            with connection.transaction():
                connection.execute(
                    "UPDATE bird_embed.processing_run "
                    "SET status='interrupted',completed_at=now() "
                    "WHERE status='running'"
                )
        except Exception as error:
            raise _storage_error(error) from None

    def register_run(
        self,
        run: ProcessingRun,
        items: tuple[RunItem, ...],
        model: EmbeddingModelRecord,
        candidates: SpeciesCandidateSet,
        config: TaggingConfig,
    ) -> None:
        """Persist immutable configuration and pending run items after preflight."""
        if (
            len(items) != run.selected_count
            or any(
                item.run_id != run.run_id or item.status is not RunItemStatus.PENDING
                for item in items
            )
            or run.status is not RunStatus.RUNNING
        ):
            raise EmbedValidationError(
                "run registration requires all selected pending items"
            )
        if (
            run.config_fingerprint != config.config_fingerprint
            or config.model_fingerprint != model.model_fingerprint
            or config.candidate_set_fingerprint != candidates.candidate_set_fingerprint
        ):
            raise EmbedValidationError("run metadata does not match its configuration")
        connection = self._require_writer()
        try:
            with connection.transaction():
                self._insert_model(connection, model)
                self._insert_candidates(connection, candidates)
                self._insert_config(connection, config)
                connection.execute(
                    "INSERT INTO bird_embed.processing_run "
                    "(run_id,started_at,completed_at,status,config_fingerprint,"
                    "manifest_locator,crop_root,selection_fingerprint,selected_count,"
                    "completed_count,skipped_count,failed_count,assigned_count,"
                    "unknown_count,failures_json,sanitized_settings_json) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        run.run_id,
                        run.started_at,
                        run.completed_at,
                        run.status.value,
                        run.config_fingerprint,
                        str(run.manifest_locator),
                        str(run.crop_root) if run.crop_root else None,
                        run.selection_fingerprint,
                        run.selected_count,
                        run.completed_count,
                        run.skipped_count,
                        run.failed_count,
                        run.assigned_count,
                        run.unknown_count,
                        Jsonb([_failure_json(failure) for failure in run.failures]),
                        Jsonb(json.loads(run.sanitized_settings_json)),
                    ),
                )
                for item in items:
                    self._insert_run_item(connection, item)
        except Exception as error:
            raise _storage_error(error) from None

    def get_completed_decision(
        self,
        snapshot_id: Sha256,
        model_fingerprint: Sha256,
        config_fingerprint: Sha256,
    ) -> SpeciesDecision | None:
        """Return a fully persisted exact decision, if it exists."""
        try:
            with psycopg.connect(
                self._database_url, row_factory=dict_row
            ) as connection:
                row = connection.execute(
                    "SELECT d.* FROM bird_embed.species_decision AS d "
                    "JOIN bird_embed.crop_representation AS r "
                    "ON r.representation_id=d.representation_id "
                    "WHERE r.snapshot_id=%s AND r.model_fingerprint=%s "
                    "AND d.config_fingerprint=%s",
                    (snapshot_id, model_fingerprint, config_fingerprint),
                ).fetchone()
                return _decision_from_row(row) if row else None
        except Exception as error:
            raise _storage_error(error) from None

    def get_compatible_representation(
        self, snapshot_id: Sha256, model_fingerprint: Sha256
    ) -> CropRepresentation | None:
        """Load one complete persisted image vector for the exact model identity."""
        try:
            with psycopg.connect(self._database_url) as connection:
                register_vector(connection)
                row = connection.execute(
                    "SELECT representation_id,snapshot_id,model_fingerprint,embedding,"
                    "processed_at,created_run_id FROM bird_embed.crop_representation "
                    "WHERE snapshot_id=%s AND model_fingerprint=%s",
                    (snapshot_id, model_fingerprint),
                ).fetchone()
                if row is None:
                    return None
                embedding = tuple(float(value) for value in row[3].to_list())
                _validate_embedding(embedding)
                return CropRepresentation(
                    representation_id=row[0],
                    snapshot_id=row[1].strip(),
                    model_fingerprint=row[2].strip(),
                    embedding=embedding,
                    processed_at=row[4],
                    created_run_id=row[5],
                )
        except Exception as error:
            raise _storage_error(error) from None

    def get_compatible_score_map(
        self, representation_id: UUID, scoring_fingerprint: Sha256
    ) -> tuple[CandidateScore, ...] | None:
        """Load a saved candidate score map for the exact scoring contract."""
        try:
            with psycopg.connect(
                self._database_url, row_factory=dict_row
            ) as connection:
                row = connection.execute(
                    "SELECT d.candidate_scores_json "
                    "FROM bird_embed.species_decision AS d "
                    "JOIN bird_embed.tagging_config AS t USING(config_fingerprint) "
                    "WHERE d.representation_id=%s AND t.scoring_fingerprint=%s "
                    "ORDER BY d.processed_at DESC,d.decision_id DESC LIMIT 1",
                    (representation_id, scoring_fingerprint),
                ).fetchone()
                if row is None:
                    return None
                values = row["candidate_scores_json"]
                return tuple(
                    CandidateScore(value["id"], value["logit"], value["score"])
                    for value in values
                )
        except Exception as error:
            raise _storage_error(error) from None

    def commit_crop_result(
        self,
        snapshot: IngestedCropSnapshot,
        representation: CropRepresentation,
        decision: SpeciesDecision,
        item: RunItem,
    ) -> bool:
        """Atomically insert provenance, representation, decision, and item."""
        connection = self._require_writer()
        if (
            item.status is not RunItemStatus.COMPLETED
            or item.decision_id != decision.decision_id
            or item.crop_id != snapshot.crop_id
            or item.expected_snapshot_id != snapshot.snapshot_id
            or item.expected_provenance_sha256 != snapshot.provenance_sha256
            or item.lighting is not snapshot.lighting
            or decision.created_run_id != item.run_id
        ):
            raise EmbedValidationError(
                "crop result item must reference its completed decision"
            )
        try:
            with connection.transaction():
                context = connection.execute(
                    "SELECT c.candidates_json,t.threshold "
                    "FROM bird_embed.processing_run AS r "
                    "JOIN bird_embed.tagging_config AS t USING (config_fingerprint) "
                    "JOIN bird_embed.candidate_set AS c "
                    "USING (candidate_set_fingerprint) "
                    "WHERE r.run_id=%s AND r.config_fingerprint=%s "
                    "AND t.model_fingerprint=%s",
                    (
                        item.run_id,
                        decision.config_fingerprint,
                        representation.model_fingerprint,
                    ),
                ).fetchone()
                if context is None:
                    raise StorageError(
                        "crop result configuration does not match its run"
                    )
                candidates_json, threshold = context
                candidate_values = (
                    candidates_json
                    if isinstance(candidates_json, list)
                    else json.loads(candidates_json)
                )
                candidates = tuple(
                    SpeciesCandidate(
                        id=value["id"],
                        name=value.get("name"),
                        kind=value.get("kind", "species"),
                        common_name=value.get("common_name"),
                        taxonomic_description=value.get("taxonomic_description"),
                        category=value.get("category"),
                    )
                    for value in candidate_values
                )
                validate_decision(decision, candidates, threshold=threshold)
                if representation.snapshot_id != snapshot.snapshot_id:
                    raise EmbedValidationError(
                        "representation snapshot does not match crop"
                    )
                self._insert_snapshot(connection, snapshot)
                representation_id = self._insert_representation(
                    connection, representation
                )
                if representation_id != representation.representation_id:
                    representation = replace(
                        representation, representation_id=representation_id
                    )
                    decision = replace(decision, representation_id=representation_id)
                inserted = self._insert_decision(connection, decision)
                if not inserted:
                    existing = connection.execute(
                        "SELECT decision_id FROM bird_embed.species_decision "
                        "WHERE representation_id=%s AND config_fingerprint=%s",
                        (representation.representation_id, decision.config_fingerprint),
                    ).fetchone()
                    if existing is None:
                        raise StorageError(
                            "conflicting decision could not be reconciled"
                        )
                    self._skip_item_in_transaction(connection, item, existing[0])
                    updated_run = connection.execute(
                        "UPDATE bird_embed.processing_run "
                        "SET skipped_count=skipped_count+1 "
                        "WHERE run_id=%s AND status='running'",
                        (item.run_id,),
                    )
                    if updated_run.rowcount != 1:
                        raise StorageError("conflicting result run is not running")
                    return False
                self._complete_item(connection, item)
                updated_run = connection.execute(
                    "UPDATE bird_embed.processing_run "
                    "SET completed_count=completed_count+1,"
                    "assigned_count=assigned_count+%s,unknown_count=unknown_count+%s "
                    "WHERE run_id=%s AND status='running'",
                    (
                        int(decision.assigned_species_id is not None),
                        int(decision.assigned_species_id is None),
                        item.run_id,
                    ),
                )
                if updated_run.rowcount != 1:
                    raise StorageError("crop result run is no longer running")
                return True
        except UnconfirmedCommitError:
            raise
        except EmbedValidationError:
            raise
        except Exception as error:
            if _is_connection_error(error):
                raise UnconfirmedCommitError(
                    "crop commit status is unconfirmed"
                ) from None
            raise _storage_error(error) from None

    def mark_item_skipped(self, item: RunItem) -> None:
        """Record a skipped item linked to its existing durable decision."""
        if item.status is not RunItemStatus.SKIPPED or item.decision_id is None:
            raise EmbedValidationError("skipped item must reference a saved decision")
        connection = self._require_writer()
        try:
            with connection.transaction():
                compatible = connection.execute(
                    "SELECT 1 FROM bird_embed.processing_run AS r "
                    "JOIN bird_embed.species_decision AS d "
                    "ON d.decision_id=%s AND d.config_fingerprint=r.config_fingerprint "
                    "JOIN bird_embed.crop_representation AS p "
                    "ON p.representation_id=d.representation_id "
                    "WHERE r.run_id=%s AND p.snapshot_id=%s",
                    (item.decision_id, item.run_id, item.expected_snapshot_id),
                ).fetchone()
                if compatible is None:
                    raise StorageError(
                        "skipped decision is incompatible with the run snapshot"
                    )
                updated = connection.execute(
                    "UPDATE bird_embed.run_item SET status='skipped', decision_id=%s, "
                    "completed_at=%s WHERE run_id=%s AND crop_id=%s "
                    "AND status='pending' AND expected_snapshot_id=%s "
                    "AND expected_provenance_sha256=%s AND lighting=%s",
                    (
                        item.decision_id,
                        item.completed_at,
                        item.run_id,
                        item.crop_id,
                        item.expected_snapshot_id,
                        item.expected_provenance_sha256,
                        item.lighting.value,
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageError("skipped item is not pending")
                counter = connection.execute(
                    "UPDATE bird_embed.processing_run "
                    "SET skipped_count=skipped_count+1 "
                    "WHERE run_id=%s AND status='running'",
                    (item.run_id,),
                )
                if counter.rowcount != 1:
                    raise StorageError("skipped item run does not exist")
        except Exception as error:
            raise _storage_error(error) from None

    def mark_item_failed(self, item: RunItem) -> None:
        """Persist one isolated failure and increment the run's failure count."""
        if item.status is not RunItemStatus.FAILED:
            raise EmbedValidationError("failed item transition requires a failed item")
        connection = self._require_writer()
        try:
            with connection.transaction():
                updated = connection.execute(
                    "UPDATE bird_embed.run_item SET status='failed',failure_code=%s,"
                    "failure_reason=%s,completed_at=%s WHERE run_id=%s AND crop_id=%s "
                    "AND status='pending' "
                    "AND expected_snapshot_id IS NOT DISTINCT FROM %s "
                    "AND expected_provenance_sha256=%s AND lighting=%s",
                    (
                        item.failure_code,
                        item.failure_reason,
                        item.completed_at,
                        item.run_id,
                        item.crop_id,
                        item.expected_snapshot_id,
                        item.expected_provenance_sha256,
                        item.lighting.value,
                    ),
                )
                if updated.rowcount != 1:
                    raise StorageError("failed item is not pending")
                counter = connection.execute(
                    "UPDATE bird_embed.processing_run SET failed_count=failed_count+1,"
                    "failures_json=failures_json || %s::jsonb "
                    "WHERE run_id=%s AND status='running'",
                    (
                        Jsonb(
                            [
                                {
                                    "crop_id": item.crop_id,
                                    "code": item.failure_code,
                                    "reason": item.failure_reason,
                                }
                            ]
                        ),
                        item.run_id,
                    ),
                )
                if counter.rowcount != 1:
                    raise StorageError("failed item run does not exist")
        except Exception as error:
            raise _storage_error(error) from None

    def finalize_run(self, run: ProcessingRun) -> None:
        """Persist a confirmed final run status and aggregate counters."""
        if run.status in {RunStatus.RUNNING, RunStatus.INTERRUPTED}:
            raise EmbedValidationError("only a final run outcome can be persisted")
        connection = self._require_writer()
        try:
            with connection.transaction():
                counts = connection.execute(
                    "SELECT count(*) AS selected, "
                    "count(*) FILTER (WHERE i.status='completed') AS completed, "
                    "count(*) FILTER (WHERE i.status='skipped') AS skipped, "
                    "count(*) FILTER (WHERE i.status='failed') AS failed, "
                    "count(*) FILTER (WHERE i.status='completed' "
                    "AND d.assigned_species_id IS NOT NULL) AS assigned, "
                    "count(*) FILTER (WHERE i.status='completed' "
                    "AND d.assigned_species_id IS NULL) AS unknown "
                    "FROM bird_embed.run_item AS i "
                    "LEFT JOIN bird_embed.species_decision AS d "
                    "ON d.decision_id=i.decision_id WHERE i.run_id=%s",
                    (run.run_id,),
                ).fetchone()
                expected_counts = (
                    run.selected_count,
                    run.completed_count,
                    run.skipped_count,
                    run.failed_count,
                    run.assigned_count,
                    run.unknown_count,
                )
                persisted_counts = tuple(counts)
                if persisted_counts != expected_counts:
                    raise StorageError("run counters do not match durable item states")
                pending_count = run.selected_count - sum(persisted_counts[1:4])
                if pending_count and run.status is not RunStatus.FAILED:
                    raise StorageError(
                        "only fatal failed runs may retain pending items"
                    )
                result = connection.execute(
                    "UPDATE bird_embed.processing_run SET completed_at=%s,status=%s,"
                    "selected_count=%s,completed_count=%s,skipped_count=%s,"
                    "failed_count=%s,assigned_count=%s,unknown_count=%s,"
                    "failures_json=%s "
                    "WHERE run_id=%s AND status='running'",
                    (
                        run.completed_at,
                        run.status.value,
                        run.selected_count,
                        run.completed_count,
                        run.skipped_count,
                        run.failed_count,
                        run.assigned_count,
                        run.unknown_count,
                        Jsonb([_failure_json(failure) for failure in run.failures]),
                        run.run_id,
                    ),
                )
                if result.rowcount != 1:
                    raise StorageError("run is missing or no longer running")
        except Exception as error:
            raise _storage_error(error) from None

    def list_runs(self) -> list[dict[str, object]]:
        """Return persisted run summaries newest first without model or crop access."""
        try:
            with psycopg.connect(
                self._database_url, row_factory=dict_row
            ) as connection:
                rows = connection.execute(
                    "SELECT run_id,status,started_at,completed_at,selected_count,"
                    "completed_count,skipped_count,failed_count,assigned_count,"
                    "unknown_count,config_fingerprint FROM bird_embed.processing_run "
                    "ORDER BY started_at DESC,run_id DESC"
                ).fetchall()
                return [_run_summary(row) for row in rows]
        except Exception as error:
            raise _storage_error(error) from None

    def inspect_run(
        self, run_id: UUID, crop_id: str | None = None
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Fetch saved run items, provenance, and decisions without source assets."""
        try:
            with psycopg.connect(
                self._database_url, row_factory=dict_row
            ) as connection:
                run_row = connection.execute(
                    "SELECT r.*,t.model_fingerprint,t.candidate_set_fingerprint,"
                    "t.scoring_fingerprint,t.threshold,t.canonical_json AS config_json,"
                    "m.canonical_json AS model_json,"
                    "c.canonical_json AS candidates_json "
                    "FROM bird_embed.processing_run AS r "
                    "JOIN bird_embed.tagging_config AS t USING(config_fingerprint) "
                    "JOIN bird_embed.embedding_model AS m USING(model_fingerprint) "
                    "JOIN bird_embed.candidate_set AS c "
                    "USING(candidate_set_fingerprint) "
                    "WHERE r.run_id=%s",
                    (run_id,),
                ).fetchone()
                if run_row is None:
                    raise EmbedValidationError("run selection was not found")
                sql = (
                    "SELECT i.*,d.decision_id AS saved_decision_id,"
                    "d.assigned_species_id,d.best_candidate_id,d.confidence,d.reason,"
                    "d.tied_candidate_ids,d.candidate_scores_json,d.warnings_json,"
                    "d.processed_at AS decision_processed_at,"
                    "s.snapshot_id,s.provenance_sha256,s.crop_sha256,s.source_id,"
                    "s.source_content_sha256,s.source_original_path,s.source_basename,"
                    "s.ingest_settings_fingerprint,s.ingestion_run_id,s.frame_number,"
                    "s.elapsed_seconds,s.detection_id,s.detection_category,"
                    "s.detection_confidence,s.detection_box_normalized,s.crop_box_pixels,"
                    "s.frame_width,s.frame_height,s.crop_original_image_path,"
                    "s.capture_time,s.capture_timezone,s.source_capture_start,"
                    "s.source_capture_timezone,s.lighting AS snapshot_lighting "
                    "FROM bird_embed.run_item AS i "
                    "LEFT JOIN bird_embed.species_decision AS d "
                    "ON d.decision_id=i.decision_id "
                    "LEFT JOIN bird_embed.crop_representation AS p "
                    "ON p.representation_id=d.representation_id "
                    "LEFT JOIN bird_embed.crop_snapshot AS s "
                    "ON s.snapshot_id=p.snapshot_id "
                    "WHERE i.run_id=%s"
                )
                parameters: tuple[Any, ...] = (run_id,)
                if crop_id is not None:
                    sql += " AND i.crop_id=%s"
                    parameters += (crop_id,)
                sql += " ORDER BY i.crop_id"
                rows = connection.execute(sql, parameters).fetchall()
                if crop_id is not None and not rows:
                    raise EmbedValidationError(
                        "crop selection was not found in the run"
                    )
                return _run_inspection(run_row), [_item_inspection(row) for row in rows]
        except EmbedValidationError:
            raise
        except Exception as error:
            raise _storage_error(error) from None

    def close(self) -> None:
        """Release any writer session held by this store."""
        self.release_writer_lock()

    def get_run_configuration(self, run_id: UUID) -> dict[str, object]:
        """Return persisted model, candidate, scoring, and threshold identities."""
        try:
            with psycopg.connect(
                self._database_url, row_factory=dict_row
            ) as connection:
                row = connection.execute(
                    "SELECT t.model_fingerprint,t.candidate_set_fingerprint,"
                    "t.scoring_fingerprint,t.threshold,"
                    "jsonb_array_length(c.candidates_json) AS candidate_count "
                    "FROM bird_embed.processing_run AS r "
                    "JOIN bird_embed.tagging_config AS t USING(config_fingerprint) "
                    "JOIN bird_embed.candidate_set AS c "
                    "USING(candidate_set_fingerprint) "
                    "WHERE r.run_id=%s",
                    (run_id,),
                ).fetchone()
                if row is None:
                    raise EmbedValidationError("run selection was not found")
                return {
                    key: row[key].strip() if key.endswith("fingerprint") else row[key]
                    for key in row
                }
        except EmbedValidationError:
            raise
        except Exception as error:
            raise _storage_error(error) from None

    def _require_writer(self) -> psycopg.Connection[Any]:
        if self._writer_connection is None or self._writer_connection.closed:
            raise StorageError("writer lock is not held")
        return self._writer_connection

    @staticmethod
    def _preflight_connection(
        connection: psycopg.Connection[Any], *, read_only: bool = False
    ) -> None:
        schema = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='bird_embed')"
        ).fetchone()[0]
        if not schema:
            raise StorageError("schema_mismatch: bird_embed schema is not initialized")
        try:
            version = connection.execute(
                "SELECT version FROM bird_embed.schema_version WHERE singleton"
            ).fetchone()
        except psycopg.Error:
            raise StorageError(
                "schema_mismatch: schema version record is unavailable"
            ) from None
        if version is None or version[0] != latest_migration_version():
            raise StorageError("schema_mismatch: unsupported database schema version")
        extension = connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
        ).fetchone()[0]
        if not extension:
            raise StorageError("vector_unavailable: pgvector extension is missing")
        column_type = connection.execute(
            "SELECT format_type(a.atttypid,a.atttypmod) "
            "FROM pg_attribute AS a JOIN pg_class AS t ON t.oid=a.attrelid "
            "JOIN pg_namespace AS n ON n.oid=t.relnamespace "
            "WHERE n.nspname='bird_embed' AND t.relname='crop_representation' "
            "AND a.attname='embedding' AND NOT a.attisdropped"
        ).fetchone()
        if column_type is None or column_type[0] != "vector(512)":
            raise StorageError(
                "schema_mismatch: representation dimension is not vector(512)"
            )
        if not connection.execute(
            "SELECT has_schema_privilege(current_user,'bird_embed','USAGE')"
        ).fetchone()[0]:
            raise StorageError("database permissions are insufficient")
        required_privileges = (
            ("SELECT", "bird_embed.processing_run"),
            ("SELECT", "bird_embed.run_item"),
            ("SELECT", "bird_embed.species_decision"),
            ("SELECT", "bird_embed.crop_representation"),
            ("SELECT", "bird_embed.crop_snapshot"),
            ("SELECT", "bird_embed.tagging_config"),
            ("SELECT", "bird_embed.embedding_model"),
            ("SELECT", "bird_embed.candidate_set"),
        )
        if not read_only:
            required_privileges += tuple(
                ("INSERT", table)
                for table in (
                    "bird_embed.processing_run",
                    "bird_embed.run_item",
                    "bird_embed.species_decision",
                    "bird_embed.crop_representation",
                    "bird_embed.crop_snapshot",
                    "bird_embed.tagging_config",
                    "bird_embed.embedding_model",
                    "bird_embed.candidate_set",
                )
            ) + (
                ("UPDATE", "bird_embed.processing_run"),
                ("UPDATE", "bird_embed.run_item"),
            )
        for privilege, relation in required_privileges:
            if not connection.execute(
                "SELECT has_table_privilege(current_user,%s,%s)",
                (relation, privilege),
            ).fetchone()[0]:
                raise StorageError("database permissions are insufficient")

    @staticmethod
    def _insert_model(
        connection: psycopg.Connection[Any], model: EmbeddingModelRecord
    ) -> None:
        connection.execute(
            "INSERT INTO bird_embed.embedding_model VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) "
            "ON CONFLICT(model_fingerprint) DO NOTHING",
            (
                model.model_fingerprint,
                model.upstream_name,
                model.upstream_revision,
                model.checkpoint_sha256,
                model.config_sha256,
                model.tokenizer_sha256,
                model.architecture,
                model.dimension,
                Jsonb(json.loads(model.preprocessing_json)),
                Jsonb(json.loads(model.tokenizer_json)),
                model.adapter_version,
                Jsonb(json.loads(model.runtime_json)),
                model.logit_scale,
                Jsonb(json.loads(model.canonical_json)),
            ),
        )

    @staticmethod
    def _insert_candidates(
        connection: psycopg.Connection[Any], candidates: SpeciesCandidateSet
    ) -> None:
        connection.execute(
            "INSERT INTO bird_embed.candidate_set VALUES (%s,%s,%s,%s,now()) "
            "ON CONFLICT(candidate_set_fingerprint) DO NOTHING",
            (
                candidates.candidate_set_fingerprint,
                candidates.schema_version,
                Jsonb(json.loads(candidates.candidates_json)),
                Jsonb(json.loads(candidates.canonical_json)),
            ),
        )

    @staticmethod
    def _insert_config(
        connection: psycopg.Connection[Any], config: TaggingConfig
    ) -> None:
        connection.execute(
            "INSERT INTO bird_embed.tagging_config VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) "
            "ON CONFLICT(config_fingerprint) DO NOTHING",
            (
                config.config_fingerprint,
                config.model_fingerprint,
                config.candidate_set_fingerprint,
                config.scoring_fingerprint,
                config.prompt_template,
                config.prompt_version,
                config.effective_logit_scale,
                Jsonb(json.loads(config.scoring_json)),
                config.threshold,
                Jsonb(json.loads(config.canonical_json)),
            ),
        )

    @staticmethod
    def _insert_snapshot(
        connection: psycopg.Connection[Any], snapshot: IngestedCropSnapshot
    ) -> None:
        connection.execute(
            "INSERT INTO bird_embed.crop_snapshot (snapshot_id,crop_id,"
            "provenance_sha256,crop_sha256,source_id,source_content_sha256,"
            "source_original_path,source_basename,ingest_settings_fingerprint,"
            "ingestion_run_id,frame_number,elapsed_seconds,detection_id,"
            "detection_category,detection_confidence,detection_box_normalized,"
            "crop_box_pixels,frame_width,frame_height,crop_original_image_path,"
            "capture_time,capture_timezone,source_capture_start,"
            "source_capture_timezone,lighting,imported_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(crop_id,provenance_sha256) DO NOTHING",
            (
                snapshot.snapshot_id,
                snapshot.crop_id,
                snapshot.provenance_sha256,
                snapshot.crop_sha256,
                snapshot.source_id,
                snapshot.source_content_sha256,
                snapshot.source_original_path,
                snapshot.source_basename,
                snapshot.ingest_settings_fingerprint,
                snapshot.ingestion_run_id,
                snapshot.frame_number,
                snapshot.elapsed_seconds,
                snapshot.detection_id,
                snapshot.detection_category,
                snapshot.detection_confidence,
                Jsonb(list(snapshot.detection_box_normalized)),
                Jsonb(list(snapshot.crop_box_pixels)),
                snapshot.frame_width,
                snapshot.frame_height,
                snapshot.crop_original_image_path,
                snapshot.capture_time,
                snapshot.capture_timezone,
                snapshot.source_capture_start,
                snapshot.source_capture_timezone,
                snapshot.lighting.value,
                snapshot.imported_at,
            ),
        )

    @staticmethod
    def _insert_representation(
        connection: psycopg.Connection[Any], representation: CropRepresentation
    ) -> UUID:
        _validate_embedding(representation.embedding)
        result = connection.execute(
            "INSERT INTO bird_embed.crop_representation VALUES (%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(snapshot_id,model_fingerprint) DO NOTHING "
            "RETURNING representation_id",
            (
                representation.representation_id,
                representation.snapshot_id,
                representation.model_fingerprint,
                Vector(list(representation.embedding)),
                representation.processed_at,
                representation.created_run_id,
            ),
        ).fetchone()
        if result is not None:
            return result[0]
        existing = connection.execute(
            "SELECT representation_id,embedding FROM bird_embed.crop_representation "
            "WHERE snapshot_id=%s AND model_fingerprint=%s",
            (representation.snapshot_id, representation.model_fingerprint),
        ).fetchone()
        if existing is None:
            raise StorageError("conflicting representation could not be reconciled")
        existing_embedding = tuple(float(value) for value in existing[1].to_list())
        _validate_embedding(existing_embedding)
        if any(
            abs(actual - expected) > 1e-5
            for actual, expected in zip(
                existing_embedding, representation.embedding, strict=True
            )
        ):
            raise StorageError(
                "conflicting representation has incompatible vector data"
            )
        return existing[0]

    @staticmethod
    def _insert_decision(
        connection: psycopg.Connection[Any], decision: SpeciesDecision
    ) -> bool:
        result = connection.execute(
            "INSERT INTO bird_embed.species_decision VALUES "
            "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(representation_id,config_fingerprint) DO NOTHING "
            "RETURNING decision_id",
            (
                decision.decision_id,
                decision.representation_id,
                decision.config_fingerprint,
                decision.assigned_species_id,
                decision.best_candidate_id,
                decision.confidence,
                Jsonb(list(decision.tied_candidate_ids)),
                Jsonb(
                    [
                        {"id": score.id, "logit": score.logit, "score": score.score}
                        for score in decision.candidate_scores
                    ]
                ),
                decision.reason,
                Jsonb(list(decision.warnings)),
                decision.processed_at,
                decision.created_run_id,
            ),
        )
        return result.fetchone() is not None

    @staticmethod
    def _insert_run_item(connection: psycopg.Connection[Any], item: RunItem) -> None:
        connection.execute(
            "INSERT INTO bird_embed.run_item "
            "(run_id,crop_id,expected_snapshot_id,expected_provenance_sha256,"
            "resolved_input_locator,status,decision_id,failure_code,failure_reason,"
            "started_at,completed_at,lighting) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                item.run_id,
                item.crop_id,
                item.expected_snapshot_id,
                item.expected_provenance_sha256,
                str(item.resolved_input_locator),
                item.status.value,
                item.decision_id,
                item.failure_code,
                item.failure_reason,
                item.started_at,
                item.completed_at,
                item.lighting.value,
            ),
        )

    @staticmethod
    def _complete_item(connection: psycopg.Connection[Any], item: RunItem) -> None:
        result = connection.execute(
            "UPDATE bird_embed.run_item SET status='completed',decision_id=%s,"
            "completed_at=%s WHERE run_id=%s AND crop_id=%s AND status='pending' "
            "AND expected_snapshot_id=%s AND expected_provenance_sha256=%s "
            "AND lighting=%s",
            (
                item.decision_id,
                item.completed_at,
                item.run_id,
                item.crop_id,
                item.expected_snapshot_id,
                item.expected_provenance_sha256,
                item.lighting.value,
            ),
        )
        if result.rowcount != 1:
            raise StorageError("crop result item is not pending")

    @staticmethod
    def _skip_item_in_transaction(
        connection: psycopg.Connection[Any], item: RunItem, decision_id: UUID
    ) -> None:
        result = connection.execute(
            "UPDATE bird_embed.run_item SET status='skipped',decision_id=%s,"
            "completed_at=%s WHERE run_id=%s AND crop_id=%s AND status='pending' "
            "AND expected_snapshot_id=%s AND expected_provenance_sha256=%s "
            "AND lighting=%s",
            (
                decision_id,
                item.completed_at,
                item.run_id,
                item.crop_id,
                item.expected_snapshot_id,
                item.expected_provenance_sha256,
                item.lighting.value,
            ),
        )
        if result.rowcount != 1:
            raise StorageError("conflicting result item is not pending")


def initialize_database(database_url: str) -> DatabaseInitResult:
    """Apply pending packaged migrations and verify the resulting schema."""
    validate_local_database_url(database_url)
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            result = apply_pending_migrations(connection)
            PgVectorStore._preflight_connection(connection)
            return DatabaseInitResult(
                result.version,
                True,
                bool(result.applied_versions),
            )
    except StorageError:
        raise
    except Exception as error:
        raise StorageError(_safe_database_error(error)) from None


def _validate_embedding(embedding: tuple[float, ...]) -> None:
    import math

    if len(embedding) != 512 or any(not math.isfinite(value) for value in embedding):
        raise EmbedValidationError("embedding must contain 512 finite values")
    norm = math.hypot(*embedding)
    if not math.isfinite(norm) or norm == 0 or abs(norm - 1.0) > 1e-5:
        raise EmbedValidationError("embedding must be nonzero and L2-normalized")


def _decision_from_row(row: Any) -> SpeciesDecision:
    return SpeciesDecision(
        decision_id=row["decision_id"],
        representation_id=row["representation_id"],
        config_fingerprint=row["config_fingerprint"].strip(),
        assigned_species_id=row["assigned_species_id"],
        best_candidate_id=row["best_candidate_id"],
        confidence=row["confidence"],
        tied_candidate_ids=tuple(row["tied_candidate_ids"]),
        candidate_scores=tuple(
            CandidateScore(value["id"], value["logit"], value["score"])
            for value in row["candidate_scores_json"]
        ),
        reason=row["reason"],
        warnings=tuple(row["warnings_json"]),
        processed_at=row["processed_at"],
        created_run_id=row["created_run_id"],
    )


def _run_summary(row: Any) -> dict[str, object]:
    return {
        "run_id": str(row["run_id"]),
        "status": row["status"],
        "started_at": _iso(row["started_at"]),
        "completed_at": _iso(row["completed_at"]),
        "counts": {
            "selected": row["selected_count"],
            "completed": row["completed_count"],
            "skipped": row["skipped_count"],
            "failed": row["failed_count"],
            "assigned": row["assigned_count"],
            "unknown": row["unknown_count"],
            "pending": row["selected_count"]
            - row["completed_count"]
            - row["skipped_count"]
            - row["failed_count"],
        },
        "config_fingerprint": row["config_fingerprint"].strip(),
    }


def _run_inspection(row: Any) -> dict[str, object]:
    result = _run_summary(row)
    result.update(
        {
            "manifest_locator": row["manifest_locator"],
            "crop_root": row["crop_root"],
            "selection_fingerprint": row["selection_fingerprint"].strip(),
            "failures": row["failures_json"],
            "model_fingerprint": row["model_fingerprint"].strip(),
            "candidate_set_fingerprint": row["candidate_set_fingerprint"].strip(),
            "scoring_fingerprint": row["scoring_fingerprint"].strip(),
            "threshold": row["threshold"],
            "config": row["config_json"],
            "model": row["model_json"],
            "candidates": row["candidates_json"],
        }
    )
    return result


def _item_inspection(row: Any) -> dict[str, object]:
    item: dict[str, object] = {
        "crop_id": row["crop_id"],
        "status": row["status"],
        "expected_snapshot_id": _strip_or_none(row["expected_snapshot_id"]),
        "expected_provenance_sha256": row["expected_provenance_sha256"].strip(),
        "lighting": row["snapshot_lighting"] or row["lighting"],
        "failure_code": row["failure_code"],
        "failure_reason": row["failure_reason"],
        "decision": None,
        "provenance": None,
    }
    if row["saved_decision_id"] is not None:
        item["decision"] = {
            "decision_id": str(row["saved_decision_id"]),
            "assigned_species_id": row["assigned_species_id"] or "unknown",
            "best_candidate_id": row["best_candidate_id"],
            "confidence": row["confidence"],
            "reason": row["reason"],
            "tied_candidate_ids": row["tied_candidate_ids"],
            "candidate_scores": row["candidate_scores_json"],
            "warnings": row["warnings_json"],
            "processed_at": _iso(row["decision_processed_at"]),
        }
        if row["snapshot_id"] is not None:
            item["provenance"] = {
                key: row[key]
                for key in (
                    "snapshot_id",
                    "provenance_sha256",
                    "crop_sha256",
                    "source_id",
                    "source_content_sha256",
                    "source_original_path",
                    "source_basename",
                    "ingest_settings_fingerprint",
                    "ingestion_run_id",
                    "frame_number",
                    "elapsed_seconds",
                    "detection_id",
                    "detection_category",
                    "detection_confidence",
                    "detection_box_normalized",
                    "crop_box_pixels",
                    "frame_width",
                    "frame_height",
                    "crop_original_image_path",
                    "capture_time",
                    "capture_timezone",
                    "source_capture_start",
                    "source_capture_timezone",
                    "lighting",
                )
            }
    return item


def _failure_json(failure: RunFailure) -> dict[str, str | None]:
    return {"crop_id": failure.crop_id, "code": failure.code, "reason": failure.reason}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def _strip_or_none(value: str | None) -> str | None:
    return value.strip() if value is not None else None


def _is_connection_error(error: Exception) -> bool:
    return isinstance(error, (psycopg.OperationalError, psycopg.InterfaceError))


def _safe_database_error(error: Exception) -> str:
    sanitized = sanitize_error(str(error))
    if not sanitized:
        sanitized = "database operation failed"
    if "database_unavailable" not in sanitized.casefold():
        sanitized = f"database_unavailable: {sanitized}"
    return sanitized


def _storage_error(error: Exception) -> StorageError:
    if isinstance(error, StorageError):
        return error
    return StorageError(_safe_database_error(error))
