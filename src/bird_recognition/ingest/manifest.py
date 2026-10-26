"""SQLite manifest persistence and stable ingestion identities."""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bird_recognition.ingest.crops import normalized_box_to_pixels
from bird_recognition.ingest.models import (
    Detection,
    DetectionCategory,
    FrameOutcome,
    IngestSettings,
    Lighting,
    SampledFrame,
    StorageError,
    ValidationError,
)

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS ingestion_run (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('running','complete','no_input','partial_failure','failed')
    ),
    input_root TEXT NOT NULL,
    output_root TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    settings_fingerprint TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS source_video (
    source_id TEXT PRIMARY KEY,
    original_path TEXT NOT NULL,
    basename TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    capture_start TEXT,
    capture_timezone TEXT,
    UNIQUE (original_path, content_sha256)
);
CREATE TABLE IF NOT EXISTS run_source (
    run_id TEXT NOT NULL REFERENCES ingestion_run(run_id),
    source_id TEXT NOT NULL REFERENCES source_video(source_id),
    settings_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processed','already_processed','failed')),
    failure_reason TEXT,
    sampled_count INTEGER NOT NULL DEFAULT 0 CHECK (sampled_count >= 0),
    person_excluded_count INTEGER NOT NULL DEFAULT 0 CHECK (person_excluded_count >= 0),
    no_animal_count INTEGER NOT NULL DEFAULT 0 CHECK (no_animal_count >= 0),
    retained_count INTEGER NOT NULL DEFAULT 0 CHECK (retained_count >= 0),
    failed_frame_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_frame_count >= 0),
    crop_count INTEGER NOT NULL DEFAULT 0 CHECK (crop_count >= 0),
    PRIMARY KEY (run_id, source_id, settings_fingerprint),
    CHECK (
        sampled_count = person_excluded_count + no_animal_count
        + retained_count + failed_frame_count
    ),
    CHECK ((status = 'failed' AND failure_reason IS NOT NULL) OR status <> 'failed')
);
CREATE TABLE IF NOT EXISTS sampled_frame (
    source_id TEXT NOT NULL REFERENCES source_video(source_id),
    settings_fingerprint TEXT NOT NULL,
    frame_number INTEGER NOT NULL CHECK (frame_number >= 0),
    elapsed_seconds REAL NOT NULL CHECK (
        elapsed_seconds >= 0 AND elapsed_seconds <= 1.7976931348623157e308
    ),
    frame_width INTEGER NOT NULL CHECK (frame_width > 0),
    frame_height INTEGER NOT NULL CHECK (frame_height > 0),
    capture_time TEXT,
    capture_timezone TEXT,
    lighting TEXT NOT NULL CHECK (lighting IN ('day','night','unknown')),
    outcome TEXT NOT NULL CHECK (
        outcome IN ('person_excluded','no_animal','retained','failed')
    ),
    failure_reason TEXT,
    run_id TEXT NOT NULL REFERENCES ingestion_run(run_id),
    PRIMARY KEY (source_id, settings_fingerprint, frame_number),
    CHECK ((outcome = 'failed' AND failure_reason IS NOT NULL) OR outcome <> 'failed')
);
CREATE TABLE IF NOT EXISTS detection (
    detection_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    settings_fingerprint TEXT NOT NULL,
    frame_number INTEGER NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('animal','person','other')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    box_left REAL NOT NULL,
    box_top REAL NOT NULL,
    box_right REAL NOT NULL,
    box_bottom REAL NOT NULL,
    qualifies INTEGER NOT NULL CHECK (qualifies IN (0,1)),
    PRIMARY KEY (detection_id, source_id, settings_fingerprint, frame_number),
    FOREIGN KEY (source_id, settings_fingerprint, frame_number)
      REFERENCES sampled_frame(source_id, settings_fingerprint, frame_number),
    CHECK (box_right > box_left AND box_bottom > box_top),
    CHECK (
        box_left >= 0 AND box_top >= 0
        AND box_right <= 1 AND box_bottom <= 1
    ),
    CHECK (category <> 'other' OR qualifies = 0)
);
CREATE TABLE IF NOT EXISTS animal_crop (
    crop_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    settings_fingerprint TEXT NOT NULL,
    frame_number INTEGER NOT NULL,
    detection_id TEXT NOT NULL,
    image_path TEXT NOT NULL UNIQUE,
    crop_sha256 TEXT NOT NULL,
    box_left INTEGER NOT NULL,
    box_top INTEGER NOT NULL,
    box_right INTEGER NOT NULL,
    box_bottom INTEGER NOT NULL,
    frame_width INTEGER NOT NULL CHECK (frame_width > 0),
    frame_height INTEGER NOT NULL CHECK (frame_height > 0),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    elapsed_seconds REAL NOT NULL CHECK (
        elapsed_seconds >= 0 AND elapsed_seconds <= 1.7976931348623157e308
    ),
    capture_time TEXT,
    capture_timezone TEXT,
    lighting TEXT NOT NULL CHECK (lighting IN ('day','night','unknown')),
    run_id TEXT NOT NULL REFERENCES ingestion_run(run_id),
    FOREIGN KEY (source_id, settings_fingerprint, frame_number)
      REFERENCES sampled_frame(source_id, settings_fingerprint, frame_number),
    FOREIGN KEY (detection_id, source_id, settings_fingerprint, frame_number)
      REFERENCES detection(detection_id, source_id, settings_fingerprint, frame_number),
    CHECK (
        box_left >= 0 AND box_top >= 0
        AND box_right <= frame_width AND box_bottom <= frame_height
    ),
    CHECK (box_right > box_left AND box_bottom > box_top)
);
"""


@contextmanager
def destination_lock(output_root: Path) -> Iterator[None]:
    """Prevent concurrent ingestion writers from sharing one destination."""
    output_root.mkdir(parents=True, exist_ok=True)
    lock_path = output_root / ".ingest.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        os.close(descriptor)
        raise StorageError(
            f"another ingestion run holds the destination lock: {output_root}"
        ) from error
    try:
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def sha256_file(path: Path) -> str:
    """Return a file's full SHA-256 digest."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_identity(path: Path, content_sha256: str) -> str:
    """Derive a stable source ID from canonical path and full content digest."""
    canonical = os.path.normcase(str(path.resolve()))
    return hashlib.sha256(f"{canonical}\0{content_sha256}".encode()).hexdigest()


