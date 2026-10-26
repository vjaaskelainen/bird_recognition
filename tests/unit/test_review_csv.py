import argparse
import csv
import hashlib
import json
from pathlib import Path

import pytest
from tools import review_csv


def _provenance(
    *,
    source_id: str,
    frame_number: int,
    detection_id: str,
    lighting: str,
    recording_day: str | None = "2026-10-25",
    crop_id: str | None = None,
) -> dict[str, object]:
    crop_id = crop_id or f"crop-{source_id}-{frame_number}-{detection_id}"
    return {
        "crop_id": crop_id,
        "crop_original_image_path": f"crops/{crop_id}.jpg",
        "source_id": source_id,
        "source_content_sha256": "a" * 64,
        "frame_number": frame_number,
        "detection_id": detection_id,
        "detection_box_normalized": [0.1, 0.2, 0.7, 0.8],
        "capture_time": f"{recording_day}T12:00:00" if recording_day else None,
        "source_capture_start": None,
        "lighting": lighting,
        "ingest_settings_fingerprint": "b" * 64,
    }


def _inspect_document(provenances: list[dict[str, object]]) -> dict[str, object]:
    return {
        "run": {"run_id": "run-1"},
        "items": [
            {
                "crop_id": provenance["crop_id"],
                "lighting": provenance["lighting"],
                "provenance": provenance,
            }
            for provenance in provenances
        ],
    }


def _write_review_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_csv.FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _review_row(
    *,
    case_id: str = "case-1",
    crop_id: str = "crop-1",
    source_id: str = "source-1",
    recording_day: str = "2026-10-25",
    truth_kind: str = "species",
    expected_species_id: str = "parus_major",
) -> dict[str, str]:
    return {
        "run_id": "run-1",
        "crop_id": crop_id,
        "lighting": "day",
        "animal_type": expected_species_id,
        "image_path": "external/crop.jpg",
        "expected_species_id": expected_species_id,
        "truth_kind": truth_kind,
        "notes": "",
        "case_id": case_id,
        "source_id": source_id,
        "source_content_sha256": "a" * 64,
        "frame_number": "12",
        "detection_id": "detection-1",
        "detection_box_normalized": "[0.1,0.2,0.7,0.8]",
        "recording_day": recording_day,
        "expected_category": "bird",
    }


def test_create_per_lighting_is_deterministic_and_filters_repeated_source_ids(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    provenance = [
        _provenance(
            source_id="source-a",
            frame_number=0,
            detection_id="d-0",
            lighting="day",
        ),
        _provenance(
            source_id="source-a",
            frame_number=4,
            detection_id="d-4",
            lighting="night",
        ),
        _provenance(
            source_id="source-b",
            frame_number=5,
            detection_id="d-5",
            lighting="day",
        ),
    ]
    inspect_path = tmp_path / "inspect.json"
    inspect_path.write_text(json.dumps(_inspect_document(provenance)), encoding="utf-8")

    outputs = [tmp_path / "first.csv", tmp_path / "second.csv"]
    for output in outputs:
        review_csv.create(
            argparse.Namespace(
                inspect=inspect_path,
                crop_root=tmp_path,
                output=output,
                limit=None,
                per_lighting=2,
                seed=19,
                source_id=["source-a", "source-b"],
            )
        )

    with outputs[0].open(newline="", encoding="utf-8") as handle:
        first_rows = list(csv.DictReader(handle))
    with outputs[1].open(newline="", encoding="utf-8") as handle:
        second_rows = list(csv.DictReader(handle))

    assert [row["crop_id"] for row in first_rows] == [
        row["crop_id"] for row in second_rows
    ]
    assert len(first_rows) == 3
    assert {row["lighting"] for row in first_rows} == {"day", "night"}
    assert {row["source_id"] for row in first_rows} == {"source-a", "source-b"}
    assert all(row["case_id"] for row in first_rows)
    assert "shortfall" in capsys.readouterr().err.casefold()


def test_case_id_ignores_crop_policy_and_crop_identity() -> None:
    first = _provenance(
        source_id="source-a",
        frame_number=1,
        detection_id="d-1",
        lighting="unknown",
        crop_id="tight-crop",
    )
    second = dict(first)
    second["crop_id"] = "expanded-crop"
    second["ingest_settings_fingerprint"] = "c" * 64

    assert review_csv._case_id(first) == review_csv._case_id(second)
    changed_source = dict(second, source_content_sha256="d" * 64)
    changed_detection = dict(second, detection_id="different-detection")
    changed_box = dict(second, detection_box_normalized=[0.1, 0.2, 0.8, 0.8])
    assert review_csv._case_id(first) != review_csv._case_id(changed_source)
    assert review_csv._case_id(first) != review_csv._case_id(changed_detection)
    assert review_csv._case_id(first) != review_csv._case_id(changed_box)


def test_create_rejects_mutually_exclusive_sampling_options() -> None:
    parser = review_csv._build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "create",
                "--inspect",
                "inspect.json",
                "--crop-root",
                "crops",
                "--output",
                "review.csv",
                "--limit",
                "4",
                "--per-lighting",
                "2",
            ]
        )


