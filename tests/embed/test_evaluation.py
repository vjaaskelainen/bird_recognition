from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from bird_recognition.embed.evaluation import (
    build_evaluation_report,
    write_evaluation_report,
)
from bird_recognition.embed.models import EmbedValidationError, StorageError

RUN_ID = "00000000-0000-0000-0000-000000000001"


def _run_data() -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "status": "partial_failure",
        "counts": {
            "selected": 6,
            "completed": 4,
            "skipped": 0,
            "failed": 1,
            "pending": 1,
        },
        "model_fingerprint": "1" * 64,
        "candidate_set_fingerprint": "2" * 64,
        "scoring_fingerprint": "3" * 64,
        "config_fingerprint": "4" * 64,
        "threshold": 0.5,
        "candidates": {
            "species": [
                {"id": "bird-a", "name": "Bird A"},
                {"id": "bird-b", "name": "Bird B"},
            ]
        },
    }


def _items() -> list[dict[str, object]]:
    return [
        {
            "crop_id": "day-correct",
            "status": "completed",
            "decision": {"assigned_species_id": "bird-a", "reason": "assigned"},
            "provenance": {"lighting": "day"},
        },
        {
            "crop_id": "day-wrong",
            "status": "skipped",
            "decision": {"assigned_species_id": "bird-b", "reason": "assigned"},
            "provenance": {"lighting": "day"},
        },
        {
            "crop_id": "night-unknown",
            "status": "completed",
            "decision": {"assigned_species_id": "unknown", "reason": "exact_tie"},
            "provenance": {"lighting": "night"},
        },
        {
            "crop_id": "night-outside",
            "status": "completed",
            "decision": {"assigned_species_id": "bird-a", "reason": "assigned"},
            "provenance": {"lighting": "night"},
        },
        {
            "crop_id": "failed",
            "status": "failed",
            "decision": None,
            "failure_code": "crop_read_error",
            "failure_reason": "crop could not be read",
            "lighting": "unknown",
            "provenance": None,
        },
        {
            "crop_id": "pending",
            "status": "pending",
            "decision": None,
            "lighting": "unknown",
            "provenance": None,
        },
    ]


def _labels(
    path: Path, examples: list[dict[str, object]], run_id: str = RUN_ID
) -> Path:
    path.write_text(
        json.dumps({"schema_version": 1, "run_id": run_id, "examples": examples}),
        encoding="utf-8",
    )
    return path


def _example(crop_id: str, expected: str | None, truth_kind: str) -> dict[str, object]:
    return {
        "crop_id": crop_id,
        "expected_species_id": expected,
        "truth_kind": truth_kind,
    }


def test_evaluation_reports_hand_calculated_group_metrics_for_all_outcomes(
    tmp_path: Path,
) -> None:
    labels_path = _labels(
        tmp_path / "labels.json",
        [
            _example("day-correct", "bird-a", "species"),
            _example("day-wrong", "bird-a", "species"),
            _example("night-unknown", "bird-b", "species"),
            _example("night-outside", "mammal", "out_of_list"),
            _example("failed", "bird-a", "species"),
            _example("pending", "bird-b", "species"),
        ],
    )

    report = build_evaluation_report(
        _run_data(), _items(), labels_path, expected_run_id=UUID(RUN_ID)
    )

    assert report["labels_sha256"]
    assert report["unlabeled_run_item_count"] == 0
    assert report["publication_ready"] is False
    assert report["groups"]["day"] == {
        "sample_count": 2,
        "completed_count": 2,
        "correct_count": 1,
        "incorrect_count": 1,
        "unknown_count": 0,
        "failed_count": 0,
        "pending_count": 0,
        "assigned_count": 2,
        "precision": 0.5,
        "assignment_coverage": 1.0,
        "processing_coverage": 1.0,
        "failure_examples": [
            {
                "crop_id": "day-wrong",
                "truth_kind": "species",
                "expected_species_id": "bird-a",
                "assigned_species_id": "bird-b",
                "reason": "incorrect_assignment",
            }
        ],
    }
    assert report["groups"]["night"]["unknown_count"] == 1
    assert report["groups"]["night"]["incorrect_count"] == 1
    assert report["groups"]["night"]["failed_count"] == 0
    assert report["groups"]["night"]["pending_count"] == 0
    assert report["groups"]["unknown"]["sample_count"] == 2
    assert report["groups"]["unknown"]["failed_count"] == 1
    assert report["groups"]["unknown"]["pending_count"] == 1
    assert report["groups"]["unknown"]["precision"] is None
    assert report["groups"]["unknown"]["assignment_coverage"] is None
    assert report["groups"]["unknown"]["processing_coverage"] == 0.0


def test_evaluation_empty_labels_report_unavailable_and_unlabeled(
    tmp_path: Path,
) -> None:
    labels_path = _labels(tmp_path / "labels.json", [])

    report = build_evaluation_report(
        _run_data(), _items(), labels_path, expected_run_id=UUID(RUN_ID)
    )

    assert report["unlabeled_run_item_count"] == 6
    assert all(group["sample_count"] == 0 for group in report["groups"].values())
    assert all(group["precision"] is None for group in report["groups"].values())
    assert report["publication_ready"] is False


