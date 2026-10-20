from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from uuid import UUID

from bird_recognition.embed.models import (
    CropRepresentation,
    EmbeddingModelRecord,
    IngestedCropSnapshot,
    ProcessingRun,
    RunFailure,
    RunItem,
    RunItemStatus,
    Sha256,
    SpeciesDecision,
    StorageError,
    Vector,
)

type FailureHook = Callable[[str], None]


class FakeModel:
    def __init__(
        self,
        identity: EmbeddingModelRecord,
        *,
        image_results: tuple[Vector | Exception, ...] = (),
        text_results: tuple[tuple[Vector, ...] | Exception, ...] = (),
    ) -> None:
        self._identity = identity
        self._image_results = image_results
        self._text_results = text_results
        self.image_calls = 0
        self.text_calls = 0
        self.prompts: list[tuple[str, ...]] = []

    @property
    def identity(self) -> EmbeddingModelRecord:
        return self._identity

    @property
    def inference_count(self) -> int:
        return self.image_calls + self.text_calls

    def encode_image(self, image: object) -> Vector:
        del image
        result = self._result_for_call(self._image_results, self.image_calls)
        self.image_calls += 1
        if isinstance(result, Exception):
            raise result
        if result is not None:
            return result
        return (1.0,) + (0.0,) * (self.identity.dimension - 1)

    def encode_texts(self, prompts: tuple[str, ...]) -> tuple[Vector, ...]:
        self.prompts.append(prompts)
        result = self._result_for_call(self._text_results, self.text_calls)
        self.text_calls += 1
        if isinstance(result, Exception):
            raise result
        if result is not None:
            return result
        return tuple(
            tuple(
                1.0 if coordinate == index % self.identity.dimension else 0.0
                for coordinate in range(self.identity.dimension)
            )
            for index, _ in enumerate(prompts)
        )

    @staticmethod
    def _result_for_call[T](results: tuple[T, ...], call_index: int) -> T | None:
        if call_index < len(results):
            return results[call_index]
        return None


@dataclass(slots=True)
class FakeStoreState:
    runs: dict[UUID, ProcessingRun] = field(default_factory=dict)
    items: dict[tuple[UUID, str], RunItem] = field(default_factory=dict)
    snapshots: dict[Sha256, IngestedCropSnapshot] = field(default_factory=dict)
    representations: dict[UUID, CropRepresentation] = field(default_factory=dict)
    decisions: dict[UUID, SpeciesDecision] = field(default_factory=dict)
    writer_locked: bool = False


class FakeStore:
    def __init__(
        self,
        state: FakeStoreState | None = None,
        failure_hook: FailureHook | None = None,
    ) -> None:
        self.state = state if state is not None else FakeStoreState()
        self.failure_hook = failure_hook

    def preflight(self) -> None:
        self._fail_at("preflight")

    def acquire_writer_lock(self) -> None:
        self._fail_at("acquire_writer_lock")
        if self.state.writer_locked:
            raise StorageError("writer busy")
        self.state.writer_locked = True

    def release_writer_lock(self) -> None:
        self._fail_at("release_writer_lock")
        self.state.writer_locked = False

    def register_run(self, run: ProcessingRun, items: tuple[RunItem, ...]) -> None:
        self._fail_at("before_register_run")
        if run.run_id in self.state.runs:
            raise StorageError("run already exists")
        runs = {**self.state.runs, run.run_id: run}
        registered_items = dict(self.state.items)
        for item in items:
            if item.run_id != run.run_id or item.status is not RunItemStatus.PENDING:
                raise StorageError("run registration requires its pending items")
            key = (item.run_id, item.crop_id)
            if key in registered_items:
                raise StorageError("run item already exists")
            registered_items[key] = item
        self._fail_at("before_register_commit")
        self.state.runs = runs
        self.state.items = registered_items
        self._fail_at("after_register_commit")

    def get_completed_decision(
        self,
        snapshot_id: Sha256,
        model_fingerprint: Sha256,
        config_fingerprint: Sha256,
    ) -> SpeciesDecision | None:
        self._fail_at("get_completed_decision")
        matches = (
            decision
            for decision in self.state.decisions.values()
            if decision.config_fingerprint == config_fingerprint
            and (
                representation := self.state.representations.get(
                    decision.representation_id
                )
            )
            is not None
            and representation.snapshot_id == snapshot_id
            and representation.model_fingerprint == model_fingerprint
        )
        return min(
            matches,
            key=lambda decision: str(decision.decision_id),
            default=None,
        )

    def commit_crop_result(
        self,
        snapshot: IngestedCropSnapshot,
        representation: CropRepresentation,
        decision: SpeciesDecision,
        item: RunItem,
    ) -> None:
        self._fail_at("before_crop_commit")
        if item.status is not RunItemStatus.COMPLETED:
            raise StorageError("crop commit requires a completed run item")
        if item.run_id not in self.state.runs:
            raise StorageError("crop commit references an unknown run")
        key = (item.run_id, item.crop_id)
        pending_item = self.state.items.get(key)
        if pending_item is None or pending_item.status is not RunItemStatus.PENDING:
            raise StorageError("crop commit requires a pending run item")

        snapshots = {**self.state.snapshots, snapshot.snapshot_id: snapshot}
        self._fail_at("after_snapshot_insert")
        representations = {
            **self.state.representations,
            representation.representation_id: representation,
        }
        self._fail_at("after_representation_insert")
        decisions = {**self.state.decisions, decision.decision_id: decision}
        self._fail_at("after_decision_insert")
        items = {**self.state.items, key: item}
        self._fail_at("after_item_insert")

        run = self.state.runs[item.run_id]
        assigned_count = run.assigned_count + (decision.assigned_species_id is not None)
        updated_run = replace(
            run,
            completed_count=run.completed_count + 1,
            assigned_count=assigned_count,
            unknown_count=run.unknown_count + (decision.assigned_species_id is None),
        )
        runs = {**self.state.runs, run.run_id: updated_run}
        self._fail_at("before_crop_commit_publish")
        self.state.snapshots = snapshots
        self.state.representations = representations
        self.state.decisions = decisions
        self.state.items = items
        self.state.runs = runs
        self._fail_at("after_crop_commit")

    def mark_item_failed(self, item: RunItem) -> None:
        self._fail_at("before_mark_item_failed")
        if item.status is not RunItemStatus.FAILED:
            raise StorageError("failed item transition requires a failed item")
        run = self.state.runs.get(item.run_id)
        if run is None:
            raise StorageError("failed item references an unknown run")
        key = (item.run_id, item.crop_id)
        pending_item = self.state.items.get(key)
        if pending_item is None or pending_item.status is not RunItemStatus.PENDING:
            raise StorageError("failed item transition requires a pending run item")
        updated_run = replace(
            run,
            failed_count=run.failed_count + 1,
            failures=run.failures
            + (
                RunFailure(
                    item.crop_id,
                    item.failure_code or "failed",
                    item.failure_reason or "",
                ),
            ),
        )
        self.state.items = {**self.state.items, key: item}
        self.state.runs = {**self.state.runs, run.run_id: updated_run}
        self._fail_at("after_mark_item_failed")

    def finalize_run(self, run: ProcessingRun) -> None:
        self._fail_at("before_finalize_run")
        if run.run_id not in self.state.runs:
            raise StorageError("cannot finalize an unknown run")
        self.state.runs = {**self.state.runs, run.run_id: run}
        self._fail_at("after_finalize_run")

    def _fail_at(self, stage: str) -> None:
        if self.failure_hook is not None:
            self.failure_hook(stage)
