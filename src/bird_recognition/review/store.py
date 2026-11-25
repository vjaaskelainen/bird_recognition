"""Append-only persistence for video reviews and crop corrections."""

from __future__ import annotations

import itertools
import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Any, Protocol

OUTCOMES = ("confirmed", "corrected")
CORRECTION_KINDS = ("no_animal", "animal_missed", "species_present")
TRUTH_KINDS = ("species", "out_of_list", "unidentifiable")
MAX_NOTE_LENGTH = 2000
MAX_BULK = 500


class ReviewValidationError(ValueError):
    """Raised for review or correction input that violates the data model."""


class ReviewNotFoundError(LookupError):
    """Raised when a review or correction does not exist."""


class AlreadyUndoneError(RuntimeError):
    """Raised when a review was already undone."""


class ReviewStorageError(RuntimeError):
    """Raised when the review database cannot be used."""


@dataclass(frozen=True, slots=True)
class ReviewInput:
    """A reviewer decision before persistence."""

    outcome: str
    correction_kind: str | None = None
    species: tuple[str, ...] = ()
    missed_times: tuple[float, ...] = ()
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """A stored review."""

    review_id: str
    source_id: str
    outcome: str
    correction_kind: str | None
    species: tuple[str, ...]
    missed_times: tuple[float, ...]
    note: str | None
    auto_result: dict[str, Any]
    created_at: str
    bulk_id: str | None
    undone: bool = False


@dataclass(frozen=True, slots=True)
class CropCorrectionRecord:
    """A stored crop truth label."""

    correction_id: str
    crop_id: str
    source_id: str
    truth_kind: str
    species_id: str | None
    created_at: str


def validate_review(data: ReviewInput, *, duration: float | None = None) -> None:
    """Enforce the review rules from the data model."""
    if data.outcome not in OUTCOMES:
        raise ReviewValidationError("outcome must be confirmed or corrected")
    if data.note is not None and len(data.note) > MAX_NOTE_LENGTH:
        raise ReviewValidationError("note must be at most 2000 characters")
    if data.outcome == "confirmed":
        if data.correction_kind or data.species or data.missed_times:
            raise ReviewValidationError("a confirmation cannot carry a correction")
        return
    if data.correction_kind not in CORRECTION_KINDS:
        raise ReviewValidationError("a correction needs a valid correction_kind")
    if data.correction_kind == "species_present":
        if not data.species or any(not item.strip() for item in data.species):
            raise ReviewValidationError("species_present needs at least one species")
    elif data.species:
        raise ReviewValidationError("species is only allowed for species_present")
    if data.correction_kind == "animal_missed":
        if not data.missed_times:
            raise ReviewValidationError("animal_missed needs at least one time")
        for seconds in data.missed_times:
            if not math.isfinite(seconds) or seconds < 0:
                raise ReviewValidationError("missed times must be seconds >= 0")
            if duration is not None and seconds > duration:
                raise ReviewValidationError("missed time is beyond the video duration")
    elif data.missed_times:
        raise ReviewValidationError("missed_times is only allowed for animal_missed")


def validate_correction(truth_kind: str, species_id: str | None) -> None:
    """Enforce the crop correction rules from the data model."""
    if truth_kind not in TRUTH_KINDS:
        raise ReviewValidationError("truth_kind is not valid")
    if truth_kind == "species":
        if species_id is None or not species_id.strip():
            raise ReviewValidationError("species truth needs a species_id")
    elif species_id is not None:
        raise ReviewValidationError("species_id is only allowed for species truth")


def review_state(record: ReviewRecord | None) -> str:
    """Map a current review to the list filter value."""
    return "unreviewed" if record is None else record.outcome


