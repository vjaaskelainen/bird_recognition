from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


def test_visits_use_explicit_reviewed_groups(fake_store, monkeypatch) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    fake_store.run_data = {"run_id": str(run_id)}
    manifest = object()
    monkeypatch.setattr(
        "bird_recognition.embed.visits.load_visit_group_manifest",
        lambda path: manifest,
    )
    monkeypatch.setattr(
        "bird_recognition.embed.visits.build_visit_report",
        lambda run, items, groups, *, expected_run_id: {
            "schema_version": 1,
            "run_id": str(expected_run_id),
            "visit_count": 0,
            "visits": [],
        },
    )
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    response = client.get(
        f"/v1/visits?run_id={run_id}&groups=C%3A%5Cprivate%5Cgroups.json"
    )

    assert response.status_code == 200
    assert response.json()["visit_count"] == 0


def test_visits_require_a_reviewed_manifest(fake_store) -> None:
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda _: fake_store,
        )
    )

    response = client.get("/v1/visits?run_id=9a0be798-6a41-4a2d-a2d2-bf6edbf15000")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_selection"
