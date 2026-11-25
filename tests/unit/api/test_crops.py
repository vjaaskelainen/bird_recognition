from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


def test_crop_metadata_matches_inspection_and_image_returns_screened_file(
    tmp_path: Path, fake_store
) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    crop_root = tmp_path / "crops"
    crop_root.mkdir()
    image = crop_root / "bird.jpg"
    image.write_bytes(b"jpeg")
    fake_store.runs = [{"run_id": str(run_id)}]
    fake_store.run_data = {"run_id": str(run_id), "crop_root": str(crop_root)}
    fake_store.items = [
        {
            "crop_id": "crop-1",
            "status": "completed",
            "lighting": "day",
            "decision": {"assigned_species_id": "bird"},
            "provenance": {
                "source_original_path": "C:\\private\\source.mp4",
                "crop_original_image_path": "bird.jpg",
                "frame_number": 12,
            },
        }
    ]
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    details = client.get("/v1/crops/crop-1")
    image_response = client.get("/v1/crops/crop-1/image")

    assert details.status_code == 200
    assert details.json()["items"][0]["provenance"]["source_original_path"].endswith(
        "source.mp4"
    )
    assert details.json()["items"][0]["crop_id"] == "crop-1"
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/jpeg"
    assert image_response.content == b"jpeg"


def test_crop_image_rejects_symlink_or_relative_escape(
    tmp_path: Path, fake_store
) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    crop_root = tmp_path / "crops"
    crop_root.mkdir()
    fake_store.runs = [{"run_id": str(run_id)}]
    fake_store.run_data = {"run_id": str(run_id), "crop_root": str(crop_root)}
    fake_store.items = [
        {
            "crop_id": "crop-1",
            "provenance": {"crop_original_image_path": "../outside.png"},
        }
    ]
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    response = client.get("/v1/crops/crop-1/image")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
