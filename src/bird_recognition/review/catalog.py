"""Read-only video catalog derived from the ingestion SQLite manifest."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_EXTENSIONS = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mpeg", ".mpg")
DISCOVERY_TTL_SECONDS = 60.0
STATUSES = ("not_ingested", "failed", "no_animals", "animals")
SORT_KEYS = ("capture_start", "basename", "ingested_at", "crop_count")


class ManifestUnavailableError(RuntimeError):
    """Raised when the ingestion manifest cannot be read."""


@dataclass(frozen=True, slots=True)
class CurrentSettings:
    """Effective ingestion settings used to detect settings drift."""

    interval: float = 1.0
    animal_threshold: float = 0.2


@dataclass(frozen=True, slots=True)
class VideoRecord:
    """One video with its derived processing status."""

    source_id: str | None
    path_id: str
    path: str
    basename: str
    folder: str
    original_path: str
    capture_start: str | None
    status: str
    failure_reason: str | None
    crop_count: int
    top_label: str | None
    run_id: str | None
    ingested_at: str | None
    interval: float | None
    animal_threshold: float | None
    settings_differ: bool
    settings_fingerprint: str | None
    content_sha256: str | None
    review_state: str = "unreviewed"
    source_available: bool = True


@dataclass(frozen=True, slots=True)
class CropRecord:
    """A privacy-screened crop recorded for a video."""

    crop_id: str
    frame_number: int
    elapsed_seconds: float
    confidence: float
    lighting: str
    image_path: str


@dataclass(frozen=True, slots=True)
class BoxRecord:
    """A normalized detection box."""

    left: float
    top: float
    right: float
    bottom: float
    confidence: float
    category: str
    qualifies: bool


@dataclass(frozen=True, slots=True)
class FrameRecord:
    """A sampled frame with its detections."""

    frame_number: int
    elapsed_seconds: float
    width: int
    height: int
    boxes: tuple[BoxRecord, ...]


@dataclass(frozen=True, slots=True)
class VideoFilter:
    """Listing filters, sorting and paging."""

    statuses: tuple[str, ...] = ()
    review: str | None = None
    folder: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    sort: str = "capture_start"
    descending: bool = False
    limit: int = 50
    offset: int = 0


def path_identity(relative_path: str) -> str:
    """Return an opaque identifier for an allowed-root-relative path."""
    normalized = relative_path.replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


class VideoCatalog:
    """Query the manifest read-only; never modifies the manifest or source files."""

    def __init__(
        self,
        manifest_path: Path,
        *,
        current: CurrentSettings | None = None,
        allowed_roots: Sequence[Path] = (),
        extensions: Sequence[str] = DEFAULT_EXTENSIONS,
        discover: Callable[[Path, tuple[str, ...]], Iterable[Path]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.output_root = self.manifest_path.parent.resolve()
        self.current = current or CurrentSettings()
        self.allowed_roots = tuple(Path(root).resolve() for root in allowed_roots)
        self.extensions = tuple(extensions)
        self._discover = discover or _default_discover
        self._clock = clock
        self._discovery: tuple[float, list[Path]] | None = None

    def available(self) -> bool:
        """Report whether the manifest can be opened and has the expected tables."""
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1 FROM run_source LIMIT 1")
        except ManifestUnavailableError, sqlite3.Error:
            return False
        return True

    def list_videos(
        self,
        filters: VideoFilter,
        reviews: Mapping[str, str] | None = None,
        *,
        refresh: bool = False,
    ) -> tuple[list[VideoRecord], int]:
        """Return one filtered, sorted page and the total matching count."""
        records = self._all_records(reviews or {}, refresh=refresh)
        matched = [item for item in records if _matches(item, filters)]
        matched.sort(key=lambda item: _sort_key(item, filters.sort))
        if filters.descending:
            matched = _descending(matched, filters.sort)
        page = matched[filters.offset : filters.offset + filters.limit]
        return [self._with_availability(item) for item in page], len(matched)

    def get_video(
        self, source_id: str, reviews: Mapping[str, str] | None = None
    ) -> VideoRecord | None:
        """Return one ingested video by source id."""
        for item in self._ingested_records(reviews or {}):
            if item.source_id == source_id:
                return self._with_availability(item)
        return None

    def queue(
        self,
        reviews: Mapping[str, str] | None = None,
        *,
        exclude: Iterable[str] = (),
        limit: int = 3,
    ) -> list[VideoRecord]:
        """Return unreviewed videos, no-animal videos first, oldest capture first."""
        skipped = set(exclude)
        candidates = [
            item
            for item in self._ingested_records(reviews or {})
            if item.review_state == "unreviewed"
            and item.status in {"no_animals", "animals"}
            and item.source_id not in skipped
        ]
        candidates.sort(
            key=lambda item: (
                item.status != "no_animals",
                item.capture_start is None,
                item.capture_start or "",
                item.path.casefold(),
            )
        )
        return [self._with_availability(item) for item in candidates[:limit]]

    def count_unreviewed(self, reviews: Mapping[str, str] | None = None) -> int:
        """Count reviewable videos that have no current review."""
        return sum(
            1
            for item in self._ingested_records(reviews or {})
            if item.review_state == "unreviewed"
            and item.status in {"no_animals", "animals"}
        )

    def crops(self, video: VideoRecord) -> list[CropRecord]:
        """List crops recorded by the video's effective run settings."""
        if video.source_id is None or video.settings_fingerprint is None:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT crop_id,frame_number,elapsed_seconds,confidence,lighting,"
                "image_path FROM animal_crop WHERE source_id=? "
                "AND settings_fingerprint=? ORDER BY frame_number,crop_id",
                (video.source_id, video.settings_fingerprint),
            ).fetchall()
        return [
            CropRecord(
                crop_id=row["crop_id"],
                frame_number=row["frame_number"],
                elapsed_seconds=row["elapsed_seconds"],
                confidence=row["confidence"],
                lighting=row["lighting"],
                image_path=row["image_path"],
            )
            for row in rows
        ]

    def detection_counts(self, video: VideoRecord) -> dict[str, int]:
        """Count sampled frames by outcome for the video's effective run."""
        if video.source_id is None or video.settings_fingerprint is None:
            return {}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT outcome,COUNT(*) AS n FROM sampled_frame WHERE source_id=? "
                "AND settings_fingerprint=? GROUP BY outcome",
                (video.source_id, video.settings_fingerprint),
            ).fetchall()
        return {row["outcome"]: row["n"] for row in rows}

    def crop_image_path(self, video: VideoRecord, crop_id: str) -> Path | None:
        """Resolve a crop file under the manifest output root, or None."""
        for crop in self.crops(video):
            if crop.crop_id != crop_id:
                continue
            relative = Path(crop.image_path)
            if relative.is_absolute():
                return None
            try:
                resolved = (self.output_root / relative).resolve(strict=True)
                resolved.relative_to(self.output_root)
            except OSError, ValueError:
                return None
            if not resolved.is_file():
                return None
            if self.allowed_roots and not _inside(resolved, self.allowed_roots):
                return None
            return resolved
        return None

    def frames(self, video: VideoRecord) -> list[FrameRecord]:
        """List sampled frames (excluding failed ones) with their detections."""
        if video.source_id is None or video.settings_fingerprint is None:
            return []
        with self._connect() as connection:
            frame_rows = connection.execute(
                "SELECT frame_number,elapsed_seconds,frame_width,frame_height "
                "FROM sampled_frame WHERE source_id=? AND settings_fingerprint=? "
                "AND outcome<>'failed' ORDER BY frame_number",
                (video.source_id, video.settings_fingerprint),
            ).fetchall()
            box_rows = connection.execute(
                "SELECT frame_number,box_left,box_top,box_right,box_bottom,"
                "confidence,category,qualifies FROM detection WHERE source_id=? "
                "AND settings_fingerprint=? ORDER BY frame_number,detection_id",
                (video.source_id, video.settings_fingerprint),
            ).fetchall()
        boxes: dict[int, list[BoxRecord]] = {}
        for row in box_rows:
            boxes.setdefault(row["frame_number"], []).append(
                BoxRecord(
                    left=row["box_left"],
                    top=row["box_top"],
                    right=row["box_right"],
                    bottom=row["box_bottom"],
                    confidence=row["confidence"],
                    category=row["category"],
                    qualifies=bool(row["qualifies"]),
                )
            )
        return [
            FrameRecord(
                frame_number=row["frame_number"],
                elapsed_seconds=row["elapsed_seconds"],
                width=row["frame_width"],
                height=row["frame_height"],
                boxes=tuple(boxes.get(row["frame_number"], ())),
            )
            for row in frame_rows
        ]

    def crop_locations(self, crop_ids: Sequence[str]) -> dict[str, tuple[str, float]]:
        """Map crop ids to their source video and elapsed seconds."""
        ids = list(dict.fromkeys(crop_ids))
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT crop_id,source_id,elapsed_seconds FROM animal_crop "
                f"WHERE crop_id IN ({marks})",
                ids,
            ).fetchall()
        return {
            row["crop_id"]: (row["source_id"], float(row["elapsed_seconds"]))
            for row in rows
        }

    def duration_seconds(self, video: VideoRecord) -> float | None:
        """Return the last sampled timestamp as a lower bound for the duration."""
        if video.source_id is None or video.settings_fingerprint is None:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT MAX(elapsed_seconds) AS last FROM sampled_frame "
                "WHERE source_id=? AND settings_fingerprint=?",
                (video.source_id, video.settings_fingerprint),
            ).fetchone()
        return None if row is None or row["last"] is None else float(row["last"])

    def source_path(self, video: VideoRecord) -> Path | None:
        """Return the original file when it exists inside the allowed roots."""
        try:
            resolved = Path(video.original_path).resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_file():
            return None
        if self.allowed_roots and not _inside(resolved, self.allowed_roots):
            return None
        return resolved

    def _connect(self) -> _Closing:
        try:
            connection = sqlite3.connect(
                f"{self.manifest_path.resolve().as_uri()}?mode=ro", uri=True, timeout=5
            )
        except (sqlite3.Error, OSError) as error:
            raise ManifestUnavailableError("the manifest cannot be opened") from error
        connection.row_factory = sqlite3.Row
        return _Closing(connection)

    def _with_availability(self, record: VideoRecord) -> VideoRecord:
        path = Path(record.original_path)
        try:
            available = path.is_file() and (
                not self.allowed_roots or _inside(path.resolve(), self.allowed_roots)
            )
        except OSError:
            available = False
        return replace(record, source_available=available)

    def _all_records(
        self, reviews: Mapping[str, str], *, refresh: bool
    ) -> list[VideoRecord]:
        records = self._ingested_records(reviews)
        known = {os.path.normcase(item.original_path) for item in records}
        for path in self._discovered(refresh=refresh):
            if os.path.normcase(str(path)) in known:
                continue
            relative = self._relative(path, None)
            records.append(
                VideoRecord(
                    source_id=None,
                    path_id=path_identity(relative),
                    path=relative,
                    basename=path.name,
                    folder=_folder(relative),
                    original_path=str(path),
                    capture_start=None,
                    status="not_ingested",
                    failure_reason=None,
                    crop_count=0,
                    top_label=None,
                    run_id=None,
                    ingested_at=None,
                    interval=None,
                    animal_threshold=None,
                    settings_differ=False,
                    settings_fingerprint=None,
                    content_sha256=None,
                )
            )
        return records

    def _ingested_records(self, reviews: Mapping[str, str]) -> list[VideoRecord]:
        query = (
            "WITH latest AS ("
            " SELECT rs.source_id,rs.settings_fingerprint,rs.status,"
            "  rs.failure_reason,rs.crop_count,r.run_id,r.started_at,"
            "  r.completed_at,r.settings_json,r.input_root,"
            "  ROW_NUMBER() OVER (PARTITION BY rs.source_id "
            "   ORDER BY r.started_at DESC, r.rowid DESC) AS rn"
            " FROM run_source rs JOIN ingestion_run r ON r.run_id=rs.run_id"
            " WHERE rs.status IN ('processed','failed') AND r.status<>'running'"
            ") SELECT sv.source_id,sv.original_path,sv.basename,sv.content_sha256,"
            "sv.capture_start,l.settings_fingerprint,l.status,l.failure_reason,"
            "l.crop_count,l.run_id,l.started_at,l.completed_at,l.settings_json,"
            "l.input_root FROM source_video sv "
            "JOIN latest l ON l.source_id=sv.source_id AND l.rn=1"
        )
        try:
            with self._connect() as connection:
                rows = connection.execute(query).fetchall()
        except sqlite3.Error as error:
            raise ManifestUnavailableError("the manifest cannot be read") from error
        records: list[VideoRecord] = []
        for row in rows:
            settings = _settings(row["settings_json"])
            interval = _number(settings.get("interval"))
            threshold = _number(settings.get("animal_threshold"))
            if row["status"] == "failed":
                status = "failed"
            elif row["crop_count"] > 0:
                status = "animals"
            else:
                status = "no_animals"
            relative = self._relative(
                Path(row["original_path"]), Path(row["input_root"])
            )
            records.append(
                VideoRecord(
                    source_id=row["source_id"],
                    path_id=path_identity(relative),
                    path=relative,
                    basename=row["basename"],
                    folder=_folder(relative),
                    original_path=row["original_path"],
                    capture_start=row["capture_start"],
                    status=status,
                    failure_reason=row["failure_reason"],
                    crop_count=row["crop_count"],
                    top_label="animal" if row["crop_count"] > 0 else None,
                    run_id=row["run_id"],
                    ingested_at=row["completed_at"] or row["started_at"],
                    interval=interval,
                    animal_threshold=threshold,
                    settings_differ=_differs(interval, threshold, self.current),
                    settings_fingerprint=row["settings_fingerprint"],
                    content_sha256=row["content_sha256"],
                    review_state=reviews.get(row["source_id"], "unreviewed"),
                )
            )
        return records

    def _relative(self, path: Path, fallback_root: Path | None) -> str:
        roots = list(self.allowed_roots)
        if fallback_root is not None:
            roots.append(fallback_root)
        for root in roots:
            try:
                return path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError, OSError:
                continue
        return path.name

    def _discovered(self, *, refresh: bool) -> list[Path]:
        now = self._clock()
        if (
            not refresh
            and self._discovery is not None
            and now - self._discovery[0] < DISCOVERY_TTL_SECONDS
        ):
            return self._discovery[1]
        roots: set[Path] = set()
        try:
            with self._connect() as connection:
                for row in connection.execute(
                    "SELECT DISTINCT input_root FROM ingestion_run"
                ):
                    roots.add(Path(row["input_root"]))
        except sqlite3.Error, ManifestUnavailableError:
            return []
        found: list[Path] = []
        for root in sorted(roots):
            if not root.is_dir():
                continue
            if self.allowed_roots and not _inside(root.resolve(), self.allowed_roots):
                continue
            try:
                found.extend(self._discover(root, self.extensions))
            except OSError:
                continue
        self._discovery = (now, found)
        return found


