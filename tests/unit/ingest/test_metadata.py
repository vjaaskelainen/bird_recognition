import math
import sqlite3
from pathlib import Path

import pytest

from bird_recognition.ingest.manifest import Manifest
from bird_recognition.ingest.models import (
    CaptureTime,
    Detection,
    DetectionCategory,
    IngestSettings,
    SampledFrame,
    ValidationError,
)


def _seed_manifest_frame(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO ingestion_run "
        "(run_id,started_at,status,input_root,output_root,settings_json,"
        "settings_fingerprint) VALUES ('run','now','running','in','out','{}','set')"
    )
    connection.execute(
        "INSERT INTO source_video VALUES ('source','source.mp4','source.mp4','sha',"
        "NULL,NULL)"
    )
    connection.execute(
        "INSERT INTO sampled_frame VALUES "
        "('source','set',0,0,32,24,NULL,NULL,'unknown','retained',NULL,'run')"
    )
    connection.execute(
        "INSERT INTO detection VALUES "
        "('det','source','set',0,'animal',0.9,0.25,0.25,0.75,0.75,1)"
    )


def _crop_row(
    *,
    detection_id: str = "det",
    box: tuple[int, int, int, int] = (8, 6, 24, 18),
    confidence: float = 0.9,
) -> tuple[object, ...]:
    return (
        "crop",
        "source",
        "set",
        0,
        detection_id,
        "crops/crop.jpg",
        "a" * 64,
        *box,
        32,
        24,
        confidence,
        0.0,
        None,
        None,
        "unknown",
        "run",
    )


def test_settings_identity_validation_rejects_nonfinite_interval() -> None:
    with pytest.raises(ValidationError):
        IngestSettings(interval=math.inf)


@pytest.mark.parametrize("threshold", [-0.1, 1.1, math.nan, math.inf])
def test_settings_validation_rejects_threshold_outside_finite_unit_interval(
    threshold: float,
) -> None:
    with pytest.raises(ValidationError):
        IngestSettings(animal_threshold=threshold)


def test_detection_validation_rejects_invalid_confidence_and_box() -> None:
    with pytest.raises(ValidationError):
        Detection(DetectionCategory.ANIMAL, math.nan, (0.1, 0.1, 0.8, 0.8))
    with pytest.raises(ValidationError):
        Detection(DetectionCategory.ANIMAL, 0.9, (0.8, 0.1, 0.2, 0.8))


def test_sampled_frame_validation_requires_positive_dimensions() -> None:
    with pytest.raises(ValidationError):
        SampledFrame(0, 0.0, 0, 10, object())


def test_settings_record_lighting_evidence_thresholds() -> None:
    settings = IngestSettings()

    assert dict(settings.lighting_settings)["day_min_luma"] == 0.28


def test_settings_default_to_context_crop_and_support_legacy_policy() -> None:
    default_settings = IngestSettings()
    legacy_settings = IngestSettings(crop_policy="legacy-tight-v1")

    assert default_settings.crop_policy == "context-v1"
    assert default_settings.crop_context == 0.1
    assert legacy_settings.crop_policy == "legacy-tight-v1"
    assert legacy_settings.crop_context == 0.0


def test_capture_time_represents_unknown_time_and_timezone_as_null() -> None:
    assert CaptureTime() == CaptureTime(local_time=None, timezone=None)


def test_manifest_enforces_provenance_foreign_keys_and_box_constraints(
    tmp_path: Path,
) -> None:
    manifest = Manifest(tmp_path / "output")
    with sqlite3.connect(manifest.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        _seed_manifest_frame(connection)

        invalid_detections = (
            (
                "bad-confidence",
                "source",
                "set",
                0,
                "animal",
                1.1,
                0.1,
                0.1,
                0.8,
                0.8,
                1,
            ),
            ("bad-box", "source", "set", 0, "animal", 0.9, 0.1, 0.1, 1.1, 0.8, 1),
            ("orphan-frame", "source", "set", 1, "animal", 0.9, 0.1, 0.1, 0.8, 0.8, 1),
        )
        for detection in invalid_detections:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO detection VALUES (?,?,?,?,?,?,?,?,?,?,?)", detection
                )

        invalid_crops = (
            _crop_row(detection_id="missing-detection"),
            _crop_row(box=(8, 6, 33, 18)),
            _crop_row(box=(8, 6, 8, 18)),
            _crop_row(confidence=1.1),
        )
        for crop in invalid_crops:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO animal_crop "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    crop,
                )

        frame = connection.execute(
            "SELECT capture_time,capture_timezone,lighting FROM sampled_frame"
        ).fetchone()

    assert frame == (None, None, "unknown")
