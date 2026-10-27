from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import pytest

from bird_recognition.embed.config import canonical_json_bytes
from bird_recognition.embed.evaluation import (
    build_comparison_report,
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


def _shared_labels(
    path: Path,
    examples: list[dict[str, object]],
    *,
    role: str = "held_out_evaluation",
) -> Path:
    split_keys = ["source-video-a"]
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "label_role": role,
                "split_mode": "source_video",
                "source_split_keys": split_keys,
                "source_split_sha256": hashlib.sha256(
                    canonical_json_bytes(split_keys)
                ).hexdigest(),
                "examples": examples,
            }
        ),
        encoding="utf-8",
    )
    return path


def _shared_example(
    case_id: str,
    crop_id: str,
    expected: str | None,
    truth_kind: str = "species",
    expected_category: str | None = None,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "reviewed_crop_id": crop_id,
        "truth_kind": truth_kind,
        "expected_taxon_id": expected,
        "expected_category": expected_category,
    }


def _shared_run(run_id: str, candidate_ids: list[dict[str, str]]) -> dict[str, object]:
    return {
        **_run_data(),
        "run_id": run_id,
        "candidates": candidate_ids,
        "config_fingerprint": run_id.replace("-", "0").ljust(64, "0")[:64],
    }


def _shared_item(
    crop_id: str,
    case_id: str,
    assigned: str | None,
    lighting: str,
    *,
    reason: str = "assigned",
    status: str = "completed",
) -> dict[str, object]:
    return {
        "crop_id": crop_id,
        "case_id": case_id,
        "status": status,
        "lighting": lighting,
        "decision": (
            {"assigned_species_id": assigned, "reason": reason}
            if status in {"completed", "skipped"}
            else None
        ),
        "failure_code": "inference_failed" if status == "failed" else None,
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


def test_shared_comparison_pairs_case_ids_across_setup_specific_crop_ids(
    tmp_path: Path,
) -> None:
    baseline_id = RUN_ID
    candidate_id = "00000000-0000-0000-0000-000000000002"
    labels_path = _shared_labels(
        tmp_path / "shared-labels.json",
        [
            _shared_example("case-a", "review-a", "bird-a", expected_category="bird"),
            _shared_example("case-b", "review-b", "bird-b", expected_category="bird"),
            _shared_example("case-c", "review-c", "fox", "out_of_list", "mammal"),
            _shared_example("case-d", "review-d", None, "unusable"),
        ],
    )
    baseline_candidates = [
        {"id": "bird-a", "name": "Bird A"},
        {"id": "bird-b", "name": "Bird B"},
        {"id": "broad_bird", "kind": "category", "category": "bird"},
        {"id": "broad_mammal", "kind": "category", "category": "mammal"},
    ]
    baseline_items = [
        _shared_item("old-a", "case-a", "bird-a", "day"),
        _shared_item("old-b", "case-b", "bird-a", "night"),
        _shared_item("old-c", "case-c", "broad_mammal", "night"),
        _shared_item("old-d", "case-d", "unknown", "unknown"),
    ]
    candidate_items = [
        _shared_item("new-a", "case-a", "bird-a", "day"),
        _shared_item("new-b", "case-b", "bird-b", "night"),
        _shared_item("new-c", "case-c", "unknown", "night", reason="below_threshold"),
        _shared_item("new-d", "case-d", "unknown", "unknown"),
    ]

    report = build_comparison_report(
        [
            (_shared_run(baseline_id, baseline_candidates), baseline_items),
            (_shared_run(candidate_id, baseline_candidates), candidate_items),
        ],
        labels_path,
        expected_run_ids=[UUID(baseline_id), UUID(candidate_id)],
    )

    assert report["paired_case_count"] == 4
    assert report["setups"][0]["matched_crop_ids"]["case-b"] == "old-b"
    assert report["setups"][1]["matched_crop_ids"]["case-b"] == "new-b"
    baseline_night = report["setups"][0]["groups"]["night"]
    candidate_night = report["setups"][1]["groups"]["night"]
    assert baseline_night["species_correct_count"] == 0
    assert baseline_night["species_incorrect_count"] == 1
    assert baseline_night["category_match_count"] == 1
    assert baseline_night["species_precision"] == 0.0
    assert candidate_night["species_correct_count"] == 1
    assert candidate_night["out_of_list_unassigned_count"] == 1
    assert candidate_night["unassigned_reason_counts"] == {"below_threshold": 1}
    assert (
        report["paired_changes"][0]["outcomes"]["species_correct"]["false_to_true"] == 1
    )
    assert report["setups"][0]["publication_ready"] is False
    assert "fewer_than_10_night_labels" in report["setups"][0]["sample_limitations"]


def test_schema_2_category_assignment_does_not_count_as_species_correctness(
    tmp_path: Path,
) -> None:
    labels_path = _shared_labels(
        tmp_path / "typed-labels.json",
        [
            _shared_example(
                "case-fox",
                "review-fox",
                "vulpes_vulpes",
                expected_category="mammal",
            )
        ],
    )
    run = _shared_run(
        RUN_ID,
        [
            {
                "id": "broad_bird",
                "kind": "category",
                "category": "bird",
                "common_name": "Bird",
                "taxonomic_description": "An unidentified bird",
            },
            {
                "id": "broad_mammal",
                "kind": "category",
                "category": "mammal",
                "common_name": "Mammal",
                "taxonomic_description": "An unidentified mammal",
            },
            {
                "id": "great_tit",
                "kind": "species",
                "common_name": "Great tit",
                "taxonomic_description": "Parus major",
            },
        ],
    )
    report = build_evaluation_report(
        run,
        [_shared_item("crop-fox", "case-fox", "broad_mammal", "night")],
        labels_path,
        expected_run_id=UUID(RUN_ID),
    )

    metrics = report["run"]["groups"]["night"]
    assert metrics["species_absent_from_candidate_count"] == 1
    assert metrics["category_match_count"] == 1
    assert metrics["species_correct_count"] == 0
    assert metrics["species_assigned_count"] == 0


def test_shared_evaluation_excludes_ambiguous_unmatched_and_unusable_cases(
    tmp_path: Path,
) -> None:
    labels_path = _shared_labels(
        tmp_path / "shared-labels.json",
        [
            _shared_example("ambiguous", "review-a", "bird-a"),
            _shared_example("missing", "review-b", "bird-a"),
            _shared_example("unusable", "review-c", None, "unusable"),
        ],
    )
    items = [
        _shared_item("crop-1", "ambiguous", "bird-a", "day"),
        _shared_item("crop-2", "ambiguous", "bird-a", "day"),
    ]

    report = build_evaluation_report(
        _shared_run(RUN_ID, [{"id": "bird-a", "name": "Bird A"}]),
        items,
        labels_path,
        expected_run_id=UUID(RUN_ID),
    )

    assert report["run"]["matched_case_count"] == 0
    assert report["ambiguous_case_ids"] == ["ambiguous"]
    assert report["unmatched_case_ids"] == ["missing", "unusable"]
    assert report["run"]["groups"]["day"]["labeled_count"] == 0


def test_shared_labels_are_candidate_independent_and_tuning_never_publication_ready(
    tmp_path: Path,
) -> None:
    labels_path = _shared_labels(
        tmp_path / "shared-labels.json",
        [_shared_example("case-a", "review-a", "not-in-this-run")],
        role="tuning",
    )
    item = _shared_item("crop-a", "case-a", "bird-a", "day")

    report = build_evaluation_report(
        _shared_run(RUN_ID, [{"id": "bird-a", "name": "Bird A"}]),
        [item],
        labels_path,
        expected_run_id=UUID(RUN_ID),
    )

    day_group = report["run"]["groups"]["day"]
    assert day_group["species_absent_from_candidate_count"] == 1
    assert day_group["species_incorrect_count"] == 1
    assert report["run"]["publication_ready"] is False
    assert (
        "tuning_labels_cannot_support_publication_quality_claims"
        in report["run"]["sample_limitations"]
    )


def test_shared_metrics_use_null_denominators_and_count_low_quality_separately(
    tmp_path: Path,
) -> None:
    labels_path = _shared_labels(
        tmp_path / "shared-labels.json",
        [
            _shared_example("unusable", "review-a", None, "unusable"),
            _shared_example("low-quality", "review-b", "bird-a"),
        ],
    )

    report = build_evaluation_report(
        _shared_run(RUN_ID, [{"id": "bird-a", "name": "Bird A"}]),
        [
            _shared_item("crop-a", "unusable", "unknown", "day"),
            _shared_item(
                "crop-b", "low-quality", "unknown", "day", reason="low_quality"
            ),
        ],
        labels_path,
        expected_run_id=UUID(RUN_ID),
    )

    day_group = report["run"]["groups"]["day"]
    assert day_group["unusable_count"] == 1
    assert day_group["low_quality_count"] == 1
    assert day_group["species_precision"] is None
    assert day_group["species_assignment_coverage"] == 0.0
    assert day_group["processing_coverage"] == 1.0
    assert report["run"]["groups"]["night"]["processing_coverage"] is None


def test_shared_held_out_sample_gate_passes_with_ten_completed_day_and_night(
    tmp_path: Path,
) -> None:
    items: list[dict[str, object]] = []
    examples: list[dict[str, object]] = []
    for lighting in ("day", "night"):
        for index in range(10):
            case_id = f"{lighting}-{index}"
            items.append(_shared_item(f"crop-{case_id}", case_id, "bird-a", lighting))
            examples.append(_shared_example(case_id, f"review-{case_id}", "bird-a"))
    run_data = _shared_run(RUN_ID, [{"id": "bird-a", "name": "Bird A"}])
    run_data["counts"] = {"selected": 20}

    report = build_evaluation_report(
        run_data,
        items,
        _shared_labels(tmp_path / "shared-labels.json", examples),
        expected_run_id=UUID(RUN_ID),
    )

    assert report["run"]["publication_ready"] is True
    assert report["run"]["sample_limitations"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda labels: labels.update(label_role="other"),
        lambda labels: labels.update(source_split_sha256="0" * 64),
        lambda labels: labels.update(source_split_keys=["z", "a"]),
        lambda labels: labels["examples"][0].update(truth_kind="unknown"),
        lambda labels: labels["examples"][0].update(expected_taxon_id=None),
        lambda labels: labels["examples"][0].update(expected_category="reptile"),
        lambda labels: labels["examples"][0].update(extra=True),
    ],
)
def test_shared_label_validation_rejects_invalid_fields_and_values(
    tmp_path: Path, mutate: Callable[[dict[str, object]], None]
) -> None:
    labels_path = _shared_labels(
        tmp_path / "shared-labels.json",
        [_shared_example("case-a", "review-a", "bird-a")],
    )
    document = json.loads(labels_path.read_text(encoding="utf-8"))
    mutate(document)
    labels_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(EmbedValidationError):
        build_evaluation_report(
            _shared_run(RUN_ID, [{"id": "bird-a", "name": "Bird A"}]),
            [_shared_item("crop-a", "case-a", "bird-a", "day")],
            labels_path,
            expected_run_id=UUID(RUN_ID),
        )


def test_schema_one_evaluation_report_remains_legacy_version(tmp_path: Path) -> None:
    report = build_evaluation_report(
        _run_data(),
        _items(),
        _labels(tmp_path / "legacy-labels.json", []),
        expected_run_id=UUID(RUN_ID),
    )

    assert report["schema_version"] == 1
    assert report["run_id"] == RUN_ID


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