class _Closing:
    """Context manager that closes the SQLite connection on exit."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self._connection

    def __exit__(self, *exc: object) -> None:
        self._connection.close()


def _default_discover(root: Path, extensions: tuple[str, ...]) -> Iterable[Path]:
    from bird_recognition.ingest.video import discover_videos

    return discover_videos(root, extensions)


def _matches(item: VideoRecord, filters: VideoFilter) -> bool:
    if filters.statuses and item.status not in filters.statuses:
        return False
    if filters.review is not None and item.review_state != filters.review:
        return False
    if filters.folder:
        prefix = filters.folder.strip("/").casefold()
        folder = item.folder.casefold()
        if prefix and folder != prefix and not folder.startswith(prefix + "/"):
            return False
    if filters.date_from or filters.date_to:
        if item.capture_start is None:
            return False
        day = item.capture_start[:10]
        if filters.date_from and day < filters.date_from:
            return False
        if filters.date_to and day > filters.date_to:
            return False
    return True


def _sort_key(item: VideoRecord, sort: str) -> tuple[Any, ...]:
    tie = (item.path.casefold(), item.source_id or "")
    if sort == "basename":
        return (item.basename.casefold(), *tie)
    if sort == "ingested_at":
        return (item.ingested_at is None, item.ingested_at or "", *tie)
    if sort == "crop_count":
        return (item.status == "not_ingested", item.crop_count, *tie)
    return (item.capture_start is None, item.capture_start or "", *tie)


def _descending(items: list[VideoRecord], sort: str) -> list[VideoRecord]:
    """Reverse the order but keep records without a sort value last."""
    if sort in {"capture_start", "ingested_at"}:
        missing = [item for item in items if getattr(item, sort) is None]
        present = [item for item in items if getattr(item, sort) is not None]
        return present[::-1] + missing
    if sort == "crop_count":
        missing = [item for item in items if item.status == "not_ingested"]
        present = [item for item in items if item.status != "not_ingested"]
        return present[::-1] + missing
    return items[::-1]


def _settings(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except TypeError, ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _differs(
    interval: float | None, threshold: float | None, current: CurrentSettings
) -> bool:
    if interval is not None and abs(interval - current.interval) > 1e-9:
        return True
    return threshold is not None and abs(threshold - current.animal_threshold) > 1e-9


def _folder(relative: str) -> str:
    return relative.rsplit("/", 1)[0] if "/" in relative else ""


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    for root in roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        return True
    return False