class ReviewStore(Protocol):
    """Persistence operations used by the HTTP layer."""

    def add_review(
        self,
        source_id: str,
        data: ReviewInput,
        auto_result: dict[str, Any],
        *,
        bulk_id: str | None = None,
    ) -> ReviewRecord: ...

    def add_bulk(
        self, items: Sequence[tuple[str, dict[str, Any]]]
    ) -> tuple[str, list[ReviewRecord]]: ...

    def history(self, source_id: str) -> list[ReviewRecord]: ...

    def current(self, source_id: str) -> ReviewRecord | None: ...

    def undo(self, review_id: str) -> None: ...

    def review_states(self) -> dict[str, str]: ...

    def set_correction(
        self,
        crop_id: str,
        source_id: str,
        truth_kind: str,
        species_id: str | None,
    ) -> CropCorrectionRecord: ...

    def clear_correction(self, crop_id: str) -> None: ...

    def current_corrections(
        self, source_id: str
    ) -> dict[str, CropCorrectionRecord]: ...

    def close(self) -> None: ...


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class InMemoryReviewStore:
    """Reference implementation with the same semantics as PostgreSQL."""

    _reviews: list[ReviewRecord] = field(default_factory=list)
    _corrections: list[CropCorrectionRecord] = field(default_factory=list)
    _undone_corrections: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)
    _sequence: Iterable[int] = field(default_factory=itertools.count)

    def add_review(
        self,
        source_id: str,
        data: ReviewInput,
        auto_result: dict[str, Any],
        *,
        bulk_id: str | None = None,
    ) -> ReviewRecord:
        validate_review(data)
        record = ReviewRecord(
            review_id=str(uuid.uuid4()),
            source_id=source_id,
            outcome=data.outcome,
            correction_kind=data.correction_kind,
            species=tuple(data.species),
            missed_times=tuple(data.missed_times),
            note=data.note,
            auto_result=dict(auto_result),
            created_at=_now(),
            bulk_id=bulk_id,
        )
        with self._lock:
            self._reviews.append(record)
        return record

    def add_bulk(
        self, items: Sequence[tuple[str, dict[str, Any]]]
    ) -> tuple[str, list[ReviewRecord]]:
        bulk_id = str(uuid.uuid4())
        records = [
            self.add_review(source_id, ReviewInput("confirmed"), auto, bulk_id=bulk_id)
            for source_id, auto in items
        ]
        return bulk_id, records

    def history(self, source_id: str) -> list[ReviewRecord]:
        with self._lock:
            rows = [item for item in self._reviews if item.source_id == source_id]
        return list(reversed(rows))

    def current(self, source_id: str) -> ReviewRecord | None:
        for record in self.history(source_id):
            if not record.undone:
                return record
        return None

    def undo(self, review_id: str) -> None:
        with self._lock:
            for index, record in enumerate(self._reviews):
                if record.review_id == review_id:
                    if record.undone:
                        raise AlreadyUndoneError("the review was already undone")
                    self._reviews[index] = replace(record, undone=True)
                    return
        raise ReviewNotFoundError("the review was not found")

    def review_states(self) -> dict[str, str]:
        states: dict[str, str] = {}
        with self._lock:
            for record in self._reviews:
                if not record.undone:
                    states[record.source_id] = record.outcome
                else:
                    states.setdefault(record.source_id, "")
        return {key: value for key, value in states.items() if value}

    def set_correction(
        self,
        crop_id: str,
        source_id: str,
        truth_kind: str,
        species_id: str | None,
    ) -> CropCorrectionRecord:
        validate_correction(truth_kind, species_id)
        record = CropCorrectionRecord(
            correction_id=str(uuid.uuid4()),
            crop_id=crop_id,
            source_id=source_id,
            truth_kind=truth_kind,
            species_id=species_id,
            created_at=_now(),
        )
        with self._lock:
            self._corrections.append(record)
        return record

    def clear_correction(self, crop_id: str) -> None:
        with self._lock:
            for record in reversed(self._corrections):
                if (
                    record.crop_id == crop_id
                    and record.correction_id not in self._undone_corrections
                ):
                    self._undone_corrections.add(record.correction_id)
                    return
        raise ReviewNotFoundError("the crop has no current correction")

    def current_corrections(self, source_id: str) -> dict[str, CropCorrectionRecord]:
        current: dict[str, CropCorrectionRecord] = {}
        with self._lock:
            for record in self._corrections:
                if record.source_id != source_id:
                    continue
                if record.correction_id in self._undone_corrections:
                    continue
                current[record.crop_id] = record
        return current

    def close(self) -> None:
        return None


