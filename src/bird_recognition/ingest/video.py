"""Video discovery, presentation-time sampling, and capture metadata."""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

from bird_recognition.ingest.models import (
    CaptureTime,
    IngestSettings,
    ProcessingError,
    SampledFrame,
    ValidationError,
)

type TimedImage = tuple[int, int | None, Fraction | None, object]


def sample_decoded_frames(
    decoded: Iterable[TimedImage], interval: float
) -> Iterator[SampledFrame]:
    """Select decoded frames at PTS-based elapsed-time targets."""
    if not math.isfinite(interval) or interval <= 0:
        raise ValidationError("sampling interval must be positive and finite")
    first_pts: int | None = None
    first_time_base: Fraction | None = None
    last_elapsed = -1.0
    next_target = 0.0
    emitted = False
    for frame_number, pts, time_base, image in decoded:
        if pts is None or time_base is None or time_base <= 0:
            raise ProcessingError(
                f"sample timing is unavailable at frame {frame_number} (PTS)"
            )
        if first_pts is None:
            first_pts = pts
            first_time_base = time_base
        assert first_time_base is not None
        elapsed = float((pts * time_base) - (first_pts * first_time_base))
        if not math.isfinite(elapsed) or elapsed < 0 or elapsed <= last_elapsed:
            raise ProcessingError(
                f"non-monotonic frame timing at frame {frame_number} (PTS)"
            )
        last_elapsed = elapsed
        if not emitted or elapsed >= next_target:
            width, height = image.size
            yield SampledFrame(frame_number, elapsed, width, height, image)
            emitted = True
            next_target = (math.floor(elapsed / interval) + 1) * interval
    if not emitted:
        raise ProcessingError("video contains no decodable frames")


def iter_video_frames(path: Path) -> Iterator[TimedImage]:
    """Decode frames from a local video once, retaining decoded ordinals and PTS."""
    try:
        import av
    except ImportError as error:
        raise ProcessingError("PyAV is required to decode videos") from error
    try:
        with av.open(str(path), mode="r") as container:
            stream = next(
                (item for item in container.streams if item.type == "video"), None
            )
            if stream is None:
                raise ProcessingError(f"no video stream found: {path}")
            if stream.duration == 0:
                raise ProcessingError(f"video stream has zero duration: {path}")
            for frame_number, frame in enumerate(container.decode(stream)):
                image = frame.to_image().convert("RGB")
                time_base = frame.time_base or stream.time_base
                yield (
                    frame_number,
                    frame.pts,
                    Fraction(time_base) if time_base else None,
                    image,
                )
    except ProcessingError:
        raise
    except Exception as error:
        raise ProcessingError(f"failed to decode video {path}: {error}") from error


def sample_video(path: Path, settings: IngestSettings) -> Iterator[SampledFrame]:
    """Decode a video once and yield its PTS-sampled frames."""
    return sample_decoded_frames(iter_video_frames(path), settings.interval)


def parse_capture_start(metadata: dict[str, str]) -> CaptureTime:
    """Parse recognized capture-start tags, preserving explicit timezone offsets."""
    recognized = {"com.apple.quicktime.creationdate", "camera.capture_start"}
    values = [
        value.strip()
        for key, value in metadata.items()
        if key.rsplit(":", 1)[-1].casefold() in recognized and value.strip()
    ]
    if not values:
        return CaptureTime()
    parsed: list[datetime] = []
    try:
        parsed = [
            datetime.fromisoformat(value.replace("Z", "+00:00")) for value in values
        ]
    except ValueError:
        return CaptureTime()
    normalized = {value.isoformat() for value in parsed}
    if len(normalized) != 1:
        return CaptureTime()
    value = parsed[0]
    if value.tzinfo is None:
        return CaptureTime(value.isoformat(), None)
    offset = value.utcoffset()
    if offset is None:
        return CaptureTime()
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    timezone = f"{sign}{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
    return CaptureTime(value.isoformat(), timezone)


def derive_capture_time(start: CaptureTime, elapsed_seconds: float) -> str | None:
    """Add elapsed PTS seconds to a recognized capture start, if available."""
    if not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
        raise ValidationError("elapsed time must be finite and non-negative")
    if start.local_time is None:
        return None
    try:
        capture = datetime.fromisoformat(start.local_time)
    except ValueError:
        return None
    return (capture + timedelta(seconds=elapsed_seconds)).isoformat()


def capture_start_for_video(path: Path) -> CaptureTime:
    """Read only recognized capture-start metadata from video containers."""
    try:
        import av
    except ImportError as error:
        raise ProcessingError("PyAV is required to read video metadata") from error
    try:
        with av.open(str(path), mode="r") as container:
            metadata = dict(container.metadata)
            for stream_index, stream in enumerate(container.streams):
                if stream.type == "video":
                    metadata.update(
                        {
                            f"stream{stream_index}:{key}": value
                            for key, value in stream.metadata.items()
                        }
                    )
            return parse_capture_start(metadata)
    except Exception as error:
        raise ProcessingError(
            f"failed to read metadata from {path}: {error}"
        ) from error


def discover_videos(root: Path, extensions: tuple[str, ...]) -> tuple[Path, ...]:
    """Find supported videos recursively in canonical path order."""
    normalized = {extension.casefold() for extension in extensions}
    try:
        paths = (
            path.resolve()
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in normalized
        )
        return tuple(sorted(paths, key=lambda path: str(path).casefold()))
    except OSError as error:
        raise ProcessingError(
            f"failed to discover videos under {root}: {error}"
        ) from error
