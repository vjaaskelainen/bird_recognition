from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


def test_run_list_is_paginated_and_detail_matches_cli_inspection(fake_store) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    fake_store.runs = [
        {"run_id": str(run_id), "status": "complete"},
        {"run_id": "b9e1155d-6a76-49c0-b36f-6f0475f7c2d0", "status": "partial"},
    ]
    fake_store.run_data = {
        "run_id": str(run_id),
        "manifest_locator": "C:\\private\\manifest.sqlite",
        "crop_root": "C:\\private\\crops",
    }
    fake_store.items = [
        {
            "crop_id": "crop-1",
            "status": "completed",
            "provenance": {
                "source_original_path": "C:\\private\\video.mp4",
                "crop_original_image_path": "C:\\private\\crop.jpg",
            },
        }
    ]
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    listing = client.get("/v1/runs?limit=1&offset=1")
    detail = client.get(f"/v1/runs/{run_id}")

    assert listing.json() == {
        "items": [fake_store.runs[1]],
        "limit": 1,
        "offset": 1,
        "total": 2,
    }
    assert detail.status_code == 200
    assert detail.json()["schema_version"] == 1
    assert detail.json()["run"]["manifest_locator"].endswith("manifest.sqlite")


def test_missing_run_returns_problem_details(fake_store) -> None:
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    response = client.get("/v1/runs/9a0be798-6a41-4a2d-a2d2-bf6edbf15000")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
