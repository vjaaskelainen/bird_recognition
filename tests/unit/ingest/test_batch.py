import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.ingest import crops, pipeline
from bird_recognition.ingest.manifest import Manifest
from bird_recognition.ingest.models import (
    CaptureTime,
    Detection,
    DetectionCategory,
    IngestSettings,
    SampledFrame,
)
from bird_recognition.ingest.pipeline import run_batch
from tests.unit.ingest.fakes import FakeDetector, ScriptedDetector


def test_empty_batch_reports_no_input_and_reconciled_zero_counts(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    summary, report = run_batch(
        input_root, tmp_path / "output", IngestSettings(), FakeDetector()
    )
    assert report["status"] == "no_input"
    assert summary.sampled_frames == 0
    assert summary.failed_frames == 0


def test_unreadable_video_isolated_as_failed_source(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "broken.mp4").write_bytes(b"not a video")
    summary, report = run_batch(
        input_root, tmp_path / "output", IngestSettings(), FakeDetector()
    )
    assert report["status"] == "failed"
    assert summary.failed_sources == 1
    assert summary.sampled_frames == (
        summary.person_excluded_frames
        + summary.no_animal_frames
        + summary.retained_frames
        + summary.failed_frames
    )
    assert report["errors"]


def test_batch_recovery_removes_staged_and_orphan_crop_files(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    staging = output_root / "crops" / ".frame.staging"
    orphan_directory = output_root / "crops" / "orphan-source" / "orphan-settings"
    staging.mkdir(parents=True)
    orphan_directory.mkdir(parents=True)
    (staging / "partial.jpg").write_bytes(b"partial")
    (orphan_directory / "orphan.jpg").write_bytes(b"orphan")
    Manifest(output_root).recover()
    assert not staging.exists()
    assert not orphan_directory.exists()


def test_batch_recovery_marks_interrupted_run_failed(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source")
    manifest = Manifest(output_root)
    run_id, settings_fingerprint = manifest.start_run(tmp_path, IngestSettings())
    source_id = manifest.put_source(source_path, "a" * 64)
    manifest.begin_source(run_id, source_id, settings_fingerprint)
    manifest.recover()
    with closing(sqlite3.connect(manifest.database_path)) as connection:
        assert connection.execute(
            "SELECT status FROM ingestion_run WHERE run_id=?", (run_id,)
        ).fetchone() == ("failed",)
        assert connection.execute(
            "SELECT status,sampled_count,failure_reason FROM run_source WHERE run_id=?",
            (run_id,),
        ).fetchone() == (
            "failed",
            0,
            "previous ingestion run was interrupted",
        )


def test_mixed_batch_reconciles_frame_outcomes_and_keeps_only_safe_crops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "a-broken.mp4").write_bytes(b"not a video")
    (input_root / "b-camera.mp4").write_bytes(b"controlled source")
    (input_root / "c-camera.mp4").write_bytes(b"successful source")
    output_root = tmp_path / "output"
    frames = [
        SampledFrame(index, float(index), 32, 24, Image.new("RGB", (32, 24), "blue"))
        for index in range(4)
    ]
    monkeypatch.setattr(
        pipeline,
        "sample_video",
        lambda path, _settings: (
            (_ for _ in ()).throw(RuntimeError("controlled decode failure"))
            if path.name == "a-broken.mp4"
            else iter(frames if path.name == "b-camera.mp4" else frames[:1])
        ),
    )
    monkeypatch.setattr(
        pipeline, "capture_start_for_video", lambda _path: CaptureTime()
    )
    animal = Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))
    person = Detection(DetectionCategory.PERSON, 0.9, (0.1, 0.1, 0.8, 0.8))
    detector = ScriptedDetector(
        [RuntimeError("controlled detector failure"), [person], [animal], [], [animal]]
    )
    summary, report = run_batch(input_root, output_root, IngestSettings(), detector)
    assert report["status"] == "partial_failure"
    assert summary.processed_sources == 1
    assert summary.failed_sources == 2
    assert summary.sampled_frames == 5
    assert summary.sampled_frames == (
        summary.person_excluded_frames
        + summary.no_animal_frames
        + summary.retained_frames
        + summary.failed_frames
    )
    assert (
        summary.person_excluded_frames,
        summary.no_animal_frames,
        summary.retained_frames,
        summary.failed_frames,
        summary.crops,
    ) == (1, 1, 2, 1, 2)
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        outcomes = connection.execute(
            "SELECT f.frame_number,f.outcome FROM sampled_frame f "
            "JOIN source_video s USING(source_id) ORDER BY s.basename,f.frame_number"
        ).fetchall()
        crops_rows = connection.execute(
            "SELECT f.outcome,c.frame_number,c.image_path FROM animal_crop c "
            "JOIN sampled_frame f USING(source_id,settings_fingerprint,frame_number)"
        ).fetchall()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert outcomes == [
        (0, "failed"),
        (1, "person_excluded"),
        (2, "retained"),
        (3, "no_animal"),
        (0, "retained"),
    ]
    assert len(crops_rows) == 2
    assert {row[0] for row in crops_rows} == {"retained"}
    assert {row[1] for row in crops_rows} == {0, 2}
    assert (output_root / crops_rows[0][2]).is_file()
    assert len(list((output_root / "crops").rglob("*.jpg"))) == 2
    assert foreign_key_errors == []


