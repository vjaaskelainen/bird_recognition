from __future__ import annotations

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings
from bird_recognition.review.store import InMemoryReviewStore


def make_client(fake_store, key: str | None = "secret") -> TestClient:
    settings = APISettings(api_key=key, database_url="postgresql://local")
    app = create_app(
        settings,
        store_factory=lambda _: fake_store,
        review_store_factory=lambda _: InMemoryReviewStore(),
    )
    return TestClient(app, base_url="http://testserver")


def test_exchange_sets_hardened_cookie_and_authenticates(fake_store) -> None:
    client = make_client(fake_store)
    assert client.get("/v1/session").status_code == 401

    response = client.post("/v1/session", json={"key": "secret"})

    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/v1/session").status_code == 204
    assert client.get("/v1/runs").status_code == 200


def test_wrong_key_and_missing_key_configuration(fake_store) -> None:
    assert (
        make_client(fake_store).post("/v1/session", json={"key": "no"}).status_code
        == 401
    )
    response = make_client(fake_store, None).post("/v1/session", json={"key": "x"})
    assert response.status_code == 403
    assert response.json()["code"] == "key_not_configured"


def test_logout_revokes_session(fake_store) -> None:
    client = make_client(fake_store)
    client.post("/v1/session", json={"key": "secret"})
    assert client.delete("/v1/session").status_code == 204
    assert client.get("/v1/session").status_code == 401


def test_cookie_requests_must_be_same_origin(fake_store) -> None:
    client = make_client(fake_store)
    client.post("/v1/session", json={"key": "secret"})
    cross = client.post("/v1/search", json={}, headers={"Origin": "http://evil.test"})
    assert cross.status_code == 403
    assert cross.json()["code"] == "bad_origin"
    same = client.post("/v1/search", json={}, headers={"Origin": "http://testserver"})
    assert same.status_code != 403


def test_api_key_header_skips_origin_check(fake_store) -> None:
    client = make_client(fake_store)
    response = client.post("/v1/search", json={}, headers={"X-API-Key": "secret"})
    assert response.status_code != 403
