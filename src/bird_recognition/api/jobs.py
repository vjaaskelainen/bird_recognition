"""Atomic, file-backed manager for asynchronous CLI jobs."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import UUID, uuid4


class JobConflictError(RuntimeError):
    """Raised when a conflicting ingestion or indexing job is active."""


class JobManager:
    """Persist sanitized job records and execute one CLI subprocess at a time."""

    def __init__(
        self,
        jobs_dir: Path,
        *,
        runner: Callable[[list[str]], Any] | None = None,
    ) -> None:
        self.jobs_dir = Path(jobs_dir).expanduser().resolve()
        repository_check_path = self.jobs_dir
        while (
            not repository_check_path.exists()
            and repository_check_path != repository_check_path.parent
        ):
            repository_check_path = repository_check_path.parent
        repository = subprocess.run(
            [
                "git",
                "-C",
                str(repository_check_path),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            check=False,
            text=True,
        )
        if repository.returncode == 0:
            raise ValueError("job records must be stored outside the Git repository")
        self.runner = runner or _run_command
        self._lock = Lock()
        self._active_job_id: str | None = None

    def recover(self) -> None:
        """Mark jobs active before a restart as interrupted."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            for path in self.jobs_dir.glob("*.json"):
                record = self._read(path)
                if record.get("status") in {"queued", "running"}:
                    record.update(
                        {
                            "status": "interrupted",
                            "finished_at": _now(),
                            "error": {
                                "code": "interrupted",
                                "message": (
                                    "The server restarted while this job was active."
                                ),
                            },
                        }
                    )
                    self._write(record)

    def start(
        self,
        kind: str,
        request: dict[str, Any],
        command: list[str],
    ) -> dict[str, Any]:
        """Atomically register a job and begin its subprocess in a worker thread."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if self._active_job_id is not None:
                active = self._read(self._path(self._active_job_id))
                if active.get("status") in {"queued", "running"}:
                    raise JobConflictError
                self._active_job_id = None
            job_id = str(uuid4())
            record: dict[str, Any] = {
                "job_id": job_id,
                "kind": kind,
                "status": "queued",
                "created_at": _now(),
                "started_at": None,
                "finished_at": None,
                "exit_code": None,
                "request": request,
                "report": None,
                "error": None,
            }
            self._write(record)
            self._active_job_id = job_id
            Thread(
                target=self._execute,
                args=(job_id, command),
                name=f"bird-recognition-{kind}-{job_id}",
                daemon=True,
            ).start()
            return record

    def list(self) -> list[dict[str, Any]]:
        """Return persisted jobs newest first."""
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            return sorted(
                (self._read(path) for path in self.jobs_dir.glob("*.json")),
                key=lambda item: item["created_at"],
                reverse=True,
            )

    def get(self, job_id: UUID) -> dict[str, Any] | None:
        """Return one job record, if present."""
        path = self._path(str(job_id))
        with self._lock:
            if not path.is_file():
                return None
            return self._read(path)

    def _execute(self, job_id: str, command: list[str]) -> None:
        with self._lock:
            record = self._read(self._path(job_id))
            record.update({"status": "running", "started_at": _now()})
            self._write(record)
        try:
            result = self.runner(command)
            exit_code = int(result.returncode)
            report = _safe_report(result.stdout)
            record.update(
                {
                    "status": (
                        "succeeded"
                        if exit_code == 0
                        else "partial"
                        if exit_code == 2
                        else "failed"
                    ),
                    "exit_code": exit_code,
                    "report": report,
                    "finished_at": _now(),
                }
            )
            if exit_code not in {0, 2}:
                record["error"] = {
                    "code": "job_failed",
                    "message": "The command failed; detailed output is not retained.",
                }
        except Exception:
            record.update(
                {
                    "status": "failed",
                    "finished_at": _now(),
                    "error": {
                        "code": "job_failed",
                        "message": "The command could not be completed.",
                    },
                }
            )
        finally:
            with self._lock:
                self._write(record)
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def _path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    def _write(self, record: dict[str, Any]) -> None:
        path = self._path(record["job_id"])
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{record['job_id']}.", suffix=".tmp", dir=self.jobs_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False, sort_keys=True)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, path)
        finally:
            Path(temporary_name).unlink(missing_ok=True)

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError, UnicodeError, json.JSONDecodeError:
            raise RuntimeError("job record is unreadable or invalid") from None
        if not isinstance(value, dict):
            raise RuntimeError("job record is invalid")
        return value


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _safe_report(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            report = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(report, dict):
            safe: dict[str, Any] = {}
            schema_version = report.get("schema_version")
            if type(schema_version) is int:
                safe["schema_version"] = schema_version
            status = report.get("status")
            if status in {
                "complete",
                "no_input",
                "partial_failure",
                "failed",
                "interrupted",
            }:
                safe["status"] = status
            run_id = report.get("run_id")
            if isinstance(run_id, str):
                try:
                    safe["run_id"] = str(UUID(run_id))
                except ValueError:
                    pass
            counts = report.get("counts")
            if isinstance(counts, dict):
                safe_counts = {
                    key: value
                    for key, value in counts.items()
                    if key
                    in {
                        "selected",
                        "completed",
                        "skipped",
                        "failed",
                        "assigned",
                        "unknown",
                        "pending",
                    }
                    and type(value) is int
                    and value >= 0
                }
                safe["counts"] = safe_counts
            return safe
    counts: dict[str, int] = {}
    status = None
    for line in stdout.splitlines():
        if line.startswith("Run status: "):
            candidate_status = line.partition(": ")[2]
            if candidate_status in {
                "complete",
                "no_input",
                "partial_failure",
                "failed",
            }:
                status = candidate_status
        elif ": " in line:
            name, value = line.partition(": ")[::2]
            count_name = name.casefold().replace(" ", "_")
            if (
                count_name
                in {
                    "processed_sources",
                    "skipped_sources",
                    "failed_sources",
                    "sampled",
                    "person_excluded",
                    "no_animal",
                    "retained",
                    "failed",
                    "crops",
                }
                and value.isdecimal()
            ):
                counts[count_name] = int(value)
    return {"status": status, "counts": counts}


def _now() -> str:
    return datetime.now(UTC).isoformat()
