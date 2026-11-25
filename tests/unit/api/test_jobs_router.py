from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


class FakeJobManager:
    def __init__(self) -> None:
        self.started: list[tuple[str, dict, list[str]]] = []

    def start(self, kind: str, request: dict, command: list[str]) -> dict:
        self.started.append((kind, request, command))
        return {
            "job_id": "9a0be798-6a41-4a2d-a2d2-bf6edbf15000",
            "status": "queued",
        }

    def list(self) -> list[dict]:
        return (
            self.started
            and [
                {
                    "job_id": "9a0be798-6a41-4a2d-a2d2-bf6edbf15000",
                    "status": "queued",
                }
            ]
            or []
        )

    def get(self, job_id):
        if str(job_id) == "9a0be798-6a41-4a2d-a2d2-bf6edbf15000":
            return {"job_id": str(job_id), "status": "queued"}
        return None


def test_ingest_job_returns_202_and_location_without_persisting_paths(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    manager = FakeJobManager()
    client = TestClient(
        create_app(
            APISettings(
                jobs_dir=tmp_path / "jobs",
                allowed_roots=(tmp_path,),
            ),
            job_manager=manager,
        )
    )

    response = client.post(
        "/v1/ingest",
        json={"input_dir": str(input_dir), "output_dir": str(output_dir)},
    )

    assert response.status_code == 202
    assert response.headers["location"].endswith(response.json()["job_id"])
    assert str(tmp_path) not in str(manager.started[0][1])


def test_job_path_outside_allowed_roots_is_refused(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    manager = FakeJobManager()
    client = TestClient(
        create_app(
            APISettings(
                jobs_dir=tmp_path / "jobs",
                allowed_roots=(allowed_root,),
            ),
            job_manager=manager,
        )
    )

    response = client.post(
        "/v1/ingest",
        json={
            "input_dir": str(tmp_path),
            "output_dir": str(allowed_root / "output"),
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "path_not_permitted"


def test_ingest_job_rejects_symlink_escape(tmp_path: Path) -> None:
    allowed_root = tmp_path / "allowed"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir()
    outside_root.mkdir()
    outside_input = outside_root / "input"
    outside_input.mkdir()
    link = allowed_root / "input-link"
    try:
        link.symlink_to(outside_input, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    manager = FakeJobManager()
    client = TestClient(
        create_app(
            APISettings(
                jobs_dir=tmp_path / "jobs",
                allowed_roots=(allowed_root,),
            ),
            job_manager=manager,
        )
    )

    response = client.post(
        "/v1/ingest",
        json={
            "input_dir": str(link),
            "output_dir": str(allowed_root / "output"),
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "path_not_permitted"


def test_jobs_endpoint_requires_configured_storage() -> None:
    client = TestClient(create_app(APISettings()))

    response = client.get("/v1/jobs")

    assert response.status_code == 503
    assert response.json()["code"] == "jobs_not_configured"
