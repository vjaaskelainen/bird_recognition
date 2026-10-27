from __future__ import annotations

import json
import math
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from bird_recognition.embed.models import EmbedValidationError
from bird_recognition.embed.visits import (
    VisitGroup,
    VisitGroupManifest,
    build_visit_report,
    load_visit_group_manifest,
    write_visit_report,
)


def _write_groups(path: Path, groups: list[dict[str, object]]) -> Path:
    path.write_text(
        json.dumps({"schema_version": 1, "groups": groups}), encoding="utf-8"
    )
    return path


def _group(
    crop_ids: list[str] | None = None,
    *,
    visit_id: str = "visit-1",
    source_video_id: str = "source-1",
    confident: bool = True,
) -> dict[str, object]:
    return {
        "visit_id": visit_id,
        "source_video_id": source_video_id,
        "crop_ids": crop_ids or ["crop-1", "crop-2"],
        "association_confident": confident,
    }


def _run_data(
    run_id: UUID, *, threshold: float = 0.5, margin: float | None = None
) -> dict[str, object]:
    config: dict[str, object] = {"minimum_margin": margin}
    candidates = [
        {"id": "a", "name": "A"},
        {"id": "b", "name": "B"},
    ]
    return {
        "run_id": str(run_id),
        "status": "complete",
        "config_fingerprint": "1" * 64,
        "model_fingerprint": "2" * 64,
        "candidate_set_fingerprint": "3" * 64,
        "threshold": threshold,
        "config": config,
        "candidates": {"schema_version": 1, "species": candidates},
    }


def _item(
    crop_id: str,
    decision_id: str,
    logits: tuple[float, float],
    *,
    source_id: str = "source-1",
    reason: str = "assigned",
    config_fingerprint: str = "1" * 64,
) -> dict[str, object]:
    maximum = max(logits)
    exponential = tuple(math.exp(value - maximum) for value in logits)
    total = sum(exponential)
    return {
        "crop_id": crop_id,
        "status": "completed",
        "provenance": {"source_id": source_id},
        "decision": {
            "decision_id": decision_id,
            "config_fingerprint": config_fingerprint,
            "reason": reason,
            "candidate_scores": [
                {"id": candidate_id, "logit": logit, "score": score / total}
                for candidate_id, logit, score in zip(
                    ("a", "b"), logits, exponential, strict=True
                )
            ],
        },
    }


def test_load_visit_group_manifest_validates_and_canonicalizes(tmp_path: Path) -> None:
    first = load_visit_group_manifest(
        _write_groups(tmp_path / "groups-a.json", [_group()])
    )
    second = load_visit_group_manifest(
        _write_groups(
            tmp_path / "groups-b.json",
            [_group(["crop-2", "crop-1"])],
        )
    )

    assert first.manifest_fingerprint == second.manifest_fingerprint
    assert first.groups[0].crop_ids == ("crop-1", "crop-2")


@pytest.mark.parametrize(
    "groups",
    [
        [],
        [_group(["crop-1"])],
        [_group(confident=False)],
        [_group(["crop-1", "crop-1"])],
        [_group(), _group(visit_id="visit-2", crop_ids=["crop-2", "crop-3"])],
    ],
)
def test_load_visit_group_manifest_rejects_uncertain_or_invalid_membership(
    tmp_path: Path, groups: list[dict[str, object]]
) -> None:
    path = _write_groups(tmp_path / "invalid-groups.json", groups)

    with pytest.raises(EmbedValidationError):
        load_visit_group_manifest(path)


def test_load_visit_group_manifest_rejects_unknown_fields_and_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    unknown = _write_groups(tmp_path / "unknown.json", [_group()])
    document = json.loads(unknown.read_text(encoding="utf-8"))
    document["extra"] = True
    unknown.write_text(json.dumps(document), encoding="utf-8")
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema_version":1,"schema_version":1,"groups":[]}', encoding="utf-8"
    )

    with pytest.raises(EmbedValidationError):
        load_visit_group_manifest(unknown)
    with pytest.raises(EmbedValidationError):
        load_visit_group_manifest(duplicate)


