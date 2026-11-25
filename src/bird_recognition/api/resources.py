"""Lazily initialized resources shared across HTTP requests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

from bird_recognition.api.errors import APIError
from bird_recognition.api.settings import APISettings


class APIResources:
    """Cache the read-only database store and model instances for app lifetime."""

    def __init__(
        self,
        settings: APISettings,
        *,
        store_factory: Callable[[str], Any] | None = None,
        model_loader: Callable[[Path, str], Any] | None = None,
        ask_executor: Callable[..., Any] | None = None,
        job_manager: Any = None,
        review_store_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.settings = settings
        self._review_store_factory = review_store_factory
        self._review_store: Any = None
        self._catalog: Any = None
        self.playback: Any = None
        self.sheets: Any = None
        self._store_factory = store_factory
        self._model_loader = model_loader
        self.ask_executor = ask_executor
        self.job_manager = job_manager
        self._store: Any = None
        self._models: dict[str, Any] = {}
        self._lock = Lock()

    def get_store(self) -> Any:
        """Return the single lazily constructed read-only storage facade."""
        if not self.settings.database_url:
            raise APIError(
                503, "database_unavailable", "The database is not configured."
            )
        with self._lock:
            if self._store is None:
                factory = self._store_factory or _default_store_factory
                self._store = factory(self.settings.database_url)
            return self._store

    def get_playback(self) -> Any:
        """Return the playback service, or None when no cache is configured."""
        from bird_recognition.review.playback import PlaybackService

        if self.settings.cache_dir is None:
            return None
        catalog = self.get_catalog()
        with self._lock:
            if self.playback is None:
                self.playback = PlaybackService(
                    self.settings.cache_dir, self.settings.ffmpeg, catalog
                )
            return self.playback

    def get_contact_sheets(self) -> Any:
        """Return the contact sheet service, or None when no cache is configured."""
        from bird_recognition.review.contact_sheet import ContactSheetService

        if self.settings.cache_dir is None:
            return None
        with self._lock:
            if self.sheets is None:
                self.sheets = ContactSheetService(self.settings.cache_dir)
            return self.sheets

    def playback_status(self, video: Any) -> str:
        """Report playback readiness without starting a conversion."""
        if video.source_id is None:
            return "unavailable"
        try:
            playback = self.get_playback()
        except APIError:
            return "unavailable"
        if playback is None:
            return "unavailable"
        return playback.status(video, probe=False)[0]

    def get_review_store(self) -> Any:
        """Return the review persistence store, created on first use."""
        if not self.settings.database_url and self._review_store_factory is None:
            raise APIError(
                503, "database_unavailable", "The database is not configured."
            )
        with self._lock:
            if self._review_store is None:
                factory = self._review_store_factory or _default_review_store_factory
                self._review_store = factory(self.settings.database_url or "")
            return self._review_store

    def get_catalog(self) -> Any:
        """Return the read-only video catalog over the ingestion manifest."""
        from bird_recognition.review.catalog import CurrentSettings, VideoCatalog

        if self.settings.manifest is None:
            raise APIError(
                503, "manifest_unavailable", "The video manifest is not configured."
            )
        with self._lock:
            if self._catalog is None:
                self._catalog = VideoCatalog(
                    self.settings.manifest,
                    current=CurrentSettings(
                        self.settings.interval, self.settings.animal_threshold
                    ),
                    allowed_roots=self.settings.allowed_roots,
                )
            return self._catalog

    def get_model(self, input_view: str) -> Any:
        """Load and cache the configured local embedding model for an input view."""
        if self.settings.model_dir is None:
            raise APIError(
                503, "model_unavailable", "The local model is not configured."
            )
        with self._lock:
            if input_view not in self._models:
                loader = self._model_loader or _default_model_loader
                try:
                    self._models[input_view] = loader(
                        self.settings.model_dir, input_view
                    )
                except Exception:
                    raise APIError(
                        503,
                        "model_unavailable",
                        "The local search model is unavailable.",
                    ) from None
            return self._models[input_view]


def _default_store_factory(database_url: str) -> Any:
    from bird_recognition.embed.storage import PgVectorStore

    return PgVectorStore(database_url)


def _default_review_store_factory(database_url: str) -> Any:
    from bird_recognition.review.store import PgReviewStore

    return PgReviewStore(database_url)


def _default_model_loader(model_dir: Path, input_view: str) -> Any:
    from bird_recognition.embed.bioclip import load_bioclip

    return load_bioclip(model_dir, input_view=input_view)
