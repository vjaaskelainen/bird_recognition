import sqlite3
from contextlib import closing
from pathlib import Path

from bird_recognition.ingest.manifest import Manifest
from bird_recognition.ingest.models import IngestSettings
from bird_recognition.ingest.pipeline import run_batch
from tests.ingest.fakes import FakeDetector


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


def test_batch_recovery_removes_staged_crop_files(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    staging = output_root / "crops" / ".frame.staging"
    staging.mkdir(parents=True)
    (staging / "partial.jpg").write_bytes(b"partial")

    Manifest(output_root).recover()

    assert not staging.exists()


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