def settings_identity(settings: IngestSettings) -> tuple[str, str]:
    """Return canonical effective settings JSON and its SHA-256 fingerprint."""
    payload = {
        "interval": settings.interval,
        "animal_threshold": settings.animal_threshold,
        "person_threshold": settings.person_threshold,
        "extensions": list(settings.extensions),
        "model_path": str(settings.model_path) if settings.model_path else None,
        "model_config_path": (
            str(settings.model_config_path) if settings.model_config_path else None
        ),
        "model_variant": settings.model_variant,
        "detector_name": settings.detector_name,
        "detector_version": settings.detector_version,
        "model_sha256": settings.model_sha256,
        "model_config_sha256": settings.model_config_sha256,
        "lighting_rule": settings.lighting_rule,
        "lighting_settings": dict(settings.lighting_settings),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return serialized, hashlib.sha256(serialized.encode()).hexdigest()


def stable_crop_id(
    source_id: str, settings_fingerprint: str, frame_number: int, detection_id: str
) -> str:
    """Create a stable crop identity from its immutable provenance."""
    identity = f"{source_id}\0{settings_fingerprint}\0{frame_number}\0{detection_id}"
    return hashlib.sha256(identity.encode()).hexdigest()


def stable_case_id(
    source_content_sha256: str,
    frame_number: int,
    detection_id: str,
    detection_box_normalized: tuple[float, float, float, float],
) -> str:
    """Derive a crop-policy-independent identity for one source detection."""
    if len(source_content_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in source_content_sha256
    ):
        raise ValidationError("source content digest must be a lowercase SHA-256")
    if type(frame_number) is not int or frame_number < 0:
        raise ValidationError("case frame number must be a non-negative integer")
    if not isinstance(detection_id, str) or not detection_id:
        raise ValidationError("case detection ID must not be blank")
    if len(detection_box_normalized) != 4 or any(
        not math.isfinite(value) or not 0 <= value <= 1
        for value in detection_box_normalized
    ):
        raise ValidationError("case detection box must contain normalized coordinates")
    left, top, right, bottom = detection_box_normalized
    if right <= left or bottom <= top:
        raise ValidationError("case detection box must have positive area")
    canonical = json.dumps(
        {
            "source_content_sha256": source_content_sha256,
            "frame_number": frame_number,
            "detection_id": detection_id,
            "detection_box_normalized": list(detection_box_normalized),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Manifest:
    """Store run, source, frame, detection, and crop provenance in SQLite."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.output_root / "manifest.sqlite3"
        try:
            with self._connect() as connection:
                connection.executescript(SCHEMA)
        except sqlite3.Error as error:
            raise StorageError(f"cannot initialize manifest: {error}") from error

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()
        finally:
            connection.close()

    def start_run(self, input_root: Path, settings: IngestSettings) -> tuple[str, str]:
        """Create a running record and return its ID and settings fingerprint."""
        serialized, fingerprint = settings_identity(settings)
        run_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO ingestion_run "
                "(run_id,started_at,status,input_root,output_root,settings_json,"
                "settings_fingerprint) VALUES (?,?,?,?,?,?,?)",
                (
                    run_id,
                    datetime.now(UTC).isoformat(),
                    "running",
                    str(input_root.resolve()),
                    str(self.output_root),
                    serialized,
                    fingerprint,
                ),
            )
        return run_id, fingerprint

    def put_source(
        self,
        path: Path,
        content_sha256: str,
        capture_start: str | None = None,
        capture_timezone: str | None = None,
    ) -> str:
        """Insert or verify immutable source identity."""
        canonical = path.resolve()
        source_id = source_identity(canonical, content_sha256)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO source_video (source_id,original_path,basename,"
                "content_sha256,capture_start,capture_timezone) VALUES (?,?,?,?,?,?)",
                (
                    source_id,
                    str(canonical),
                    canonical.name,
                    content_sha256,
                    capture_start,
                    capture_timezone,
                ),
            )
        return source_id

    def has_completed_source(self, source_id: str, settings_fingerprint: str) -> bool:
        """Check for an identical source/settings result in this destination."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM run_source rs JOIN ingestion_run r USING(run_id) "
                "WHERE rs.source_id=? AND rs.settings_fingerprint=? "
                "AND ((rs.status='processed' "
                "AND r.status IN ('complete','partial_failure')) "
                "OR (rs.status='already_processed' AND r.status='complete')) LIMIT 1",
                (source_id, settings_fingerprint),
            ).fetchone()
        return row is not None

    def set_source_capture_time(
        self, source_id: str, capture_start: str | None, capture_timezone: str | None
    ) -> None:
        """Store recognized capture metadata, preserving unavailable values as null."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE source_video SET capture_start=?,capture_timezone=? "
                "WHERE source_id=?",
                (capture_start, capture_timezone, source_id),
            )

    def begin_source(
        self, run_id: str, source_id: str, settings_fingerprint: str
    ) -> None:
        """Record that a source is being evaluated in this run."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO run_source (run_id,source_id,settings_fingerprint,status) "
                "VALUES (?,?,?,'processed')",
                (run_id, source_id, settings_fingerprint),
            )

    def record_skipped_source(
        self, run_id: str, source_id: str, settings_fingerprint: str
    ) -> None:
        """Record an unchanged source that reuses an earlier completed result."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO run_source (run_id,source_id,settings_fingerprint,status) "
                "VALUES (?,?,?,'already_processed')",
                (run_id, source_id, settings_fingerprint),
            )

    def reusable_frame(
        self,
        run_id: str,
        source_id: str,
        settings_fingerprint: str,
        frame_number: int,
    ) -> tuple[FrameOutcome, int] | None:
        """Return a previously committed non-failed frame outcome, if present."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT outcome,run_id FROM sampled_frame WHERE source_id=? "
                "AND settings_fingerprint=? AND frame_number=?",
                (source_id, settings_fingerprint, frame_number),
            ).fetchone()
            if row is None:
                return None
            outcome = FrameOutcome(row["outcome"])
            previous_run_id = str(row["run_id"])
            crop_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM animal_crop WHERE source_id=? "
                    "AND settings_fingerprint=? AND frame_number=?",
                    (source_id, settings_fingerprint, frame_number),
                ).fetchone()[0]
            )
            if previous_run_id != run_id:
                outcome_column = {
                    FrameOutcome.PERSON_EXCLUDED: "person_excluded_count",
                    FrameOutcome.NO_ANIMAL: "no_animal_count",
                    FrameOutcome.RETAINED: "retained_count",
                    FrameOutcome.FAILED: "failed_frame_count",
                }[outcome]
                connection.execute(
                    f"UPDATE run_source SET sampled_count=sampled_count-1,"
                    f"{outcome_column}={outcome_column}-1,crop_count=crop_count-? "
                    "WHERE run_id=? AND source_id=? AND settings_fingerprint=?",
                    (
                        crop_count,
                        previous_run_id,
                        source_id,
                        settings_fingerprint,
                    ),
                )
            if outcome is FrameOutcome.FAILED:
                connection.execute(
                    "DELETE FROM detection WHERE source_id=? "
                    "AND settings_fingerprint=? "
                    "AND frame_number=?",
                    (source_id, settings_fingerprint, frame_number),
                )
                connection.execute(
                    "DELETE FROM sampled_frame WHERE source_id=? "
                    "AND settings_fingerprint=? AND frame_number=?",
                    (source_id, settings_fingerprint, frame_number),
                )
                return None
            connection.execute(
                "UPDATE sampled_frame SET run_id=? WHERE source_id=? "
                "AND settings_fingerprint=? AND frame_number=?",
                (run_id, source_id, settings_fingerprint, frame_number),
            )
            connection.execute(
                "UPDATE animal_crop SET run_id=? WHERE source_id=? "
                "AND settings_fingerprint=? AND frame_number=?",
                (run_id, source_id, settings_fingerprint, frame_number),
            )
        return outcome, int(crop_count)

    def commit_frame(
        self,
        run_id: str,
        source_id: str,
        settings_fingerprint: str,
        frame: SampledFrame,
        outcome: FrameOutcome,
        lighting: Lighting,
        detections: tuple[Detection, ...],
        crop_records: tuple[dict[str, Any], ...],
        settings: IngestSettings,
        capture_time: str | None,
        capture_timezone: str | None,
        failure_reason: str | None = None,
    ) -> None:
        """Atomically persist one frame, detections, and its complete crop set."""
        if outcome is FrameOutcome.FAILED and not failure_reason:
            raise StorageError("failed frames require a failure reason")
        if outcome is FrameOutcome.RETAINED and not crop_records:
            raise StorageError("retained frames require at least one complete crop")
        if outcome is not FrameOutcome.RETAINED and crop_records:
            raise StorageError("only retained frames may have crop records")
        qualifying_animals = 0
        qualifying_people = 0
        detection_map: dict[str, Detection] = {}
        for index, detection in enumerate(detections):
            detection_id = detection.detection_id or f"d{index:06d}"
            detection_map[detection_id] = detection
            expected_qualification = (
                detection.category is DetectionCategory.ANIMAL
                and detection.confidence >= settings.animal_threshold
            ) or (
                detection.category is DetectionCategory.PERSON
                and detection.confidence >= settings.person_threshold
            )
            if detection.qualifies != expected_qualification:
                raise StorageError(
                    "detection qualification does not match effective thresholds"
                )
            if detection.category is DetectionCategory.ANIMAL and detection.qualifies:
                qualifying_animals += 1
            if detection.category is DetectionCategory.PERSON and detection.qualifies:
                qualifying_people += 1
        if outcome is FrameOutcome.PERSON_EXCLUDED and not qualifying_people:
            raise StorageError("person-excluded frames require a qualifying person")
        if outcome is FrameOutcome.NO_ANIMAL and (
            qualifying_people or qualifying_animals
        ):
            raise StorageError("no-animal outcome conflicts with qualifying detections")
        if outcome is FrameOutcome.RETAINED and (
            qualifying_people or not qualifying_animals
        ):
            raise StorageError(
                "retained outcome requires animals and no qualifying people"
            )
        if outcome is FrameOutcome.RETAINED and len(crop_records) != qualifying_animals:
            raise StorageError("retained frames require one crop per qualifying animal")
        for crop in crop_records:
            image_path = self._validate_crop_path(str(crop["image_path"]))
            detection = detection_map.get(str(crop["detection_id"]))
            if (
                detection is None
                or detection.category is not DetectionCategory.ANIMAL
                or not detection.qualifies
            ):
                raise StorageError("crop must refer to a qualifying animal detection")
            expected_box = normalized_box_to_pixels(
                detection.box, frame.width, frame.height
            )
            saved_box = (
                crop["box_left"],
                crop["box_top"],
                crop["box_right"],
                crop["box_bottom"],
            )
            if saved_box != expected_box:
                raise StorageError("crop pixel box does not match normalized detection")
            if (
                crop["frame_width"] != frame.width
                or crop["frame_height"] != frame.height
                or crop["lighting"] != lighting.value
                or crop["elapsed_seconds"] != frame.elapsed_seconds
                or crop["capture_time"] != capture_time
                or crop["capture_timezone"] != capture_timezone
                or crop["confidence"] != detection.confidence
                or crop["run_id"] != run_id
            ):
                raise StorageError("crop provenance does not match its source frame")
            if crop["crop_sha256"] != sha256_file(image_path):
                raise StorageError("crop image hash does not match its manifest record")
            try:
                from PIL import Image

                with Image.open(image_path) as image:
                    image.verify()
                with Image.open(image_path) as image:
                    expected_size = (
                        crop["box_right"] - crop["box_left"],
                        crop["box_bottom"] - crop["box_top"],
                    )
                    if image.size != expected_size:
                        raise StorageError(
                            "saved crop dimensions do not match its pixel box"
                        )
            except StorageError:
                raise
            except ImportError as error:
                raise StorageError(
                    "Pillow is required to validate persisted crop images"
                ) from error
            except Exception as error:
                raise StorageError("saved crop image is unreadable") from error
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO sampled_frame "
                    "(source_id,settings_fingerprint,frame_number,elapsed_seconds,"
                    "frame_width,frame_height,capture_time,capture_timezone,lighting,"
                    "outcome,failure_reason,run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        source_id,
                        settings_fingerprint,
                        frame.frame_number,
                        frame.elapsed_seconds,
                        frame.width,
                        frame.height,
                        capture_time,
                        capture_timezone,
                        lighting.value,
                        outcome.value,
                        failure_reason,
                        run_id,
                    ),
                )
                for index, detection in enumerate(detections):
                    detection_id = detection.detection_id or f"d{index:06d}"
                    connection.execute(
                        "INSERT INTO detection VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            detection_id,
                            source_id,
                            settings_fingerprint,
                            frame.frame_number,
                            detection.category.value,
                            detection.confidence,
                            *detection.box,
                            int(detection.qualifies),
                        ),
                    )
                for crop in crop_records:
                    connection.execute(
                        "INSERT INTO animal_crop VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(
                            crop[key]
                            for key in (
                                "crop_id",
                                "source_id",
                                "settings_fingerprint",
                                "frame_number",
                                "detection_id",
                                "image_path",
                                "crop_sha256",
                                "box_left",
                                "box_top",
                                "box_right",
                                "box_bottom",
                                "frame_width",
                                "frame_height",
                                "confidence",
                                "elapsed_seconds",
                                "capture_time",
                                "capture_timezone",
                                "lighting",
                                "run_id",
                            )
                        ),
                    )
        except (sqlite3.Error, KeyError, OSError, ValueError) as error:
            raise StorageError(
                f"failed to commit frame {frame.frame_number}: {error}"
            ) from error

    def _validate_crop_path(self, relative_path: str) -> Path:
        if Path(relative_path).is_absolute():
            raise StorageError("crop path must be relative to output root")
        path = (self.output_root / relative_path).resolve()
        if (
            path == self.output_root
            or self.output_root not in path.parents
            or not path.is_file()
        ):
            raise StorageError(
                "crop path must point to an existing file under output root"
            )
        return path

    def finish_source(
        self,
        run_id: str,
        source_id: str,
        settings_fingerprint: str,
        counts: dict[str, int],
        status: str = "processed",
        failure_reason: str | None = None,
    ) -> None:
        """Persist reconciled source counts and terminal source status."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE run_source SET status=?,failure_reason=?,sampled_count=?,"
                "person_excluded_count=?,no_animal_count=?,retained_count=?,"
                "failed_frame_count=?,crop_count=? "
                "WHERE run_id=? AND source_id=? AND settings_fingerprint=?",
                (
                    status,
                    failure_reason,
                    counts.get("sampled", 0),
                    counts.get("person_excluded", 0),
                    counts.get("no_animal", 0),
                    counts.get("retained", 0),
                    counts.get("failed", 0),
                    counts.get("crops", 0),
                    run_id,
                    source_id,
                    settings_fingerprint,
                ),
            )
            if cursor.rowcount != 1:
                raise StorageError("source summary record was not found")

    def finish_run(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        """Persist run summary and its terminal state."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE ingestion_run SET completed_at=?,status=?,summary_json=? "
                "WHERE run_id=?",
                (
                    datetime.now(UTC).isoformat(),
                    status,
                    json.dumps(summary, sort_keys=True),
                    run_id,
                ),
            )

    def recover(self) -> None:
        """Remove stale staging content and unreferenced crop files."""
        with self._connect() as connection:
            interrupted = connection.execute(
                "SELECT run_id FROM ingestion_run WHERE status='running'"
            ).fetchall()
            for row in interrupted:
                run_id = row["run_id"]
                sources = connection.execute(
                    "SELECT source_id,settings_fingerprint FROM run_source "
                    "WHERE run_id=? AND status='processed'",
                    (run_id,),
                ).fetchall()
                for source in sources:
                    key = (source["source_id"], source["settings_fingerprint"])
                    outcomes = {
                        result["outcome"]: result["count"]
                        for result in connection.execute(
                            "SELECT outcome,COUNT(*) AS count FROM sampled_frame "
                            "WHERE run_id=? AND source_id=? AND settings_fingerprint=? "
                            "GROUP BY outcome",
                            (run_id, *key),
                        )
                    }
                    counts = {
                        "person_excluded": outcomes.get("person_excluded", 0),
                        "no_animal": outcomes.get("no_animal", 0),
                        "retained": outcomes.get("retained", 0),
                        "failed": outcomes.get("failed", 0),
                    }
                    sampled_count = sum(counts.values())
                    crop_count = connection.execute(
                        "SELECT COUNT(*) FROM animal_crop WHERE run_id=? "
                        "AND source_id=? AND settings_fingerprint=?",
                        (run_id, *key),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE run_source SET status='failed',"
                        "failure_reason='previous ingestion run was interrupted',"
                        "sampled_count=?,person_excluded_count=?,no_animal_count=?,"
                        "retained_count=?,failed_frame_count=?,crop_count=? "
                        "WHERE run_id=? AND source_id=? AND settings_fingerprint=?",
                        (
                            sampled_count,
                            counts["person_excluded"],
                            counts["no_animal"],
                            counts["retained"],
                            counts["failed"],
                            crop_count,
                            run_id,
                            *key,
                        ),
                    )
                connection.execute(
                    "UPDATE ingestion_run SET status='failed',completed_at=?,"
                    "summary_json=? WHERE run_id=?",
                    (
                        datetime.now(UTC).isoformat(),
                        json.dumps({"error": "previous ingestion run was interrupted"}),
                        run_id,
                    ),
                )
        crop_root = self.output_root / "crops"
        if not crop_root.exists():
            return
        with self._connect() as connection:
            referenced = {
                str((self.output_root / row[0]).resolve())
                for row in connection.execute("SELECT image_path FROM animal_crop")
            }
        for path in crop_root.rglob("*"):
            if not path.is_file():
                continue
            is_staging = any(part.endswith(".staging") for part in path.parts)
            if is_staging or str(path.resolve()) not in referenced:
                path.unlink(missing_ok=True)
        for path in sorted(crop_root.rglob("*"), reverse=True):
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass

    def close(self) -> None:
        """Checkpoint the SQLite write-ahead log."""
        with self._connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