def test_evaluation_subset_discloses_unlabeled_items_and_unidentifiable_assignment(
    tmp_path: Path,
) -> None:
    labels_path = _labels(
        tmp_path / "labels.json",
        [_example("day-correct", None, "unidentifiable")],
    )

    report = build_evaluation_report(
        _run_data(), _items(), labels_path, expected_run_id=UUID(RUN_ID)
    )

    assert report["unlabeled_run_item_count"] == 5
    assert report["groups"]["day"]["incorrect_count"] == 1


def test_evaluation_requires_ten_completed_day_and_night_examples_for_readiness(
    tmp_path: Path,
) -> None:
    items: list[dict[str, object]] = []
    examples: list[dict[str, object]] = []
    for lighting in ("day", "night"):
        for index in range(10):
            crop_id = f"{lighting}-{index}"
            items.append(
                {
                    "crop_id": crop_id,
                    "status": "completed",
                    "decision": {
                        "assigned_species_id": "bird-a",
                        "reason": "assigned",
                    },
                    "provenance": {"lighting": lighting},
                }
            )
            examples.append(_example(crop_id, "bird-a", "species"))
    run_data = {
        **_run_data(),
        "counts": {"selected": 20, "completed": 20, "failed": 0, "pending": 0},
    }

    report = build_evaluation_report(
        run_data,
        items,
        _labels(tmp_path / "labels.json", examples),
        expected_run_id=UUID(RUN_ID),
    )

    assert report["publication_ready"] is True
    assert report["groups"]["day"]["completed_count"] == 10
    assert report["groups"]["night"]["completed_count"] == 10


@pytest.mark.parametrize(
    "document",
    [
        '{"schema_version":1,"schema_version":1,"run_id":"'
        + RUN_ID
        + '","examples":[]}',
        '{"schema_version":1,"run_id":"' + RUN_ID + '","examples":[],"extra":true}',
        '{"schema_version":1,"run_id":"'
        + RUN_ID
        + '","examples":[{"crop_id":"day-correct","crop_id":"day-correct",'
        '"expected_species_id":"bird-a","truth_kind":"species"}]}',
        '{"schema_version":1,"run_id":"'
        + RUN_ID
        + '","examples":[{"crop_id":"day-correct","expected_species_id":'
        '"bird-a","truth_kind":"species","extra":1}]}',
    ],
)
def test_evaluation_rejects_duplicate_keys_and_unknown_fields(
    tmp_path: Path, document: str
) -> None:
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(document, encoding="utf-8")

    with pytest.raises(EmbedValidationError):
        build_evaluation_report(
            _run_data(), _items(), labels_path, expected_run_id=UUID(RUN_ID)
        )


@pytest.mark.parametrize(
    "examples",
    [
        [_example("missing", "bird-a", "species")],
        [_example("day-correct", "unknown-bird", "species")],
        [_example("day-correct", "bird-a", "out_of_list")],
        [_example("day-correct", "bird-a", "unidentifiable")],
        [_example("day-correct", None, "species")],
        [_example("day-correct", None, "other")],
        [_example("day-correct", " ", "out_of_list")],
    ],
)
def test_evaluation_rejects_invalid_truth_membership_and_run_items(
    tmp_path: Path, examples: list[dict[str, object]]
) -> None:
    with pytest.raises(EmbedValidationError):
        build_evaluation_report(
            _run_data(),
            _items(),
            _labels(tmp_path / "labels.json", examples),
            expected_run_id=UUID(RUN_ID),
        )


def test_evaluation_rejects_labels_for_different_run(tmp_path: Path) -> None:
    labels_path = _labels(
        tmp_path / "labels.json", [], "00000000-0000-0000-0000-000000000002"
    )

    with pytest.raises(EmbedValidationError):
        build_evaluation_report(
            _run_data(), _items(), labels_path, expected_run_id=UUID(RUN_ID)
        )


def test_evaluation_rejects_duplicate_label_crop_ids(tmp_path: Path) -> None:
    repeated = _example("day-correct", "bird-a", "species")
    labels_path = _labels(tmp_path / "labels.json", [repeated, repeated])

    with pytest.raises(EmbedValidationError):
        build_evaluation_report(
            _run_data(), _items(), labels_path, expected_run_id=UUID(RUN_ID)
        )


def test_evaluation_report_writer_is_external_atomic_and_never_overwrites(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "report.json"
    report = {"schema_version": 1, "run_id": RUN_ID}

    write_evaluation_report(report, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == report
    with pytest.raises(EmbedValidationError):
        write_evaluation_report(report, destination)


def test_evaluation_report_writer_rejects_repository_paths(tmp_path: Path) -> None:
    repository_path = Path(__file__).resolve().parents[2] / "evaluation-report.json"

    with pytest.raises(EmbedValidationError):
        write_evaluation_report({"schema_version": 1}, repository_path)


def test_evaluation_report_writer_cleans_temporary_file_after_atomic_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import bird_recognition.embed.evaluation as evaluation

    destination = tmp_path / "report.json"

    def fail_link(source: Path, target: Path) -> None:
        del source, target
        raise OSError("simulated report finalization error")

    monkeypatch.setattr(evaluation.os, "link", fail_link)

    with pytest.raises(StorageError):
        write_evaluation_report({"schema_version": 1}, destination)

    assert not destination.exists()
    assert list(tmp_path.glob(".evaluation-*.tmp")) == []
