from __future__ import annotations

from pathlib import Path

import pytest

from bird_recognition.review.catalog import VideoCatalog, VideoFilter
from bird_recognition.review.playback import PlaybackService
from tests.unit.review.manifest_builder import ManifestBuilder


@pytest.fixture
def env(tmp_path: Path):
    builder = ManifestBuilder(tmp_path / "out", tmp_path / "videos")
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.avi", run_id="r1")
    builder.video("m", "m.avi", run_id="r1", create_file=False)
    catalog = VideoCatalog(
        builder.path,
        allowed_roots=(tmp_path,),
        discover=lambda root, extensions: [],
    )
    videos, _ = catalog.list_videos(VideoFilter())
    by_name = {item.basename: item for item in videos}
    yield tmp_path, catalog, by_name
    builder.close()


def service(env, runner, *, ffmpeg="ffmpeg", playable=False) -> PlaybackService:
    tmp_path, catalog, _ = env
    return PlaybackService(
        tmp_path / "cache",
        ffmpeg,
        catalog,
        runner=runner,
        directly_playable=lambda _: playable,
        start_worker=False,
    )


def ok_runner(calls):
    def run(command):
        calls.append(list(command))
        Path(command[-1]).write_bytes(b"mp4")
        return 0, ""

    return run


def test_request_is_idempotent_and_converts_once(env) -> None:
    video = env[2]["a.avi"]
    calls: list[list[str]] = []
    playback = service(env, ok_runner(calls))

    assert playback.status(video)[0] == "not_started"
    assert playback.request(video)[0] == "converting"
    assert playback.request(video)[0] == "converting"
    playback.run_pending()

    assert len(calls) == 1
    assert "+faststart" in calls[0] and "-an" in calls[0] and "libx264" in calls[0]
    assert playback.status(video)[0] == "ready"
    assert playback.stream_path(video).name == "sha-a-v1.mp4"
    assert playback.request(video)[0] == "ready"


def test_failure_leaves_marker_and_no_partial_file(env) -> None:
    video = env[2]["a.avi"]
    playback = service(env, lambda command: (1, "secret path stderr"))

    playback.request(video)
    playback.run_pending()

    status, reason = playback.status(video)
    assert status == "failed" and reason == "conversion failed"
    assert playback.stream_path(video) is None
    assert not list((env[0] / "cache" / "playback").glob("*.mp4"))


def test_unavailable_without_ffmpeg_and_missing_source(env) -> None:
    unavailable = service(env, ok_runner([]), ffmpeg=None)
    unavailable._ffmpeg = None
    assert unavailable.status(env[2]["a.avi"])[0] == "unavailable"
    assert unavailable.status(env[2]["m.avi"])[0] == "source_missing"


def test_directly_playable_source_is_streamed_without_copy(env) -> None:
    video = env[2]["a.avi"]
    calls: list[list[str]] = []
    playback = service(env, ok_runner(calls), playable=True)

    assert playback.request(video)[0] == "ready"
    assert playback.stream_path(video) == env[1].source_path(video)
    assert calls == []