@pytest.mark.parametrize("per_lighting", [0, 501])
def test_create_rejects_out_of_range_stratum_limit(
    per_lighting: int, tmp_path: Path
) -> None:
    inspect_path = tmp_path / "inspect.json"
    inspect_path.write_text(json.dumps(_inspect_document([])), encoding="utf-8")

    with pytest.raises(SystemExit, match="between 1 and 500"):
        review_csv.create(
            argparse.Namespace(
                inspect=inspect_path,
                crop_root=tmp_path,
                output=tmp_path / "review.csv",
                limit=None,
                per_lighting=per_lighting,
                seed=1,
                source_id=[],
            )
        )


def test_create_rejects_duplicate_case_keys_from_ambiguous_detections(
    tmp_path: Path,
) -> None:
    first = _provenance(
        source_id="source-a",
        frame_number=1,
        detection_id="d-1",
        lighting="day",
        crop_id="tight-crop",
    )
    second = dict(first, crop_id="duplicate-crop")
    inspect_path = tmp_path / "inspect.json"
    inspect_path.write_text(
        json.dumps(_inspect_document([first, second])), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="ambiguous case_id"):
        review_csv.create(
            argparse.Namespace(
                inspect=inspect_path,
                crop_root=tmp_path,
                output=tmp_path / "review.csv",
                limit=None,
                per_lighting=None,
                seed=1,
                source_id=[],
            )
        )


def test_create_applies_global_limit_and_zero_remains_unlimited(
    tmp_path: Path,
) -> None:
    provenances = [
        _provenance(
            source_id="source-a",
            frame_number=index,
            detection_id=f"d-{index}",
            lighting="day",
        )
        for index in range(4)
    ]
    inspect_path = tmp_path / "inspect.json"
    inspect_path.write_text(
        json.dumps(_inspect_document(provenances)), encoding="utf-8"
    )

    outputs = [(tmp_path / "limited.csv", 2), (tmp_path / "unlimited.csv", 0)]
    for output, limit in outputs:
        review_csv.create(
            argparse.Namespace(
                inspect=inspect_path,
                crop_root=tmp_path,
                output=output,
                limit=limit,
                per_lighting=None,
                seed=3,
                source_id=[],
            )
        )

    counts = []
    for output, _ in outputs:
        with output.open(newline="", encoding="utf-8") as handle:
            counts.append(len(list(csv.DictReader(handle))))
    assert counts == [2, 4]


