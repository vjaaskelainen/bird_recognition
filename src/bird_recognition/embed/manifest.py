"""Read-only snapshot access to the ingestion SQLite manifest."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from bird_recognition.embed.config import canonical_json_sha256
from bird_recognition.embed.models import (
    EmbedValidationError,
    IngestedCropSnapshot,
    IsolatedCropError,
    Lighting,
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_COLUMNS = {
    "animal_crop": {
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
    },
    "source_video": {
        "source_id",
        "original_path",
        "basename",
        "content_sha256",
        "capture_start",
        "capture_timezone",
    },
    "sampled_frame": {
        "source_id",
        "settings_fingerprint",
        "frame_number",
        "elapsed_seconds",
        "frame_width",
        "frame_height",
        "capture_time",
        "capture_timezone",
        "lighting",
        "outcome",
        "run_id",
    },
    "detection": {
        "detection_id",
        "source_id",
        "settings_fingerprint",
        "frame_number",
        "category",
        "confidence",
        "box_left",
        "box_top",
        "box_right",
        "box_bottom",
        "qualifies",
    },
    "ingestion_run": {"run_id", "settings_fingerprint"},
    "run_source": {"run_id", "source_id", "settings_fingerprint"},
}


def read_manifest_snapshot(
    database_path: Path, crop_root: Path
) -> list[IngestedCropSnapshot]:
    """Read every retained crop from one consistent, query-only snapshot."""
    connection: sqlite3.Connection | None = None
    try:
        manifest_path = database_path.resolve(strict=True)
        if not manifest_path.is_file():
            raise EmbedValidationError("manifest database is unavailable")
        connection = sqlite3.connect(
            f"{manifest_path.as_uri()}?mode=ro", uri=True, timeout=30
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        _validate_manifest_schema(connection)
        rows = connection.execute(
            "SELECT c.crop_id, c.source_id, c.settings_fingerprint, c.frame_number, "
            "c.detection_id, c.image_path, c.crop_sha256, c.box_left, c.box_top, "
            "c.box_right, c.box_bottom, c.frame_width, c.frame_height, c.confidence, "
            "c.elapsed_seconds, c.capture_time, c.capture_timezone, c.lighting, "
            "c.run_id, s.original_path AS source_original_path, "
            "s.basename AS source_basename, s.content_sha256 AS source_content_sha256, "
            "s.capture_start AS source_capture_start, "
            "s.capture_timezone AS source_capture_timezone, "
            "f.elapsed_seconds AS frame_elapsed_seconds, "
            "f.frame_width AS frame_width_from_frame, "
            "f.frame_height AS frame_height_from_frame, "
            "f.capture_time AS frame_capture_time, "
            "f.capture_timezone AS frame_capture_timezone, "
            "f.lighting AS frame_lighting, f.outcome AS frame_outcome, "
            "f.run_id AS frame_run_id, d.category AS detection_category, "
            "d.confidence AS detection_confidence, d.box_left AS detection_left, "
            "d.box_top AS detection_top, d.box_right AS detection_right, "
            "d.box_bottom AS detection_bottom, d.qualifies AS detection_qualifies, "
            "r.run_id AS matched_run_id, "
            "r.settings_fingerprint AS run_settings_fingerprint, "
            "rs.run_id AS matched_run_source_id "
            "FROM animal_crop AS c "
            "LEFT JOIN source_video AS s ON s.source_id = c.source_id "
            "LEFT JOIN sampled_frame AS f ON f.source_id = c.source_id "
            "AND f.settings_fingerprint = c.settings_fingerprint "
            "AND f.frame_number = c.frame_number "
            "LEFT JOIN detection AS d ON d.detection_id = c.detection_id "
            "AND d.source_id = c.source_id "
            "AND d.settings_fingerprint = c.settings_fingerprint "
            "AND d.frame_number = c.frame_number "
            "LEFT JOIN ingestion_run AS r ON r.run_id = c.run_id "
            "LEFT JOIN run_source AS rs ON rs.run_id = c.run_id "
            "AND rs.source_id = c.source_id "
            "AND rs.settings_fingerprint = c.settings_fingerprint "
            "ORDER BY c.crop_id"
        ).fetchall()
        snapshots = [_snapshot_from_row(row) for row in rows]
        connection.commit()
        return snapshots
    except EmbedValidationError:
        if connection is not None:
            connection.rollback()
        raise
    except OSError, sqlite3.Error, TypeError, ValueError, OverflowError:
        if connection is not None:
            connection.rollback()
        raise EmbedValidationError(
            "manifest is unreadable or structurally invalid"
        ) from None
    finally:
        if connection is not None:
            connection.close()


def resolve_crop_path(crop_root: Path, relative_path: str) -> Path:
    """Resolve a manifest-relative crop path without allowing root escape."""
    if not isinstance(relative_path, str) or not relative_path:
        raise IsolatedCropError("crop path is invalid")
    relative = Path(relative_path)
    windows_relative = PureWindowsPath(relative_path)
    if (
        relative.is_absolute()
        or windows_relative.is_absolute()
        or windows_relative.drive
        or ".." in relative.parts
        or ".." in windows_relative.parts
    ):
        raise IsolatedCropError("crop path escapes the crop root")
    try:
        root = crop_root.resolve()
        resolved = (root / relative).resolve()
    except OSError, RuntimeError, ValueError:
        raise IsolatedCropError("crop path cannot be safely resolved") from None
    if resolved == root or root not in resolved.parents:
        raise IsolatedCropError("crop path escapes the crop root")
    return resolved


def _validate_manifest_schema(connection: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if not _REQUIRED_COLUMNS.keys() <= tables:
        raise EmbedValidationError("manifest schema is incomplete")
    for table, required_columns in _REQUIRED_COLUMNS.items():
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if not required_columns <= columns:
            raise EmbedValidationError("manifest schema is incompatible")
    if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise EmbedValidationError("manifest integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise EmbedValidationError("manifest contains orphaned rows")


def _snapshot_from_row(row: sqlite3.Row) -> IngestedCropSnapshot:
    if any(
        row[key] is None
        for key in (
            "source_original_path",
            "source_basename",
            "source_content_sha256",
            "frame_elapsed_seconds",
            "frame_width_from_frame",
            "frame_height_from_frame",
            "frame_lighting",
            "frame_outcome",
            "frame_run_id",
            "detection_category",
            "detection_confidence",
            "detection_left",
            "detection_top",
            "detection_right",
            "detection_bottom",
            "detection_qualifies",
            "matched_run_id",
            "run_settings_fingerprint",
            "matched_run_source_id",
        )
    ):
        raise EmbedValidationError("crop has an incomplete provenance relationship")

    crop_id = _required_text(row, "crop_id")
    source_id = _required_text(row, "source_id")
    detection_id = _required_text(row, "detection_id")
    run_id = _required_text(row, "run_id")
    settings_fingerprint = _required_sha256(row, "settings_fingerprint")
    crop_sha256 = _required_sha256(row, "crop_sha256")
    source_content_sha256 = _required_sha256(row, "source_content_sha256")
    source_original_path = _required_text(row, "source_original_path")
    source_basename = _required_text(row, "source_basename")
    image_path = row["image_path"]
    if not isinstance(image_path, str):
        raise EmbedValidationError("manifest contains an invalid crop path")

    frame_number = _required_integer(row, "frame_number")
    if frame_number < 0:
        raise EmbedValidationError("frame number must be non-negative")
    elapsed_seconds = _required_number(row, "elapsed_seconds", minimum=0)
    frame_elapsed_seconds = _required_number(row, "frame_elapsed_seconds", minimum=0)
    frame_width = _required_integer(row, "frame_width")
    frame_height = _required_integer(row, "frame_height")
    frame_width_from_frame = _required_integer(row, "frame_width_from_frame")
    frame_height_from_frame = _required_integer(row, "frame_height_from_frame")
    if (
        frame_width <= 0
        or frame_height <= 0
        or frame_width != frame_width_from_frame
        or frame_height != frame_height_from_frame
        or elapsed_seconds != frame_elapsed_seconds
    ):
        raise EmbedValidationError("crop frame metadata is inconsistent")

    capture_time = _nullable_text(row, "capture_time")
    capture_timezone = _nullable_text(row, "capture_timezone")
    source_capture_start = _nullable_text(row, "source_capture_start")
    source_capture_timezone = _nullable_text(row, "source_capture_timezone")
    if capture_time != _nullable_text(
        row, "frame_capture_time"
    ) or capture_timezone != _nullable_text(row, "frame_capture_timezone"):
        raise EmbedValidationError("crop capture metadata is inconsistent")

    lighting = _required_text(row, "lighting")
    if (
        lighting != _required_text(row, "frame_lighting")
        or row["frame_outcome"] != "retained"
    ):
        raise EmbedValidationError("crop does not belong to a retained frame")
    try:
        parsed_lighting = Lighting(lighting)
    except ValueError:
        raise EmbedValidationError("crop lighting is invalid") from None

    detection_category = _required_text(row, "detection_category")
    if detection_category != "animal" or row["detection_qualifies"] != 1:
        raise EmbedValidationError("crop does not reference a qualifying animal")
    detection_confidence = _required_number(
        row, "detection_confidence", minimum=0, maximum=1
    )
    crop_confidence = _required_number(row, "confidence", minimum=0, maximum=1)
    if crop_confidence != detection_confidence:
        raise EmbedValidationError("crop detection confidence is inconsistent")

    detection_box = tuple(
        _required_number(row, key, minimum=0, maximum=1)
        for key in (
            "detection_left",
            "detection_top",
            "detection_right",
            "detection_bottom",
        )
    )
    if detection_box[2] <= detection_box[0] or detection_box[3] <= detection_box[1]:
        raise EmbedValidationError("detection bounds are invalid")
    crop_box = tuple(
        _required_integer(row, key)
        for key in ("box_left", "box_top", "box_right", "box_bottom")
    )
    left, top, right, bottom = crop_box
    if (
        left < 0
        or top < 0
        or right <= left
        or bottom <= top
        or right > frame_width
        or bottom > frame_height
    ):
        raise EmbedValidationError("crop bounds are invalid")

    if (
        run_id != _required_text(row, "frame_run_id")
        or run_id != _required_text(row, "matched_run_id")
        or run_id != _required_text(row, "matched_run_source_id")
        or settings_fingerprint != _required_sha256(row, "run_settings_fingerprint")
    ):
        raise EmbedValidationError("crop run provenance is inconsistent")

    provenance = {
        "crop_id": crop_id,
        "crop_sha256": crop_sha256,
        "source_id": source_id,
        "source_content_sha256": source_content_sha256,
        "source_original_path": source_original_path,
        "source_basename": source_basename,
        "ingest_settings_fingerprint": settings_fingerprint,
        "ingestion_run_id": run_id,
        "frame_number": frame_number,
        "elapsed_seconds": elapsed_seconds,
        "detection_id": detection_id,
        "detection_category": detection_category,
        "detection_confidence": detection_confidence,
        "detection_box_normalized": detection_box,
        "crop_box_pixels": crop_box,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "crop_original_image_path": image_path,
        "capture_time": capture_time,
        "capture_timezone": capture_timezone,
        "source_capture_start": source_capture_start,
        "source_capture_timezone": source_capture_timezone,
        "lighting": lighting,
    }
    provenance_sha256 = canonical_json_sha256(provenance)
    snapshot_id = hashlib.sha256(f"{crop_id}\0{provenance_sha256}".encode()).hexdigest()
    return IngestedCropSnapshot(
        snapshot_id=snapshot_id,
        crop_id=crop_id,
        provenance_sha256=provenance_sha256,
        crop_sha256=crop_sha256,
        source_id=source_id,
        source_content_sha256=source_content_sha256,
        source_original_path=source_original_path,
        source_basename=source_basename,
        ingest_settings_fingerprint=settings_fingerprint,
        ingestion_run_id=run_id,
        frame_number=frame_number,
        elapsed_seconds=elapsed_seconds,
        detection_id=detection_id,
        detection_category=detection_category,
        detection_confidence=detection_confidence,
        detection_box_normalized=detection_box,
        crop_box_pixels=crop_box,
        frame_width=frame_width,
        frame_height=frame_height,
        crop_original_image_path=image_path,
        capture_time=capture_time,
        capture_timezone=capture_timezone,
        source_capture_start=source_capture_start,
        source_capture_timezone=source_capture_timezone,
        lighting=parsed_lighting,
        imported_at=datetime.now(UTC),
    )


def _required_text(row: sqlite3.Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str) or not value:
        raise EmbedValidationError("manifest contains an invalid text field")
    return value


def _nullable_text(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is not None and not isinstance(value, str):
        raise EmbedValidationError("manifest contains invalid nullable metadata")
    return value


def _required_sha256(row: sqlite3.Row, key: str) -> str:
    value = _required_text(row, key)
    if not _SHA256_PATTERN.fullmatch(value):
        raise EmbedValidationError("manifest contains an invalid SHA-256 digest")
    return value


def _required_integer(row: sqlite3.Row, key: str) -> int:
    value = row[key]
    if type(value) is not int:
        raise EmbedValidationError("manifest contains an invalid integer field")
    return value


def _required_number(
    row: sqlite3.Row,
    key: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EmbedValidationError("manifest contains an invalid numeric field")
    number = float(value)
    if (
        not math.isfinite(number)
        or (minimum is not None and number < minimum)
        or (maximum is not None and number > maximum)
    ):
        raise EmbedValidationError("manifest contains an out-of-range numeric field")
    return number