class PgReviewStore:
    """PostgreSQL implementation; one short-lived connection per operation."""

    def __init__(self, database_url: str) -> None:
        from bird_recognition.embed.config import validate_local_database_url

        validate_local_database_url(database_url)
        self._database_url = database_url

    def _connect(self) -> Any:
        import psycopg
        from psycopg.rows import dict_row

        try:
            return psycopg.connect(self._database_url, row_factory=dict_row)
        except Exception:
            raise ReviewStorageError("the review database is unavailable") from None

    def add_review(
        self,
        source_id: str,
        data: ReviewInput,
        auto_result: dict[str, Any],
        *,
        bulk_id: str | None = None,
    ) -> ReviewRecord:
        validate_review(data)
        with self._wrap(), self._connect() as connection:
            return self._insert_review(
                connection, source_id, data, auto_result, bulk_id
            )

    def add_bulk(
        self, items: Sequence[tuple[str, dict[str, Any]]]
    ) -> tuple[str, list[ReviewRecord]]:
        bulk_id = str(uuid.uuid4())
        with self._wrap(), self._connect() as connection:
            with connection.transaction():
                records = [
                    self._insert_review(
                        connection,
                        source_id,
                        ReviewInput("confirmed"),
                        auto,
                        bulk_id,
                    )
                    for source_id, auto in items
                ]
        return bulk_id, records

    def history(self, source_id: str) -> list[ReviewRecord]:
        with self._wrap(), self._connect() as connection:
            rows = connection.execute(
                "SELECT r.*, (u.review_id IS NOT NULL) AS undone "
                "FROM bird_embed.video_review r "
                "LEFT JOIN bird_embed.video_review_undo u USING (review_id) "
                "WHERE r.source_id=%s ORDER BY r.created_at DESC, r.review_id",
                (source_id,),
            ).fetchall()
        return [_review_from_row(row) for row in rows]

    def current(self, source_id: str) -> ReviewRecord | None:
        for record in self.history(source_id):
            if not record.undone:
                return record
        return None

    def undo(self, review_id: str) -> None:
        import psycopg

        try:
            parsed = uuid.UUID(review_id)
        except ValueError:
            raise ReviewNotFoundError("the review was not found") from None
        with self._wrap(), self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM bird_embed.video_review WHERE review_id=%s", (parsed,)
            ).fetchone()
            if exists is None:
                raise ReviewNotFoundError("the review was not found")
            try:
                connection.execute(
                    "INSERT INTO bird_embed.video_review_undo (review_id) VALUES (%s)",
                    (parsed,),
                )
            except psycopg.errors.UniqueViolation:
                raise AlreadyUndoneError("the review was already undone") from None

    def review_states(self) -> dict[str, str]:
        with self._wrap(), self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT ON (r.source_id) r.source_id, r.outcome "
                "FROM bird_embed.video_review r "
                "LEFT JOIN bird_embed.video_review_undo u USING (review_id) "
                "WHERE u.review_id IS NULL "
                "ORDER BY r.source_id, r.created_at DESC, r.review_id"
            ).fetchall()
        return {row["source_id"]: row["outcome"] for row in rows}

    def set_correction(
        self,
        crop_id: str,
        source_id: str,
        truth_kind: str,
        species_id: str | None,
    ) -> CropCorrectionRecord:
        validate_correction(truth_kind, species_id)
        with self._wrap(), self._connect() as connection:
            row = connection.execute(
                "INSERT INTO bird_embed.crop_correction "
                "(crop_id,source_id,truth_kind,species_id,created_at) "
                "VALUES (%s,%s,%s,%s,clock_timestamp()) RETURNING *",
                (crop_id, source_id, truth_kind, species_id),
            ).fetchone()
        return _correction_from_row(row)

    def clear_correction(self, crop_id: str) -> None:
        with self._wrap(), self._connect() as connection:
            row = connection.execute(
                "SELECT c.correction_id FROM bird_embed.crop_correction c "
                "LEFT JOIN bird_embed.crop_correction_undo u USING (correction_id) "
                "WHERE c.crop_id=%s AND u.correction_id IS NULL "
                "ORDER BY c.created_at DESC, c.correction_id LIMIT 1",
                (crop_id,),
            ).fetchone()
            if row is None:
                raise ReviewNotFoundError("the crop has no current correction")
            connection.execute(
                "INSERT INTO bird_embed.crop_correction_undo (correction_id) "
                "VALUES (%s)",
                (row["correction_id"],),
            )

    def current_corrections(self, source_id: str) -> dict[str, CropCorrectionRecord]:
        with self._wrap(), self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT ON (c.crop_id) c.* "
                "FROM bird_embed.crop_correction c "
                "LEFT JOIN bird_embed.crop_correction_undo u USING (correction_id) "
                "WHERE c.source_id=%s AND u.correction_id IS NULL "
                "ORDER BY c.crop_id, c.created_at DESC, c.correction_id",
                (source_id,),
            ).fetchall()
        return {row["crop_id"]: _correction_from_row(row) for row in rows}

    def close(self) -> None:
        return None

    @staticmethod
    def _insert_review(
        connection: Any,
        source_id: str,
        data: ReviewInput,
        auto_result: dict[str, Any],
        bulk_id: str | None,
    ) -> ReviewRecord:
        from psycopg.types.json import Jsonb

        row = connection.execute(
            "INSERT INTO bird_embed.video_review (source_id,outcome,"
            "correction_kind,species,missed_times,note,auto_result,bulk_id,"
            "created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,clock_timestamp()) "
            "RETURNING *, false AS undone",
            (
                source_id,
                data.outcome,
                data.correction_kind,
                Jsonb(list(data.species)),
                Jsonb(list(data.missed_times)),
                data.note,
                Jsonb(auto_result),
                uuid.UUID(bulk_id) if bulk_id else None,
            ),
        ).fetchone()
        return _review_from_row(row)

    @staticmethod
    def _wrap() -> _StorageGuard:
        return _StorageGuard()


