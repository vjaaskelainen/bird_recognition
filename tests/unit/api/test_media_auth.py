from __future__ import annotations

import pytest

MEDIA_ROUTES = [
    "/v1/videos/a/contact-sheet",
    "/v1/videos/a/contact-sheet/layout",
    "/v1/videos/a/playback",
    "/v1/videos/a/playback/stream",
]


@pytest.mark.parametrize("route", MEDIA_ROUTES)
def test_unfiltered_media_refuses_unauthenticated_requests(review_env, route) -> None:
    client, _, _ = review_env
    client.headers.pop("X-API-Key")

    response = client.get(route)

    assert response.status_code == 401
    assert response.json()["code"] == "unauthorized"
    assert "x-unfiltered-media" not in response.headers