def test_to_labels_builds_candidate_independent_shared_label_set(
    tmp_path: Path,
) -> None:
    rows = [
        _review_row(),
        _review_row(
            case_id="case-2",
            crop_id="crop-2",
            source_id="source-2",
            truth_kind="not-in-list",
            expected_species_id="external_taxon",
        ),
    ]
    csv_path = tmp_path / "review.csv"
    _write_review_csv(csv_path, rows)
    output = tmp_path / "labels.json"

    review_csv.to_labels(
        argparse.Namespace(
            csv=csv_path,
            output=output,
            label_role="held_out_evaluation",
            split_mode="source_video",
        )
    )

    labels = json.loads(output.read_text(encoding="utf-8"))
    expected_keys = ["source-1", "source-2"]
    expected_digest = hashlib.sha256(
        json.dumps(expected_keys, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    assert labels["schema_version"] == 2
    assert labels["label_role"] == "held_out_evaluation"
    assert labels["split_mode"] == "source_video"
    assert labels["source_split_keys"] == expected_keys
    assert labels["source_split_sha256"] == expected_digest
    assert labels["examples"][0]["case_id"] == "case-1"
    assert labels["examples"][0]["reviewed_crop_id"] == "crop-1"
    assert labels["examples"][0]["expected_taxon_id"] == "parus_major"
    assert labels["examples"][0]["expected_category"] == "bird"
    assert labels["examples"][1]["truth_kind"] == "out_of_list"


@pytest.mark.parametrize(
    ("label_role", "split_mode"),
    [("invalid", "source_video"), ("tuning", "unknown"), (None, "source_video")],
)
def test_to_labels_rejects_invalid_shared_label_options(
    tmp_path: Path, label_role: str | None, split_mode: str | None
) -> None:
    csv_path = tmp_path / "review.csv"
    _write_review_csv(csv_path, [_review_row()])

    with pytest.raises(SystemExit, match="label-role|split-mode"):
        review_csv.to_labels(
            argparse.Namespace(
                csv=csv_path,
                output=tmp_path / "labels.json",
                label_role=label_role,
                split_mode=split_mode,
            )
        )


def test_to_labels_rejects_unknown_recording_day_and_ambiguous_cases(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "review.csv"
    _write_review_csv(csv_path, [_review_row(recording_day="")])
    args = argparse.Namespace(
        csv=csv_path,
        output=tmp_path / "labels.json",
        label_role="tuning",
        split_mode="recording_day",
    )

    with pytest.raises(SystemExit, match="recording day"):
        review_csv.to_labels(args)

    _write_review_csv(
        csv_path,
        [_review_row(), _review_row(crop_id="crop-duplicate")],
    )
    args.split_mode = "source_video"
    with pytest.raises(SystemExit, match="duplicate|ambiguous"):
        review_csv.to_labels(args)


def test_to_labels_maps_legacy_unknown_choice_to_unidentifiable(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "review.csv"
    _write_review_csv(
        csv_path,
        [
            _review_row(
                truth_kind="unknown",
                expected_species_id="",
            )
        ],
    )
    output = tmp_path / "labels.json"

    review_csv.to_labels(
        argparse.Namespace(
            csv=csv_path,
            output=output,
            label_role="tuning",
            split_mode="source_video",
        )
    )

    labels = json.loads(output.read_text(encoding="utf-8"))
    assert labels["examples"][0]["truth_kind"] == "unidentifiable"
    assert labels["examples"][0]["expected_taxon_id"] is None


def test_to_labels_preserves_legacy_schema_when_shared_options_are_omitted(
    tmp_path: Path,
) -> None:
    row = _review_row()
    csv_path = tmp_path / "review.csv"
    _write_review_csv(csv_path, [row])
    output = tmp_path / "legacy-labels.json"

    review_csv.to_labels(
        argparse.Namespace(
            csv=csv_path, output=output, label_role=None, split_mode=None
        )
    )

    labels = json.loads(output.read_text(encoding="utf-8"))
    assert labels == {
        "schema_version": 1,
        "run_id": "run-1",
        "examples": [
            {
                "crop_id": "crop-1",
                "expected_species_id": "parus_major",
                "truth_kind": "species",
                "notes": "",
            }
        ],
    }
