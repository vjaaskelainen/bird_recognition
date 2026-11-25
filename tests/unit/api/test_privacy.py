from __future__ import annotations

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


def test_no_full_frame_route_is_exposed() -> None:
    paths = set(create_app().openapi()["paths"])

    assert not any("frame" in path.casefold() for path in paths)
    assert "/v1/crops/{crop_id}/image" in paths


def test_failed_api_responses_use_problem_media_type() -> None:
    client = TestClient(create_app(APISettings()))
    responses = (
        client.get("/v1/health"),
        client.get("/v1/crops/missing"),
        client.post("/v1/search", json={"query": ""}),
    )

    assert all(
        response.status_code >= 400
        and response.headers["content-type"].startswith("application/problem+json")
        for response in responses
    )
