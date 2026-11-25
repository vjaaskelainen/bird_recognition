from __future__ import annotations

from pathlib import Path

from tests.unit.api.test_media_router import attach


def good_runner(command):
    Path(command[-1]).write_bytes(b"0123456789" * 10)
    return 0, ""


def test_playback_states_and_range_streaming(review_env, tmp_path) -> None:
    client, _, _ = review_env
    attach(client, tmp_path, runner=good_runner)

    not_ready = client.get("/v1/videos/a/playback/stream")
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "playback_not_ready"

    first = client.get("/v1/videos/a/playback").json()
    assert first["status"] == "converting" and first["url"] is None
    client.app.state.resources.playback.run_pending()
    ready = client.get("/v1/videos/a/playback").json()
    assert ready["status"] == "ready"

    full = client.get(ready["url"])
    assert full.status_code == 200 and len(full.content) == 100
    assert full.headers["x-unfiltered-media"] == "true"
    part = client.get(ready["url"], headers={"Range": "bytes=10-19"})
    assert part.status_code == 206
    assert part.content == b"0123456789"


def test_failed_and_missing_source(review_env, tmp_path) -> None:
    client, _, builder = review_env
    attach(client, tmp_path)

    client.get("/v1/videos/a/playback")
    client.app.state.resources.playback.run_pending()
    assert client.get("/v1/videos/a/playback").json()["status"] == "failed"
    (builder.input_root / "b.mp4").unlink()
    assert client.get("/v1/videos/b/playback").json()["status"] == "source_missing"
    assert client.get("/v1/videos/zzz/playback").status_code == 404
