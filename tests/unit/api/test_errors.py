from __future__ import annotations

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.errors import APIError


def test_validation_error_uses_problem_details_and_names_fields() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/search", json={"query": ""})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["type"] == "urn:bird-recognition:error:validation_error"
    assert response.json()["errors"]
    assert "run_id" in {error["field"] for error in response.json()["errors"]}


def test_unhandled_error_is_generic_and_path_free() -> None:
    app = create_app()

    @app.get("/test-internal-error")
    def fail() -> None:
        raise RuntimeError("secret C:\\private\\database-url")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/test-internal-error")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "internal_error"
    assert "private" not in response.text


def test_api_problem_uses_stable_code_and_media_type() -> None:
    app = create_app()

    @app.get("/test-known-error")
    def fail() -> None:
        raise APIError(403, "opt_in_required", "Explicit opt-in is required.")

    response = TestClient(app).get("/test-known-error")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "opt_in_required"
