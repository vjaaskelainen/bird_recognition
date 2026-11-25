from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest


class FakeStore:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []
        self.run_data: dict[str, Any] = {}
        self.items: list[dict[str, Any]] = []
        self.context: Any = None
        self.candidates: tuple[Any, ...] = ()
        self.preflight_error: Exception | None = None

    def preflight(self, *, read_only: bool = False) -> None:
        if self.preflight_error is not None:
            raise self.preflight_error

    def list_runs(self) -> list[dict[str, Any]]:
        return self.runs

    def inspect_run(
        self, run_id: UUID, crop_id: str | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if not self.run_data:
            raise ValueError("run selection was not found")
        if self.run_data and str(self.run_data.get("run_id")) != str(run_id):
            raise ValueError("run selection was not found")
        items = self.items
        if crop_id is not None:
            items = [item for item in items if item.get("crop_id") == crop_id]
            if not items:
                raise ValueError("crop selection was not found in the run")
        return self.run_data, items

    def load_search_collection(self, request: Any) -> tuple[Any, tuple[Any, ...]]:
        return self.context, self.candidates

    def close(self) -> None:
        return None


@pytest.fixture
def fake_store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def review_env(tmp_path):
    """An app with a populated manifest and in-memory review store."""
    from fastapi.testclient import TestClient

    from bird_recognition.api.app import create_app
    from bird_recognition.api.settings import APISettings
    from bird_recognition.review.store import InMemoryReviewStore
    from tests.unit.review.manifest_builder import ManifestBuilder

    builder = ManifestBuilder(tmp_path / "out", tmp_path / "videos")
    builder.run("r1", "2026-01-01T00:00:00")
    builder.video("a", "a.mp4", run_id="r1", crops=1, capture="2026-01-02T00:00:00")
    builder.frame("a", "r1", 0, 0.0, box=(0.1, 0.1, 0.5, 0.5), crop_id="c1")
    (tmp_path / "out" / "crops").mkdir()
    (tmp_path / "out" / "crops" / "c1.jpg").write_bytes(b"jpeg")
    builder.video("b", "b.mp4", run_id="r1", crops=0, capture="2026-01-03T00:00:00")
    builder.frame("b", "r1", 0, 0.0)
    builder.video("c", "c.mp4", run_id="r1", crops=0, capture="2026-01-01T00:00:00")
    builder.video("d", "d.mp4", run_id="r1", status="failed", failure="bad")
    settings = APISettings(
        api_key="secret",
        database_url="postgresql://local",
        manifest=builder.path,
        allowed_roots=(tmp_path,),
        cache_dir=tmp_path / "cache",
    )
    store = InMemoryReviewStore()
    app = create_app(
        settings,
        store_factory=lambda _: None,
        review_store_factory=lambda _: store,
    )
    client = TestClient(app, headers={"X-API-Key": "secret"})
    yield client, store, builder
    builder.close()
