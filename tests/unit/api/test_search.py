from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


def test_search_returns_shared_cli_payload_and_search_constraints(
    fake_store, monkeypatch
) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    fake_store.context = SimpleNamespace(
        run_id=run_id,
        model_input_view="fit-pad-v1",
        model_fingerprint="model",
        config_fingerprint="config",
        candidate_set_fingerprint="candidates",
    )
    observed = {}

    def execute(request, model, store, *, context, candidates):
        observed["request"] = request
        return SimpleNamespace(
            request=request,
            context=context,
            returned_count=0,
            warnings=("relative relevance only",),
            results=(),
        )

    monkeypatch.setattr("bird_recognition.embed.search.execute_search", execute)
    client = TestClient(
        create_app(
            APISettings(
                database_url="postgresql://local",
                model_dir=Path("model"),
            ),
            store_factory=lambda _: fake_store,
            model_loader=lambda *_: object(),
        )
    )

    response = client.post(
        "/v1/search",
        json={
            "run_id": str(run_id),
            "query": "blue tit",
            "limit": 4,
            "lighting": "day",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "searched"
    assert response.json()["requested_limit"] == 4
    assert response.json()["warnings"] == ["relative relevance only"]
    assert observed["request"].query == "blue tit"
    assert observed["request"].lighting.value == "day"


def test_search_failure_maps_to_stable_database_code(fake_store, monkeypatch) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    fake_store.context = SimpleNamespace(
        run_id=run_id,
        model_input_view="fit-pad-v1",
        model_fingerprint="model",
        config_fingerprint="config",
        candidate_set_fingerprint="candidates",
    )

    def fail(*args, **kwargs):
        raise RuntimeError("database postgres://secret")

    monkeypatch.setattr("bird_recognition.embed.search.execute_search", fail)
    client = TestClient(
        create_app(
            APISettings(
                database_url="postgresql://local",
                model_dir=Path("model"),
            ),
            store_factory=lambda _: fake_store,
            model_loader=lambda *_: object(),
        )
    )

    response = client.post(
        "/v1/search",
        json={"run_id": str(run_id), "query": "owl"},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert "secret" not in response.text
