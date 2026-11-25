"""Browser playback copies of unfiltered source videos, converted one at a time."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from bird_recognition.review.catalog import VideoCatalog, VideoRecord

VERSION = "v1"
CONVERSION_TIMEOUT_SECONDS = 3600

Runner = Callable[[Sequence[str]], tuple[int, str]]


def subprocess_runner(command: Sequence[str]) -> tuple[int, str]:
    """Run ffmpeg without a shell and return its status and stderr tail."""
    try:
        completed = subprocess.run(  # noqa: S603
            list(command),
            capture_output=True,
            text=True,
            timeout=CONVERSION_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 1, "conversion timed out"
    except OSError as error:
        return 1, f"ffmpeg could not start: {error.strerror or 'error'}"
    return completed.returncode, completed.stderr[-300:]


def probe_directly_playable(path: Path) -> bool:
    """Report whether a browser can play the file as is (H.264 in MP4)."""
    if path.suffix.casefold() not in {".mp4", ".m4v"}:
        return False
    try:
        import av

        with av.open(str(path), mode="r") as container:
            streams = container.streams.video
            return bool(streams) and streams[0].codec_context.name == "h264"
    except Exception:
        return False


class PlaybackService:
    """Cache playback copies; a single worker converts one video at a time."""

    def __init__(
        self,
        cache_dir: Path,
        ffmpeg: str | None,
        catalog: VideoCatalog,
        *,
        runner: Runner = subprocess_runner,
        directly_playable: Callable[[Path], bool] = probe_directly_playable,
        start_worker: bool = True,
    ) -> None:
        self.directory = Path(cache_dir) / "playback"
        self._ffmpeg = ffmpeg if ffmpeg is not None else shutil.which("ffmpeg")
        self._catalog = catalog
        self._runner = runner
        self._directly_playable = directly_playable
        self._queue: queue.Queue[tuple[str, Path, Path]] = queue.Queue()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._start_worker = start_worker

    def _paths(self, video: VideoRecord) -> tuple[Path, Path]:
        base = self.directory / f"{video.content_sha256}-{VERSION}"
        return base.with_suffix(".mp4"), base.with_suffix(".failed")

    def status(
        self, video: VideoRecord, *, probe: bool = True
    ) -> tuple[str, str | None]:
        """Return the playback status and an optional short reason."""
        source = self._catalog.source_path(video)
        if source is None or video.content_sha256 is None:
            return "source_missing", None
        target, marker = self._paths(video)
        if target.is_file():
            return "ready", None
        if probe and self._directly_playable(source):
            return "ready", None
        with self._lock:
            if video.content_sha256 in self._pending:
                return "converting", None
        if marker.is_file():
            return "failed", marker.read_text(encoding="utf-8", errors="replace")
        if self._ffmpeg is None:
            return "unavailable", "ffmpeg is not configured"
        return "not_started", None

    def request(self, video: VideoRecord) -> tuple[str, str | None]:
        """Enqueue a conversion if needed (idempotent) and return the status."""
        status, reason = self.status(video)
        if status != "not_started":
            return status, reason
        source = self._catalog.source_path(video)
        assert source is not None and video.content_sha256 is not None
        target, _ = self._paths(video)
        with self._lock:
            if video.content_sha256 in self._pending:
                return "converting", None
            self._pending.add(video.content_sha256)
        self._queue.put((video.content_sha256, source, target))
        self._ensure_worker()
        return "converting", None

    def stream_path(self, video: VideoRecord) -> Path | None:
        """Return the file to stream, or None when not ready."""
        status, _ = self.status(video)
        if status != "ready":
            return None
        target, _ = self._paths(video)
        if target.is_file():
            return target
        return self._catalog.source_path(video)

    def run_pending(self) -> None:
        """Process queued conversions synchronously (used by the worker)."""
        while True:
            try:
                key, source, target = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                self._convert(source, target)
            finally:
                with self._lock:
                    self._pending.discard(key)

    def _convert(self, source: Path, target: Path) -> None:
        marker = target.with_suffix(".failed")
        temporary = target.with_name(f"{target.stem}.partial.mp4")
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            marker.unlink(missing_ok=True)
            code, _ = self._runner(
                [
                    str(self._ffmpeg),
                    "-nostdin",
                    "-y",
                    "-i",
                    str(source),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ]
            )
            if code == 0 and temporary.is_file():
                os.replace(temporary, target)
                return
            marker.write_text("conversion failed", encoding="utf-8")
        except OSError:
            pass
        finally:
            temporary.unlink(missing_ok=True)

    def _work(self) -> None:
        while True:
            self.run_pending()
            with self._lock:
                if self._queue.empty():
                    self._thread = None
                    return

    def _ensure_worker(self) -> None:
        if not self._start_worker:
            return
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._work, name="playback-worker", daemon=True
            )
            self._thread.start()
