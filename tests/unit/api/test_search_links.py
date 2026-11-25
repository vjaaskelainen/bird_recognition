from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings

RUN_ID = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")


def search(review_env, fake_store, monkeypatch, manifest: Path | None):
    client, _, builder = review_env
    fake_store.context = SimpleNamespace(
        run_id=RUN_ID,
        model_input_view="fit-pad-v1",
        model_fingerprint="m",
        config_fingerprint="c",
        candidate_set_fingerprint="s",
    )
    result = SimpleNamespace(
        rank=1,
        similarity=0.5,
        crop_id="c1",
        snapshot_id="s",
        representation_id=RUN_ID,
        decision_id=RUN_ID,
        crop_path=Path("c1.jpg"),
        image_status="available",
        capture_time=None,
        capture_source=None,
        lighting="day",
        species_id=None,
        label=None,
        decision_status=None,
        species_confidence=None,
        species_margin=None,
        reasons=(),
        provenance={},
    )
    monkeypatch.setattr(
        "bird_recognition.embed.search.execute_search",
        lambda request, model, store, **kw: SimpleNamespace(
            request=request,
            context=kw["context"],
            returned_count=1,
            warnings=(),
            results=(result,),
        ),
    )
    monkeypatch.setattr(
        "bird_recognition.api.routers.search._search_payload",
        lambda outcome: {
            "schema_version": 1,
            "status": "searched",
            "query": "robin",
            "requested_limit": 5,
            "returned_count": 2,
            "results": [{"crop_id": "c1"}, {"crop_id": "other"}],
            "warnings": [],
        },
    )
    settings = APISettings(
        database_url="postgresql://local", model_dir=Path("m"), manifest=manifest
    )
    app = create_app(
        settings,
        store_factory=lambda _: fake_store,
        model_loader=lambda *_: object(),
    )
    response = TestClient(app).post(
        "/v1/search", json={"run_id": str(RUN_ID), "query": "robin"}
    )
    return response


def test_results_link_to_source_video_and_time(
    review_env, fake_store, monkeypatch
) -> None:
    manifest = review_env[2].path
    response = search(review_env, fake_store, monkeypatch, manifest)

    items = response.json()["results"]
    assert items[0]["source_id"] == "a" and items[0]["elapsed_seconds"] == 0.0
    assert "source_id" not in items[1]


def test_results_unchanged_without_manifest(
    review_env, fake_store, monkeypatch
) -> None:
    response = search(review_env, fake_store, monkeypatch, None)

    assert response.status_code == 200
    assert "source_id" not in response.json()["results"][0]
