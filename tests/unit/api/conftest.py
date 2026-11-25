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
