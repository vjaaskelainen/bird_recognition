from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from bird_recognition.embed.config import canonical_json_sha256
from bird_recognition.embed.manifest import read_manifest_snapshot, resolve_crop_path
from bird_recognition.embed.models import EmbedValidationError, IsolatedCropError


def _seed_crop(
    database_path: Path,
    crop_root: Path,
    crop_id: str,
    source_id: str,
    settings_fingerprint: str,
    run_id: str,
    detection_id: str,
    *,
    image_path: str | None = None,
    crop_bytes: bytes = b"synthetic crop",
    recorded_hash: str | None = None,
    capture_time: str | None = None,
    source_capture_start: str | None = None,
    lighting: str = "day",
    detection_confidence: float = 0.875,
) -> Path:
    relative_image_path = image_path or f"crops/{crop_id}.png"
    image_file = crop_root / relative_image_path
    image_file.parent.mkdir(parents=True, exist_ok=True)
    image_file.write_bytes(crop_bytes)
    content_sha256 = hashlib.sha256(f"content-{source_id}".encode()).hexdigest()
    actual_hash = hashlib.sha256(crop_bytes).hexdigest()
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO ingestion_run "
            "(run_id,started_at,completed_at,status,input_root,output_root,"
            "settings_json,settings_fingerprint,summary_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:01:00+00:00",
                "partial_failure",
                "synthetic-input",
                str(crop_root),
                "{}",
                settings_fingerprint,
                '{"failed": 1}',
            ),
        )
        connection.execute(
            "INSERT INTO source_video "
            "(source_id,original_path,basename,content_sha256,capture_start,"
            "capture_timezone) VALUES (?,?,?,?,?,?)",
            (
                source_id,
                f"synthetic-source/{source_id}.mp4",
                f"{source_id}.mp4",
                content_sha256,
                source_capture_start,
                None,
            ),
        )
        connection.execute(
            "INSERT INTO run_source "
            "(run_id,source_id,settings_fingerprint,status,sampled_count,"
            "retained_count,failed_frame_count,crop_count) "
            "VALUES (?,?,?,'processed',2,1,1,1)",
            (run_id, source_id, settings_fingerprint),
        )
        connection.execute(
            "INSERT INTO sampled_frame "
            "(source_id,settings_fingerprint,frame_number,elapsed_seconds,"
            "frame_width,frame_height,capture_time,capture_timezone,lighting,"
            "outcome,run_id) VALUES (?,?,0,12.5,10,10,?,NULL,?,'retained',?)",
            (source_id, settings_fingerprint, capture_time, lighting, run_id),
        )
        connection.execute(
            "INSERT INTO sampled_frame "
            "(source_id,settings_fingerprint,frame_number,elapsed_seconds,"
            "frame_width,frame_height,capture_time,capture_timezone,lighting,"
            "outcome,failure_reason,run_id) "
            "VALUES (?,?,1,13.5,10,10,NULL,NULL,'unknown','failed',"
            "'synthetic failure',?)",
            (source_id, settings_fingerprint, run_id),
        )
        connection.execute(
            "INSERT INTO detection VALUES (?,?,?,0,'animal',?,0.2,0.2,0.8,0.8,1)",
            (
                detection_id,
                source_id,
                settings_fingerprint,
                detection_confidence,
            ),
        )
        connection.execute(
            "INSERT INTO animal_crop "
            "(crop_id,source_id,settings_fingerprint,frame_number,detection_id,"
            "image_path,crop_sha256,box_left,box_top,box_right,box_bottom,"
            "frame_width,frame_height,confidence,elapsed_seconds,capture_time,"
            "capture_timezone,lighting,run_id) "
            "VALUES (?,?,?,0,?,?,?,2,2,8,8,10,10,?,12.5,?,NULL,?,?)",
            (
                crop_id,
                source_id,
                settings_fingerprint,
                detection_id,
                relative_image_path,
                recorded_hash or actual_hash,
                detection_confidence,
                capture_time,
                lighting,
                run_id,
            ),
        )
    return image_file


