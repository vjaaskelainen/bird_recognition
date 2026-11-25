"""Contact sheets: one image of evenly spaced sampled frames with box layout."""

from __future__ import annotations

import io
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bird_recognition.review.catalog import FrameRecord, VideoRecord

MAX_TILES = 12
COLUMNS = 4
TILE_WIDTH = 320
VERSION = "v1"

FrameSource = Callable[[Path, Sequence[float]], list[Any]]


class SheetUnavailableError(RuntimeError):
    """Raised when frames cannot be read to build the sheet."""


@dataclass(frozen=True, slots=True)
class SheetTile:
    """One tile of the layout."""

    index: int
    frame_number: int
    elapsed_seconds: float
    boxes: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class SheetLayout:
    """Geometry of a rendered sheet."""

    columns: int
    tile_width: int
    tile_height: int
    tiles: tuple[SheetTile, ...]


def select_frames(
    frames: Sequence[FrameRecord], limit: int = MAX_TILES
) -> list[FrameRecord]:
    """Pick at most ``limit`` evenly spaced frames, always keeping order."""
    if len(frames) <= limit:
        return list(frames)
    step = (len(frames) - 1) / (limit - 1)
    indices = sorted({round(index * step) for index in range(limit)})
    return [frames[index] for index in indices]


def cache_name(content_sha256: str, fingerprint: str) -> str:
    """Return the cache file name for a video's sheet."""
    return f"{content_sha256}-{fingerprint}-{MAX_TILES}-{VERSION}.jpg"


def build_layout(frames: Sequence[FrameRecord]) -> SheetLayout:
    """Compute the layout for the selected frames."""
    selected = select_frames(frames)
    if not selected:
        return SheetLayout(COLUMNS, TILE_WIDTH, 0, ())
    first = selected[0]
    tile_height = max(1, round(TILE_WIDTH * first.height / max(first.width, 1)))
    tiles = tuple(
        SheetTile(index, frame.frame_number, frame.elapsed_seconds, frame.boxes)
        for index, frame in enumerate(selected)
    )
    return SheetLayout(COLUMNS, TILE_WIDTH, tile_height, tiles)


def pyav_frame_source(path: Path, times: Sequence[float]) -> list[Any]:
    """Decode the frame at or after each timestamp using PyAV."""
    try:
        import av
    except ImportError as error:
        raise SheetUnavailableError("PyAV is required for contact sheets") from error
    images: list[Any] = []
    try:
        with av.open(str(path), mode="r") as container:
            stream = container.streams.video[0]
            for seconds in times:
                container.seek(int(seconds / stream.time_base), stream=stream)
                chosen = None
                for frame in container.decode(stream):
                    chosen = frame
                    if frame.time is not None and frame.time >= seconds - 1e-3:
                        break
                if chosen is None:
                    raise SheetUnavailableError("a frame could not be decoded")
                images.append(chosen.to_image())
    except SheetUnavailableError:
        raise
    except Exception as error:
        raise SheetUnavailableError("the video could not be read") from error
    return images


def render_sheet(images: Sequence[Any], layout: SheetLayout) -> bytes:
    """Compose tiles into one JPEG; no overlays, boxes come from the layout."""
    from PIL import Image

    rows = -(-len(layout.tiles) // layout.columns)
    sheet = Image.new(
        "RGB", (layout.columns * layout.tile_width, rows * layout.tile_height)
    )
    for tile, image in zip(layout.tiles, images, strict=True):
        resized = image.convert("RGB").resize((layout.tile_width, layout.tile_height))
        column = tile.index % layout.columns
        row = tile.index // layout.columns
        sheet.paste(resized, (column * layout.tile_width, row * layout.tile_height))
    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


class ContactSheetService:
    """Build and cache contact sheets under the cache directory."""

    def __init__(
        self, cache_dir: Path, frame_source: FrameSource = pyav_frame_source
    ) -> None:
        self.directory = Path(cache_dir) / "sheets"
        self._frame_source = frame_source

    def sheet(
        self, video: VideoRecord, frames: Sequence[FrameRecord], source: Path
    ) -> tuple[Path, SheetLayout]:
        """Return the cached sheet path and layout, rendering when missing."""
        layout = build_layout(frames)
        if not layout.tiles or video.content_sha256 is None:
            raise SheetUnavailableError("the video has no sampled frames")
        target = self.directory / cache_name(
            video.content_sha256, video.settings_fingerprint or "none"
        )
        if target.is_file():
            return target, layout
        images = self._frame_source(
            source, [tile.elapsed_seconds for tile in layout.tiles]
        )
        data = render_sheet(images, layout)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
            temporary.write_bytes(data)
            os.replace(temporary, target)
        except OSError as error:
            raise SheetUnavailableError("the cache is not writable") from error
        return target, layout
