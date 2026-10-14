"""Crop geometry and all-or-none frame image publication."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from bird_recognition.ingest.models import StorageError, ValidationError


class CroppableImage(Protocol):
    @property
    def size(self) -> tuple[int, int]: ...

    def crop(self, box: tuple[int, int, int, int]) -> CroppableImage: ...

    def save(self, fp: object, format: str) -> None: ...


def normalized_box_to_pixels(
    box: Sequence[float], width: int, height: int
) -> tuple[int, int, int, int]:
    """Clip normalized detector coordinates to an exclusive-edge pixel box."""
    if width <= 0 or height <= 0:
        raise ValidationError("frame dimensions must be positive")
    if len(box) != 4 or any(not math.isfinite(value) for value in box):
        raise ValidationError("box must contain four finite coordinates")
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        raise ValidationError("box must have positive area")
    pixel_box = (
        max(0, min(width, math.floor(left * width))),
        max(0, min(height, math.floor(top * height))),
        max(0, min(width, math.ceil(right * width))),
        max(0, min(height, math.ceil(bottom * height))),
    )
    if pixel_box[2] <= pixel_box[0] or pixel_box[3] <= pixel_box[1]:
        raise ValidationError("box has no positive area inside the frame")
    return pixel_box


def crop_image(
    image: CroppableImage, box: Sequence[float]
) -> tuple[CroppableImage, tuple[int, int, int, int]]:
    """Return a crop and its clipped source-frame pixel coordinates."""
    width, height = image.size
    pixel_box = normalized_box_to_pixels(box, width, height)
    return image.crop(pixel_box), pixel_box


def publish_frame_crops(
    crops: Sequence[tuple[str, CroppableImage]], destination: Path
) -> tuple[Path, ...]:
    """Encode and atomically publish a complete frame crop set."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.staging")
    if staging.exists() or destination.exists():
        raise StorageError(f"crop destination already exists: {destination}")
    staging.mkdir()
    try:
        paths: list[Path] = []
        for name, image in crops:
            if Path(name).name != name or not name:
                raise ValidationError("crop filename must be a simple non-empty name")
            path = staging / f"{name}.jpg"
            image.save(path, format="JPEG")
            if not path.is_file() or path.stat().st_size == 0:
                raise StorageError(f"crop image was not completely written: {name}")
            paths.append(path)
        staging.replace(destination)
        return tuple(destination / path.name for path in paths)
    except Exception as error:
        for path in staging.glob("*") if staging.exists() else ():
            path.unlink(missing_ok=True)
        if staging.exists():
            staging.rmdir()
        if isinstance(error, (StorageError, ValidationError)):
            raise
        raise StorageError("failed to publish complete frame crop set") from error
