from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from bird_recognition.review.catalog import (
    CurrentSettings,
    ManifestUnavailableError,
    VideoCatalog,
    VideoFilter,
)
from tests.unit.review.manifest_builder import ManifestBuilder


@pytest.fixture
def builder(tmp_path: Path) -> Iterator[ManifestBuilder]:
    value = ManifestBuilder(tmp_path / "out", tmp_path / "videos")
    yield value
    value.close()


def make_catalog(
    builder: ManifestBuilder, tmp_path: Path, **kwargs: object
) -> VideoCatalog:
    return VideoCatalog(
        builder.path, allowed_roots=(tmp_path,), discover=_scan, **kwargs
    )


def _scan(root: Path, extensions: tuple[str, ...]) -> list[Path]:
    return sorted(
        path.resolve() for path in root.rglob("*") if path.suffix in extensions
    )


def test_status_is_derived_for_animals_empty_and_failed_videos(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "animal.mp4", run_id="r1", crops=2)
    builder.video("b", "empty.mp4", run_id="r1", crops=0)
    builder.video("c", "broken.mp4", run_id="r1", status="failed", failure="bad codec")

    items, total = make_catalog(builder, tmp_path).list_videos(VideoFilter())

    by_name = {item.basename: item for item in items}
    assert total == 3
    assert by_name["animal.mp4"].status == "animals"
    assert by_name["animal.mp4"].top_label == "animal"
    assert by_name["empty.mp4"].status == "no_animals"
    assert by_name["empty.mp4"].crop_count == 0
    assert by_name["broken.mp4"].status == "failed"
    assert by_name["broken.mp4"].failure_reason == "bad codec"
    assert by_name["empty.mp4"].path == "videos/empty.mp4"


