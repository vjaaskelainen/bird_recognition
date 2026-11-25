from __future__ import annotations

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings
from bird_recognition.embed.models import StorageError


def test_health_ready_when_database_preflight_succeeds(fake_store) -> None:
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}


def test_health_reports_database_unavailable(fake_store) -> None:
    fake_store.preflight_error = StorageError("database secret://private")
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "database_unavailable"
    assert "private" not in response.text
