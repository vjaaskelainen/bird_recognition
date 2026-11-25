from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from threading import Event

import pytest

from bird_recognition.api.jobs import JobConflictError, JobManager


def test_job_manager_maps_exit_status_and_writes_sanitized_record(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            2,
            stdout='{"schema_version":1,"status":"partial","counts":{"failed":1}}',
            stderr="C:\\private\\failure",
        )

    manager = JobManager(jobs_dir, runner=runner)

    started = manager.start(
        "index",
        {"manifest": "manifest.sqlite"},
        ["bird-recognition", "index"],
    )
    deadline = time.monotonic() + 2
    record = None
    while time.monotonic() < deadline:
        record = manager.get(started["job_id"])
        if record and record["status"] == "partial":
            break
        time.sleep(0.01)

    assert record is not None
    assert record["status"] == "partial"
    assert record["exit_code"] == 2
    assert record["report"]["counts"] == {"failed": 1}
    assert "private" not in json.dumps(record)
    assert not list(jobs_dir.glob("*.tmp"))


@pytest.mark.parametrize(
    ("exit_code", "expected_status"),
    [(0, "succeeded"), (2, "partial"), (1, "failed")],
)
def test_job_manager_maps_exit_codes(
    tmp_path: Path, exit_code: int, expected_status: str
) -> None:
    manager = JobManager(
        tmp_path / str(exit_code),
        runner=lambda command: subprocess.CompletedProcess(
            command, exit_code, stdout="", stderr=""
        ),
    )

    started = manager.start("ingest", {}, ["bird-recognition", "ingest"])
    deadline = time.monotonic() + 2
    record = None
    while time.monotonic() < deadline:
        record = manager.get(started["job_id"])
        if record and record["status"] in {"succeeded", "partial", "failed"}:
            break
        time.sleep(0.01)

    assert record is not None
    assert record["status"] == expected_status


def test_job_manager_rejects_second_active_job(tmp_path: Path) -> None:
    started = Event()
    release = Event()

    def runner(command):
        started.set()
        release.wait(timeout=2)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    manager = JobManager(tmp_path / "jobs", runner=runner)
    manager.start("ingest", {}, ["first"])
    assert started.wait(timeout=1)

    with pytest.raises(JobConflictError):
        manager.start("index", {}, ["second"])

    release.set()


def test_job_manager_recovers_active_records_as_interrupted(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    job_id = "9a0be798-6a41-4a2d-a2d2-bf6edbf15000"
    (jobs_dir / f"{job_id}.json").write_text(
        json.dumps(
            {
                "job_id": job_id,
                "kind": "ingest",
                "status": "running",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    manager = JobManager(jobs_dir)

    manager.recover()

    record = manager.get(job_id)
    assert record is not None
    assert record["status"] == "interrupted"
    assert record["error"]["code"] == "interrupted"
