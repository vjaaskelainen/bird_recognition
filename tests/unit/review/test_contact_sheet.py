from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.review.catalog import BoxRecord, FrameRecord
from bird_recognition.review.contact_sheet import (
    ContactSheetService,
    SheetUnavailableError,
    build_layout,
    cache_name,
    select_frames,
)


def frames(count: int) -> list[FrameRecord]:
    box = BoxRecord(0.1, 0.1, 0.5, 0.5, 0.9, "animal", True)
    return [
        FrameRecord(i, float(i), 640, 480, (box,) if i == 0 else ())
        for i in range(count)
    ]


def test_at_most_twelve_evenly_spaced_frames() -> None:
    selected = select_frames(frames(100))
    numbers = [frame.frame_number for frame in selected]
    assert len(numbers) == 12
    assert numbers[0] == 0 and numbers[-1] == 99
    gaps = [b - a for a, b in zip(numbers, numbers[1:], strict=False)]
    assert max(gaps) - min(gaps) <= 1
    assert len(select_frames(frames(5))) == 5


def test_layout_has_normalized_boxes_and_tile_geometry() -> None:
    layout = build_layout(frames(3))
    assert (layout.columns, layout.tile_width, layout.tile_height) == (4, 320, 240)
    assert layout.tiles[0].boxes[0].right == 0.5
    assert build_layout([]).tiles == ()


def test_cache_key() -> None:
    assert cache_name("abc", "fp") == "abc-fp-12-v1.jpg"


def test_sheet_is_rendered_once_and_cached(tmp_path: Path) -> None:
    from bird_recognition.review.catalog import VideoRecord

    calls: list[list[float]] = []

    def source(path: Path, times):
        calls.append(list(times))
        return [Image.new("RGB", (640, 480), "red") for _ in times]

    video = VideoRecord(
        "a",
        "p",
        "p",
        "a.mp4",
        "",
        "",
        None,
        "animals",
        None,
        1,
        None,
        None,
        None,
        None,
        None,
        False,
        "fp",
        "sha",
    )
    service = ContactSheetService(tmp_path / "cache", source)

    path, layout = service.sheet(video, frames(30), tmp_path / "a.mp4")
    again, _ = service.sheet(video, frames(30), tmp_path / "a.mp4")

    assert path == again and path.name == "sha-fp-12-v1.jpg"
    assert len(calls) == 1 and len(calls[0]) == 12
    with Image.open(path) as image:
        assert image.size == (4 * 320, 3 * 240)
    with pytest.raises(SheetUnavailableError):
        service.sheet(video, [], tmp_path / "a.mp4")