def _database_schema(database_path: Path) -> tuple[tuple[str, str, str], ...]:
    with sqlite3.connect(database_path) as connection:
        return tuple(
            connection.execute(
                "SELECT type,name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
        )


def test_snapshot_joins_composite_keys_and_retains_partial_failure_crops(
    ingestion_schema: Path, tmp_path: Path
) -> None:
    crop_root = tmp_path / "ingestion-output"
    crop_z_path = _seed_crop(
        ingestion_schema,
        crop_root,
        "crop-z",
        "source-z",
        "a" * 64,
        "run-z",
        "same-detection-id",
        detection_confidence=0.7,
        lighting="night",
    )
    crop_a_path = _seed_crop(
        ingestion_schema,
        crop_root,
        "crop-a",
        "source-a",
        "b" * 64,
        "run-a",
        "same-detection-id",
        detection_confidence=0.9,
        lighting="day",
    )
    crop_bytes = {
        crop_z_path: crop_z_path.read_bytes(),
        crop_a_path: crop_a_path.read_bytes(),
    }
    database_bytes = ingestion_schema.read_bytes()
    database_schema = _database_schema(ingestion_schema)

    snapshots = read_manifest_snapshot(ingestion_schema, crop_root)

    assert [snapshot.crop_id for snapshot in snapshots] == ["crop-a", "crop-z"]
    assert [snapshot.source_id for snapshot in snapshots] == ["source-a", "source-z"]
    assert [snapshot.detection_id for snapshot in snapshots] == [
        "same-detection-id",
        "same-detection-id",
    ]
    assert [snapshot.detection_confidence for snapshot in snapshots] == [0.9, 0.7]
    assert [snapshot.lighting.value for snapshot in snapshots] == ["day", "night"]
    assert all(snapshot.ingestion_run_id for snapshot in snapshots)
    assert all(snapshot.source_content_sha256 for snapshot in snapshots)
    assert all(
        snapshot.detection_box_normalized == (0.2, 0.2, 0.8, 0.8)
        for snapshot in snapshots
    )
    assert all(snapshot.crop_box_pixels == (2, 2, 8, 8) for snapshot in snapshots)
    assert all(
        crop_path.read_bytes() == original for crop_path, original in crop_bytes.items()
    )
    assert ingestion_schema.read_bytes() == database_bytes
    assert _database_schema(ingestion_schema) == database_schema


def test_snapshot_hashes_complete_semantic_provenance(
    ingestion_schema: Path, tmp_path: Path
) -> None:
    crop_root = tmp_path / "ingestion-output"
    _seed_crop(
        ingestion_schema,
        crop_root,
        "crop",
        "source",
        "a" * 64,
        "run",
        "detection",
    )
    expected_provenance = {
        "crop_id": "crop",
        "crop_sha256": hashlib.sha256(b"synthetic crop").hexdigest(),
        "source_id": "source",
        "source_content_sha256": hashlib.sha256(b"content-source").hexdigest(),
        "source_original_path": "synthetic-source/source.mp4",
        "source_basename": "source.mp4",
        "ingest_settings_fingerprint": "a" * 64,
        "ingestion_run_id": "run",
        "frame_number": 0,
        "elapsed_seconds": 12.5,
        "detection_id": "detection",
        "detection_category": "animal",
        "detection_confidence": 0.875,
        "detection_box_normalized": (0.2, 0.2, 0.8, 0.8),
        "crop_box_pixels": (2, 2, 8, 8),
        "frame_width": 10,
        "frame_height": 10,
        "crop_original_image_path": "crops/crop.png",
        "capture_time": None,
        "capture_timezone": None,
        "source_capture_start": None,
        "source_capture_timezone": None,
        "lighting": "day",
    }

    snapshot = read_manifest_snapshot(ingestion_schema, crop_root)[0]
    expected_digest = canonical_json_sha256(expected_provenance)

    assert snapshot.provenance_sha256 == expected_digest
    assert (
        snapshot.snapshot_id
        == hashlib.sha256(f"crop\0{expected_digest}".encode()).hexdigest()
    )


@pytest.mark.parametrize(
    "corruption",
    (
        "source",
        "frame",
        "detection",
        "run",
        "non_retained",
        "not_qualified",
        "confidence",
    ),
)
def test_snapshot_rejects_orphan_or_inconsistent_manifest_rows(
    ingestion_schema: Path, tmp_path: Path, corruption: str
) -> None:
    crop_root = tmp_path / "ingestion-output"
    _seed_crop(
        ingestion_schema,
        crop_root,
        "crop",
        "source",
        "c" * 64,
        "run",
        "detection",
    )
    with sqlite3.connect(ingestion_schema) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        if corruption == "source":
            connection.execute("DELETE FROM source_video WHERE source_id='source'")
        elif corruption == "frame":
            connection.execute(
                "DELETE FROM sampled_frame WHERE source_id='source' AND frame_number=0"
            )
        elif corruption == "detection":
            connection.execute("DELETE FROM detection WHERE detection_id='detection'")
        elif corruption == "run":
            connection.execute(
                "UPDATE animal_crop SET run_id='missing-run' WHERE crop_id='crop'"
            )
        elif corruption == "non_retained":
            connection.execute(
                "UPDATE sampled_frame SET outcome='no_animal' "
                "WHERE source_id='source' AND frame_number=0"
            )
        elif corruption == "not_qualified":
            connection.execute(
                "UPDATE detection SET qualifies=0 WHERE detection_id='detection'"
            )
        else:
            connection.execute(
                "UPDATE animal_crop SET confidence=0.4 WHERE crop_id='crop'"
            )

    with pytest.raises(EmbedValidationError):
        read_manifest_snapshot(ingestion_schema, crop_root)


def test_snapshot_preserves_null_metadata_and_defers_crop_file_errors(
    ingestion_schema: Path, tmp_path: Path
) -> None:
    crop_root = tmp_path / "ingestion-output"
    missing_image = _seed_crop(
        ingestion_schema,
        crop_root,
        "crop-missing",
        "source-missing",
        "d" * 64,
        "run-missing",
        "detection-missing",
    )
    mismatched_image = _seed_crop(
        ingestion_schema,
        crop_root,
        "crop-mismatched",
        "source-mismatched",
        "e" * 64,
        "run-mismatched",
        "detection-mismatched",
        crop_bytes=b"actual bytes",
        recorded_hash="0" * 64,
    )
    missing_image.unlink()
    original_mismatched_bytes = mismatched_image.read_bytes()

    snapshots = read_manifest_snapshot(ingestion_schema, crop_root)

    assert [snapshot.crop_id for snapshot in snapshots] == [
        "crop-mismatched",
        "crop-missing",
    ]
    assert all(snapshot.capture_time is None for snapshot in snapshots)
    assert all(snapshot.capture_timezone is None for snapshot in snapshots)
    assert all(snapshot.source_capture_start is None for snapshot in snapshots)
    assert all(snapshot.source_capture_timezone is None for snapshot in snapshots)
    assert snapshots[0].crop_sha256 == "0" * 64
    assert (
        snapshots[0].crop_sha256
        != hashlib.sha256(mismatched_image.read_bytes()).hexdigest()
    )
    assert not (crop_root / snapshots[1].crop_original_image_path).is_file()
    assert mismatched_image.read_bytes() == original_mismatched_bytes


@pytest.mark.parametrize(
    "relative_path", ("", "../outside.png", "crops/../../outside.png")
)
def test_snapshot_defers_invalid_crop_paths_to_item_resolution(
    ingestion_schema: Path, tmp_path: Path, relative_path: str
) -> None:
    crop_root = tmp_path / "ingestion-output"
    _seed_crop(
        ingestion_schema,
        crop_root,
        "crop",
        "source",
        "3" * 64,
        "run",
        "detection",
    )
    with sqlite3.connect(ingestion_schema) as connection:
        connection.execute(
            "UPDATE animal_crop SET image_path=? WHERE crop_id='crop'",
            (relative_path,),
        )

    snapshot = read_manifest_snapshot(ingestion_schema, crop_root)[0]

    assert snapshot.crop_original_image_path == relative_path
    with pytest.raises(IsolatedCropError):
        resolve_crop_path(crop_root, snapshot.crop_original_image_path)


def test_manifest_relocation_preserves_semantic_provenance(
    ingestion_schema: Path, tmp_path: Path
) -> None:
    original_root = tmp_path / "original-output"
    _seed_crop(
        ingestion_schema,
        original_root,
        "crop",
        "source",
        "f" * 64,
        "run",
        "detection",
        capture_time="2026-03-04T05:06:07",
        source_capture_start="2026-03-04T05:00:00",
    )
    before = read_manifest_snapshot(ingestion_schema, original_root)[0]
    relocated_root = tmp_path / "relocated-output"
    relocated_root.mkdir()
    relocated_database = relocated_root / "manifest.sqlite3"
    shutil.copy2(ingestion_schema, relocated_database)
    shutil.copytree(original_root, relocated_root, dirs_exist_ok=True)

    after = read_manifest_snapshot(relocated_database, relocated_root)[0]

    assert after.snapshot_id == before.snapshot_id
    assert after.provenance_sha256 == before.provenance_sha256
    assert after.crop_original_image_path == before.crop_original_image_path
    relocated_image = resolve_crop_path(relocated_root, after.crop_original_image_path)
    assert relocated_image.is_file()
    assert relocated_root.resolve() in relocated_image.parents


def test_semantic_source_metadata_change_changes_provenance(
    ingestion_schema: Path, tmp_path: Path
) -> None:
    crop_root = tmp_path / "ingestion-output"
    _seed_crop(
        ingestion_schema,
        crop_root,
        "crop",
        "source",
        "1" * 64,
        "run",
        "detection",
        source_capture_start="2026-03-04T05:00:00",
    )
    before = read_manifest_snapshot(ingestion_schema, crop_root)[0]
    with sqlite3.connect(ingestion_schema) as connection:
        connection.execute(
            "UPDATE source_video SET capture_start='2026-03-04T05:01:00' "
            "WHERE source_id='source'"
        )

    after = read_manifest_snapshot(ingestion_schema, crop_root)[0]

    assert after.provenance_sha256 != before.provenance_sha256
    assert after.snapshot_id != before.snapshot_id
    assert after.source_capture_start == "2026-03-04T05:01:00"


def test_processing_timestamp_change_does_not_change_provenance(
    ingestion_schema: Path, tmp_path: Path
) -> None:
    crop_root = tmp_path / "ingestion-output"
    _seed_crop(
        ingestion_schema,
        crop_root,
        "crop",
        "source",
        "2" * 64,
        "run",
        "detection",
    )
    before = read_manifest_snapshot(ingestion_schema, crop_root)[0]
    with sqlite3.connect(ingestion_schema) as connection:
        connection.execute(
            "UPDATE ingestion_run SET started_at='2027-01-01T00:00:00+00:00',"
            "completed_at='2027-01-01T00:01:00+00:00' WHERE run_id='run'"
        )

    after = read_manifest_snapshot(ingestion_schema, crop_root)[0]

    assert after.provenance_sha256 == before.provenance_sha256
    assert after.snapshot_id == before.snapshot_id


@pytest.mark.parametrize("relative_path", ("../outside.png", "crops/../../outside.png"))
def test_crop_path_resolution_rejects_traversal(
    tmp_path: Path, relative_path: str
) -> None:
    with pytest.raises(IsolatedCropError):
        resolve_crop_path(tmp_path, relative_path)


def test_crop_path_resolution_rejects_symlink_escape(tmp_path: Path) -> None:
    crop_root = tmp_path / "crop-root"
    crop_directory = crop_root / "crops"
    crop_directory.mkdir(parents=True)
    outside_image = tmp_path / "outside.png"
    outside_image.write_bytes(b"synthetic crop")
    escaped_image = crop_directory / "escaped.png"
    try:
        escaped_image.symlink_to(outside_image)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    with pytest.raises(IsolatedCropError):
        resolve_crop_path(crop_root, "crops/escaped.png")