class _StorageGuard:
    """Translate unexpected database errors into ReviewStorageError."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind: Any, error: Any, trace: Any) -> bool:
        domain = (
            ReviewStorageError,
            ReviewNotFoundError,
            AlreadyUndoneError,
            ReviewValidationError,
        )
        if error is not None and not isinstance(error, domain):
            raise ReviewStorageError("the review database request failed") from None
        return False


def _review_from_row(row: dict[str, Any]) -> ReviewRecord:
    return ReviewRecord(
        review_id=str(row["review_id"]),
        source_id=row["source_id"],
        outcome=row["outcome"],
        correction_kind=row["correction_kind"],
        species=tuple(row["species"]),
        missed_times=tuple(float(item) for item in row["missed_times"]),
        note=row["note"],
        auto_result=dict(row["auto_result"]),
        created_at=row["created_at"].isoformat(),
        bulk_id=str(row["bulk_id"]) if row["bulk_id"] else None,
        undone=bool(row.get("undone", False)),
    )


def _correction_from_row(row: dict[str, Any]) -> CropCorrectionRecord:
    return CropCorrectionRecord(
        correction_id=str(row["correction_id"]),
        crop_id=row["crop_id"],
        source_id=row["source_id"],
        truth_kind=row["truth_kind"],
        species_id=row["species_id"],
        created_at=row["created_at"].isoformat(),
    )
