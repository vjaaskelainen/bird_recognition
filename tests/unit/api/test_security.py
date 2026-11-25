from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bird_recognition.api import server
from bird_recognition.api.app import create_app
from bird_recognition.api.security import is_loopback_host, validate_bind
from bird_recognition.api.settings import APISettings


def test_api_key_is_required_for_authenticated_routes(fake_store) -> None:
    settings = APISettings(api_key="secret", database_url="postgresql://local")
    client = TestClient(
        create_app(settings, store_factory=lambda _: fake_store),
    )

    response = client.get("/v1/runs")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "unauthorized"


def test_health_route_is_exempt_and_valid_key_allows_routes(fake_store) -> None:
    fake_store.runs = []
    settings = APISettings(api_key="secret", database_url="postgresql://local")
    client = TestClient(create_app(settings, store_factory=lambda _: fake_store))

    assert client.get("/v1/health").status_code == 200
    assert client.get("/v1/runs", headers={"X-API-Key": "secret"}).status_code == 200


def test_validate_bind_refuses_non_loopback_without_key() -> None:
    try:
        validate_bind(APISettings(host="0.0.0.0"))
    except ValueError as error:
        assert "API_KEY" in str(error)
    else:
        raise AssertionError("non-loopback bind unexpectedly succeeded")


def test_is_loopback_host_distinguishes_local_and_remote_hosts() -> None:
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("example.invalid")


def test_server_refuses_non_loopback_bind_without_key(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "load_settings",
        lambda overrides: APISettings(
            host=overrides["host"],
            port=overrides.get("port", 8000),
        ),
    )

    with pytest.raises(SystemExit, match="2"):
        server.main(["serve", "--host", "0.0.0.0"])


def test_server_runs_with_one_worker(monkeypatch) -> None:
    calls = {}
    settings = APISettings()

    class Uvicorn:
        @staticmethod
        def run(app, **kwargs):
            calls["settings"] = kwargs

    monkeypatch.setattr(server, "load_settings", lambda overrides: settings)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", Uvicorn)

    assert server.main(["serve"]) == 0
    assert calls["settings"]["workers"] == 1
