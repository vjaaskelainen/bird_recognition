import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.ingest import pipeline
from bird_recognition.ingest.manifest import settings_identity, source_identity
from bird_recognition.ingest.models import (
    CaptureTime,
    Detection,
    DetectionCategory,
    IngestSettings,
    SampledFrame,
)
from bird_recognition.ingest.pipeline import run_batch
from tests.ingest.fakes import FakeDetector


def test_source_identity_distinguishes_same_basename_different_paths(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one" / "camera.mp4"
    second = tmp_path / "two" / "camera.mp4"
    assert source_identity(first, "a" * 64) != source_identity(second, "a" * 64)


def test_source_identity_changes_when_content_digest_changes(tmp_path: Path) -> None:
    source = tmp_path / "camera.mp4"
    assert source_identity(source, "a" * 64) != source_identity(source, "b" * 64)


def test_settings_identity_changes_when_effective_settings_change() -> None:
    default_fingerprint = settings_identity(IngestSettings())[1]
    changed_fingerprint = settings_identity(IngestSettings(interval=2.0))[1]
    assert default_fingerprint != changed_fingerprint


def test_settings_identity_changes_when_model_provenance_changes() -> None:
    baseline = IngestSettings(
        model_variant="MDV6-mit-yolov9-c",
        detector_version="pytorchwildlife-1.3.0/MDV6-mit-yolov9-c",
        model_sha256="a" * 64,
        model_config_sha256="b" * 64,
    )
    changed_settings = (
        replace(baseline, model_variant="MDV6-mit-yolov9-e"),
        replace(
            baseline,
            detector_version="pytorchwildlife-1.3.1/MDV6-mit-yolov9-c",
        ),
        replace(baseline, model_sha256="c" * 64),
        replace(baseline, model_config_sha256="d" * 64),
    )
    for changed in changed_settings:
        assert settings_identity(baseline)[1] != settings_identity(changed)[1]


def test_unchanged_rerun_reuses_persisted_outputs_without_detector_calls(
    tiny_video: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / tiny_video.name).write_bytes(tiny_video.read_bytes())
    output_root = tmp_path / "output"
    settings = IngestSettings()
    detections = [Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))]
    first_detector = FakeDetector(detections)
    first_summary, first_report = run_batch(
        input_root, output_root, settings, first_detector
    )
    second_detector = FakeDetector(detections)
    second_summary, second_report = run_batch(
        input_root, output_root, settings, second_detector
    )
    assert first_summary.processed_sources == 1
    assert first_summary.crops == 2
    assert second_summary.skipped_sources == 1
    assert second_summary.sampled_frames == second_summary.crops == 0
    assert second_detector.calls == 0
    assert second_report["status"] == "complete"
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM animal_crop").fetchone() == (2,)
        assert connection.execute(
            "SELECT status FROM run_source WHERE run_id=?",
            (first_report["run_id"],),
        ).fetchone() == ("processed",)
        assert connection.execute(
            "SELECT status FROM run_source WHERE run_id=?",
            (second_report["run_id"],),
        ).fetchone() == ("already_processed",)
    assert len(list((output_root / "crops").rglob("*.jpg"))) == 2


def test_changed_content_and_settings_create_distinct_persisted_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / "camera.mp4"
    source.write_bytes(b"first-content")
    output_root = tmp_path / "output"
    settings = IngestSettings()
    frame = SampledFrame(0, 0.0, 32, 24, Image.new("RGB", (32, 24), "blue"))
    monkeypatch.setattr(
        pipeline, "sample_video", lambda _path, _settings: iter((frame,))
    )
    monkeypatch.setattr(
        pipeline, "capture_start_for_video", lambda _path: CaptureTime()
    )
    detections = [Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))]
    _, first_report = run_batch(
        input_root, output_root, settings, FakeDetector(detections)
    )
    source.write_bytes(b"changed-content")
    _, content_report = run_batch(
        input_root, output_root, settings, FakeDetector(detections)
    )
    _, settings_report = run_batch(
        input_root,
        output_root,
        replace(settings, interval=2.0),
        FakeDetector(detections),
    )
    assert first_report["status"] == "complete"
    assert content_report["status"] == "complete"
    assert settings_report["status"] == "complete"
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        records = connection.execute(
            "SELECT s.content_sha256,c.settings_fingerprint,c.image_path "
            "FROM animal_crop c JOIN source_video s USING(source_id)"
        ).fetchall()
        statuses = dict(
            connection.execute("SELECT run_id,status FROM run_source").fetchall()
        )
    assert len(records) == 3
    assert len({record[0] for record in records}) == 2
    assert len({record[1] for record in records}) == 2
    assert len({record[2] for record in records}) == 3
    assert all((output_root / record[2]).is_file() for record in records)
    assert statuses == {
        first_report["run_id"]: "processed",
        content_report["run_id"]: "processed",
        settings_report["run_id"]: "processed",
    }


def test_same_basename_sources_persist_independent_crops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_root = tmp_path / "input"
    first_source = input_root / "north" / "camera.mp4"
    second_source = input_root / "south" / "camera.mp4"
    first_source.parent.mkdir(parents=True)
    second_source.parent.mkdir(parents=True)
    first_source.write_bytes(b"north")
    second_source.write_bytes(b"south")
    output_root = tmp_path / "output"
    frame = SampledFrame(0, 0.0, 32, 24, Image.new("RGB", (32, 24), "green"))
    monkeypatch.setattr(
        pipeline, "sample_video", lambda _path, _settings: iter((frame,))
    )
    monkeypatch.setattr(
        pipeline, "capture_start_for_video", lambda _path: CaptureTime()
    )
    summary, report = run_batch(
        input_root,
        output_root,
        IngestSettings(),
        FakeDetector([Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))]),
    )
    assert report["status"] == "complete"
    assert summary.processed_sources == 2
    assert summary.crops == 2
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        records = connection.execute(
            "SELECT s.original_path,c.image_path FROM animal_crop c "
            "JOIN source_video s USING(source_id)"
        ).fetchall()
    assert {Path(source_path) for source_path, _ in records} == {
        first_source.resolve(),
        second_source.resolve(),
    }
    assert len({image_path for _, image_path in records}) == 2
    assert all((output_root / image_path).is_file() for _, image_path in records)