def test_latest_run_wins_and_skipped_runs_keep_earlier_result(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.run("r2", "2026-01-02T00:00:00")
    builder.run("r3", "2026-01-03T00:00:00")
    builder.video("a", "a.mp4", run_id="r1", crops=0)
    builder.run_source("r2", "a", status="processed", crops=1)
    builder.run_source("r3", "a", status="already_processed")

    items, _ = make_catalog(builder, tmp_path).list_videos(VideoFilter())

    assert items[0].status == "animals"
    assert items[0].run_id == "r2"


def test_running_runs_are_ignored(builder: ManifestBuilder, tmp_path: Path) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.run("r2", "2026-01-02T00:00:00", status="running")
    builder.video("a", "a.mp4", run_id="r1", crops=1)
    builder.run_source("r2", "a", status="processed", crops=0)

    items, _ = make_catalog(builder, tmp_path).list_videos(VideoFilter())

    assert items[0].status == "animals"


def test_settings_drift_compares_with_current_configuration(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00", interval=2.0)
    builder.video("a", "a.mp4", run_id="r1")

    drifted = make_catalog(
        builder, tmp_path, current=CurrentSettings(1.0, 0.2)
    ).list_videos(VideoFilter())[0][0]
    same = make_catalog(
        builder, tmp_path, current=CurrentSettings(2.0, 0.2)
    ).list_videos(VideoFilter())[0][0]

    assert drifted.settings_differ and drifted.interval == 2.0
    assert not same.settings_differ


def test_filters_sort_and_pagination(builder: ManifestBuilder, tmp_path: Path) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "x/a.mp4", run_id="r1", capture="2026-03-01T10:00:00")
    builder.video("b", "x/b.mp4", run_id="r1", crops=1, capture="2026-03-02T10:00:00")
    builder.video("c", "y/c.mp4", run_id="r1", capture="2026-03-03T10:00:00")
    catalog = make_catalog(builder, tmp_path)
    reviews = {"a": "confirmed"}

    unreviewed, total = catalog.list_videos(
        VideoFilter(statuses=("no_animals",), review="unreviewed"), reviews
    )
    in_folder, _ = catalog.list_videos(VideoFilter(folder="videos/x"))
    dated, _ = catalog.list_videos(VideoFilter(date_from="2026-03-02"))
    newest, _ = catalog.list_videos(
        VideoFilter(sort="capture_start", descending=True, limit=1, offset=1)
    )
    by_crops, _ = catalog.list_videos(VideoFilter(sort="crop_count", descending=True))

    assert [item.basename for item in unreviewed] == ["c.mp4"]
    assert total == 1
    assert {item.basename for item in in_folder} == {"a.mp4", "b.mp4"}
    assert {item.basename for item in dated} == {"b.mp4", "c.mp4"}
    assert [item.basename for item in newest] == ["b.mp4"]
    assert by_crops[0].basename == "b.mp4"


def test_not_ingested_videos_are_discovered_and_cached(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.mp4", run_id="r1")
    new_file = tmp_path / "videos" / "new.mp4"
    new_file.write_bytes(b"x")
    now = [0.0]
    catalog = make_catalog(builder, tmp_path, clock=lambda: now[0])

    first, _ = catalog.list_videos(VideoFilter(statuses=("not_ingested",)))
    later = tmp_path / "videos" / "later.mp4"
    later.write_bytes(b"x")
    cached, _ = catalog.list_videos(VideoFilter(statuses=("not_ingested",)))
    now[0] = 120.0
    expired, _ = catalog.list_videos(VideoFilter(statuses=("not_ingested",)))
    refreshed, _ = catalog.list_videos(
        VideoFilter(statuses=("not_ingested",)), refresh=True
    )

    assert [item.basename for item in first] == ["new.mp4"]
    assert first[0].source_id is None and first[0].path_id
    assert [item.basename for item in cached] == ["new.mp4"]
    assert {item.basename for item in expired} == {"new.mp4", "later.mp4"}
    assert len(refreshed) == 2


def test_missing_source_file_is_reported_unavailable(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.mp4", run_id="r1", create_file=False)

    item = make_catalog(builder, tmp_path).get_video("a")

    assert item is not None and not item.source_available


def test_queue_orders_no_animals_first_and_honours_exclusions(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.mp4", run_id="r1", crops=1, capture="2026-01-01T00:00:00")
    builder.video("b", "b.mp4", run_id="r1", capture="2026-02-01T00:00:00")
    builder.video("c", "c.mp4", run_id="r1", capture="2026-01-15T00:00:00")
    builder.video("d", "d.mp4", run_id="r1", status="failed", failure="x")
    catalog = make_catalog(builder, tmp_path)

    queue = catalog.queue({}, exclude=["c"], limit=5)

    assert [item.source_id for item in queue] == ["b", "a"]
    assert catalog.count_unreviewed({"a": "confirmed"}) == 2


def test_frames_boxes_and_crop_paths(builder: ManifestBuilder, tmp_path: Path) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.mp4", run_id="r1", crops=1)
    builder.frame("a", "r1", 0, 0.0)
    builder.frame("a", "r1", 30, 1.0, box=(0.1, 0.1, 0.5, 0.5), crop_id="crop-1")
    crop = tmp_path / "out" / "crops" / "crop-1.jpg"
    crop.parent.mkdir()
    crop.write_bytes(b"jpg")
    catalog = make_catalog(builder, tmp_path)
    video = catalog.get_video("a")
    assert video is not None

    frames = catalog.frames(video)
    crops = catalog.crops(video)

    assert [frame.frame_number for frame in frames] == [0, 30]
    assert frames[1].boxes[0].qualifies and frames[1].boxes[0].category == "animal"
    assert [item.crop_id for item in crops] == ["crop-1"]
    assert catalog.crop_image_path(video, "crop-1") == crop.resolve()
    assert catalog.crop_image_path(video, "missing") is None
    assert catalog.detection_counts(video)["retained"] == 1
    assert catalog.duration_seconds(video) == 1.0


def test_crop_image_outside_output_root_is_refused(
    builder: ManifestBuilder, tmp_path: Path
) -> None:
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.mp4", run_id="r1", crops=1)
    builder.frame("a", "r1", 0, 0.0, box=(0.1, 0.1, 0.5, 0.5), crop_id="crop-1")
    builder.connection.execute(
        "UPDATE animal_crop SET image_path='../outside.jpg' WHERE crop_id='crop-1'"
    )
    builder.connection.commit()
    (tmp_path / "outside.jpg").write_bytes(b"jpg")
    catalog = make_catalog(builder, tmp_path)
    video = catalog.get_video("a")
    assert video is not None

    assert catalog.crop_image_path(video, "crop-1") is None


def test_missing_manifest_is_unavailable(tmp_path: Path) -> None:
    catalog = VideoCatalog(tmp_path / "none" / "manifest.sqlite3")

    assert not catalog.available()
    with pytest.raises(ManifestUnavailableError):
        catalog.list_videos(VideoFilter())