def test_crop_write_failure_records_failed_frame_without_partial_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "camera.mp4").write_bytes(b"controlled source")
    output_root = tmp_path / "output"
    frames = [
        SampledFrame(index, float(index), 32, 24, Image.new("RGB", (32, 24), "blue"))
        for index in range(2)
    ]
    monkeypatch.setattr(
        pipeline,
        "sample_video",
        lambda path, _settings: (
            (_ for _ in ()).throw(RuntimeError("controlled decode failure"))
            if path.name == "a-broken.mp4"
            else iter(frames if path.name == "b-camera.mp4" else frames[:1])
        ),
    )
    monkeypatch.setattr(
        pipeline, "capture_start_for_video", lambda _path: CaptureTime()
    )
    original_publish = crops.publish_frame_crops

    class WriteThenFail:
        def __init__(self, image: object) -> None:
            self.image = image

        def save(self, fp: object, format: str) -> None:
            self.image.save(fp, format=format)
            raise OSError("controlled crop write failure")

    def fail_during_publish(entries: object, destination: Path) -> tuple[Path, ...]:
        name, image = entries[0]
        return original_publish(((name, WriteThenFail(image)),), destination)

    monkeypatch.setattr(pipeline, "publish_frame_crops", fail_during_publish)
    summary, report = run_batch(
        input_root,
        output_root,
        IngestSettings(),
        FakeDetector([Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))]),
    )
    assert report["status"] == "failed"
    assert summary.failed_sources == 1
    assert summary.failed_frames == summary.sampled_frames == 1
    assert summary.retained_frames == summary.crops == 0
    assert summary.sampled_frames == (
        summary.person_excluded_frames
        + summary.no_animal_frames
        + summary.retained_frames
        + summary.failed_frames
    )
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        outcomes = connection.execute(
            "SELECT outcome,failure_reason FROM sampled_frame"
        ).fetchall()
        crop_count = connection.execute("SELECT COUNT(*) FROM animal_crop").fetchone()[
            0
        ]
    assert len(outcomes) == 1
    assert all(
        outcome == "failed" and "failed to publish complete frame crop set" in reason
        for outcome, reason in outcomes
    )
    assert crop_count == 0
    assert not list((output_root / "crops").rglob("*.jpg"))
    assert not list((output_root / "crops").rglob("*.staging"))


def test_recovery_preserves_committed_crops_and_removes_interrupted_publication(
    tiny_video: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    source_path = input_root / tiny_video.name
    source_path.write_bytes(tiny_video.read_bytes())
    output_root = tmp_path / "output"
    run_batch(
        input_root,
        output_root,
        IngestSettings(),
        FakeDetector([Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))]),
    )
    committed_images = set((output_root / "crops").rglob("*.jpg"))
    manifest = Manifest(output_root)
    interrupted_source = tmp_path / "interrupted.mp4"
    interrupted_source.write_bytes(b"interrupted")
    run_id, settings_fingerprint = manifest.start_run(input_root, IngestSettings())
    source_id = manifest.put_source(interrupted_source, "f" * 64)
    manifest.begin_source(run_id, source_id, settings_fingerprint)
    staging = output_root / "crops" / ".frame-00000001.staging"
    orphan = (
        output_root / "crops" / "orphan-source" / "orphan-settings" / "frame-00000001"
    )
    staging.mkdir(parents=True)
    orphan.mkdir(parents=True)
    (staging / "partial.jpg").write_bytes(b"partial")
    (orphan / "orphan.jpg").write_bytes(b"orphan")
    manifest.recover()
    assert set((output_root / "crops").rglob("*.jpg")) == committed_images
    assert not staging.exists()
    assert not orphan.exists()
    with closing(sqlite3.connect(manifest.database_path)) as connection:
        assert connection.execute(
            "SELECT status FROM ingestion_run WHERE run_id=?", (run_id,)
        ).fetchone() == ("failed",)