def test_build_visit_report_averages_logits_and_links_every_crop() -> None:
    run_id = uuid4()
    run_data = _run_data(run_id)
    members = [
        _item("crop-1", "decision-1", (0.2, 0.0)),
        _item("crop-2", "decision-2", (0.0, 0.2)),
    ]
    manifest = VisitGroupManifest(
        "4" * 64,
        (VisitGroup("visit-1", "source-1", ("crop-1", "crop-2")),),
    )

    report = build_visit_report(run_data, members, manifest, expected_run_id=run_id)
    repeated = build_visit_report(run_data, members, manifest, expected_run_id=run_id)

    visit = report["visits"][0]
    assert visit["crop_ids"] == ["crop-1", "crop-2"]
    assert visit["decision_ids"] == ["decision-1", "decision-2"]
    assert visit["reason"] == "exact_tie"
    assert visit["tied_candidate_ids"] == ["a", "b"]
    assert repeated["visits"] == report["visits"]
    assert members[0]["decision"]["reason"] == "assigned"


def test_build_visit_report_reapplies_margin_and_threshold() -> None:
    run_id = uuid4()
    manifest = VisitGroupManifest(
        "4" * 64,
        (VisitGroup("visit-1", "source-1", ("crop-1", "crop-2")),),
    )
    groups = [
        _item("crop-1", "decision-1", (0.2, 0.0)),
        _item("crop-2", "decision-2", (0.2, 0.0)),
    ]

    below_margin = build_visit_report(
        _run_data(run_id, margin=0.1), groups, manifest, expected_run_id=run_id
    )
    below_threshold = build_visit_report(
        _run_data(run_id, threshold=0.9), groups, manifest, expected_run_id=run_id
    )

    assert below_margin["visits"][0]["reason"] == "below_margin"
    assert below_threshold["visits"][0]["reason"] == "below_threshold"
    assert len(below_margin["visits"][0]["candidate_scores"]) == 2


@pytest.mark.parametrize(
    ("members", "match"),
    [
        (
            [
                _item("crop-1", "d1", (1.0, 0.0)),
                _item("crop-2", "d2", (1.0, 0.0), source_id="source-2"),
            ],
            "source video",
        ),
        (
            [
                _item("crop-1", "d1", (1.0, 0.0)),
                _item("crop-2", "d2", (1.0, 0.0), config_fingerprint="9" * 64),
            ],
            "compatible completed",
        ),
        (
            [
                _item("crop-1", "d1", (1.0, 0.0)),
                _item("crop-2", "d2", (1.0, 0.0), reason="low_quality"),
            ],
            "compatible completed",
        ),
    ],
)
def test_build_visit_report_rejects_missing_or_incompatible_member_decisions(
    members: list[dict[str, object]], match: str
) -> None:
    run_id = uuid4()
    groups = VisitGroupManifest(
        "4" * 64,
        (VisitGroup("visit-1", "source-1", ("crop-1", "crop-2")),),
    )

    with pytest.raises(EmbedValidationError, match=match):
        build_visit_report(_run_data(run_id), members, groups, expected_run_id=run_id)


def test_build_visit_report_rejects_one_candidate_when_margin_is_enabled() -> None:
    run_id = uuid4()
    run_data = _run_data(run_id, margin=0.1)
    run_data["candidates"] = {"species": [{"id": "a", "name": "A"}]}
    items = [
        _item("crop-1", "decision-1", (0.2, 0.0)),
        _item("crop-2", "decision-2", (0.2, 0.0)),
    ]
    manifest = VisitGroupManifest(
        "4" * 64,
        (VisitGroup("visit-1", "source-1", ("crop-1", "crop-2")),),
    )

    with pytest.raises(EmbedValidationError, match="at least two candidates"):
        build_visit_report(run_data, items, manifest, expected_run_id=run_id)


def test_write_visit_report_is_atomic_external_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "visit-report.json"

    assert write_visit_report({"schema_version": 1}, path) == path.resolve()
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema_version": 1}
    with pytest.raises(EmbedValidationError, match="already exists"):
        write_visit_report({"schema_version": 1}, path)


def test_write_visit_report_refuses_repository_destination() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    path = repository_root / ".private-visit-test.json"

    with pytest.raises(EmbedValidationError, match="outside every Git repository"):
        write_visit_report({"schema_version": 1}, path)

    assert not path.exists()
