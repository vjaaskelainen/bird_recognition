from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings
from bird_recognition.review.contact_sheet import (
    ContactSheetService,
    SheetUnavailableError,
)
from bird_recognition.review.playback import PlaybackService
from bird_recognition.review.store import InMemoryReviewStore


def fake_frames(path: Path, times):
    return [Image.new("RGB", (64, 48), "blue") for _ in times]


def attach(client: TestClient, tmp_path: Path, **kwargs) -> None:
    resources = client.app.state.resources
    resources.sheets = ContactSheetService(
        tmp_path / "cache", kwargs.get("frames", fake_frames)
    )
    resources.playback = PlaybackService(
        tmp_path / "cache",
        "ffmpeg",
        resources.get_catalog(),
        runner=kwargs.get("runner", lambda command: (1, "")),
        directly_playable=lambda _: False,
        start_worker=False,
    )


def test_contact_sheet_and_layout(review_env, tmp_path) -> None:
    client, _, _ = review_env
    attach(client, tmp_path)

    response = client.get("/v1/videos/a/contact-sheet")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["x-unfiltered-media"] == "true"
    assert response.headers["cache-control"] == "private, max-age=3600"
    layout = client.get("/v1/videos/a/contact-sheet/layout").json()
    assert layout["tiles"][0]["boxes"][0]["right"] == 0.5
    assert client.get("/v1/videos/zzz/contact-sheet").status_code == 404


def test_source_missing_and_cache_unavailable(review_env, tmp_path) -> None:
    client, _, builder = review_env
    attach(client, tmp_path)
    (builder.input_root / "a.mp4").unlink()
    missing = client.get("/v1/videos/a/contact-sheet")
    assert missing.status_code == 409 and missing.json()["code"] == "source_missing"

    resources = client.app.state.resources
    resources.sheets = None
    resources.settings = replace(resources.settings, cache_dir=None)
    response = client.get("/v1/videos/b/contact-sheet")
    assert response.status_code == 503
    assert response.json()["code"] == "cache_unavailable"


def test_sheet_failure_is_cache_unavailable(review_env, tmp_path) -> None:
    client, _, _ = review_env

    def broken(path, times):
        raise SheetUnavailableError("nope")

    attach(client, tmp_path, frames=broken)
    assert client.get("/v1/videos/a/contact-sheet").status_code == 503


def test_media_requires_key_and_is_disabled_without_one(review_env, tmp_path) -> None:
    client, _, _ = review_env
    attach(client, tmp_path)
    assert (
        client.get("/v1/videos/a/contact-sheet", headers={"X-API-Key": "x"}).status_code
        == 401
    )

    open_app = create_app(
        APISettings(manifest=client.app.state.settings.manifest),
        review_store_factory=lambda _: InMemoryReviewStore(),
    )
    response = TestClient(open_app).get("/v1/videos/a/contact-sheet")
    assert response.status_code == 403
    assert response.json()["code"] == "media_disabled"
