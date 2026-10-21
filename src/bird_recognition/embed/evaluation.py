"""Validation and persisted-only evaluation of species decisions."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from bird_recognition.embed.config import canonical_json_bytes
from bird_recognition.embed.models import EmbedValidationError, StorageError
from bird_recognition.embed.scoring import (
    RELATIVE_CONFIDENCE_WARNING,
    SINGLE_CANDIDATE_WARNING,
)


def load_label_file(path: Path) -> tuple[dict[str, Any], str, Path]:
    """Read strict UTF-8 labels and return their canonical-content digest."""
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        if _is_inside_git_repository(resolved):
            raise EmbedValidationError(
                "labels file must be outside every Git repository"
            )
        raw = resolved.read_bytes()
        document = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except EmbedValidationError:
        raise
    except OSError, UnicodeError, json.JSONDecodeError, ValueError:
        raise EmbedValidationError(
            "labels file is unreadable or invalid UTF-8 JSON"
        ) from None
    if not isinstance(document, dict):
        raise EmbedValidationError("labels document must be a JSON object")
    return (
        document,
        hashlib.sha256(canonical_json_bytes(document)).hexdigest(),
        resolved,
    )


def build_evaluation_report(
    run_data: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    labels_path: Path,
    *,
    expected_run_id: UUID,
) -> dict[str, object]:
    """Build lighting-grouped metrics using only persisted run items and decisions."""
    labels, labels_sha256, _ = load_label_file(labels_path)
    examples = _validate_labels(labels, run_data, items, expected_run_id)
    item_by_id = {str(item["crop_id"]): item for item in items}
    groups: dict[str, dict[str, object]] = {}
    for lighting in ("day", "night", "unknown"):
        group_labels = [
            example
            for example in examples
            if _item_lighting(item_by_id[example["crop_id"]]) == lighting
        ]
        groups[lighting] = _group_metrics(group_labels, item_by_id)

    counts = run_data.get("counts", {})
    all_run_items = int(counts.get("selected", len(items)))
    candidate_count = len(_candidate_ids(run_data))
    return {
        "schema_version": 1,
        "evaluation_id": str(uuid4()),
        "evaluated_at": datetime.now(UTC).isoformat(),
        "run_id": str(expected_run_id),
        "run_status": run_data.get("status"),
        "labels_sha256": labels_sha256,
        "model_fingerprint": run_data.get("model_fingerprint"),
        "candidate_set_fingerprint": run_data.get("candidate_set_fingerprint"),
        "scoring_fingerprint": run_data.get("scoring_fingerprint"),
        "config_fingerprint": run_data.get("config_fingerprint"),
        "threshold": run_data.get("threshold"),
        "candidate_count": candidate_count,
        "label_notes": [
            {"crop_id": example["crop_id"], "notes": example["notes"]}
            for example in examples
            if example.get("notes") is not None
        ],
        "warnings": [RELATIVE_CONFIDENCE_WARNING]
        + ([SINGLE_CANDIDATE_WARNING] if candidate_count == 1 else []),
        "unlabeled_run_item_count": max(all_run_items - len(examples), 0),
        "publication_ready": (
            int(groups["day"]["completed_count"]) >= 10
            and int(groups["night"]["completed_count"]) >= 10
        ),
        "groups": groups,
    }


def validate_report_destination(path: Path) -> Path:
    """Resolve a report target and reject repository paths or existing files."""
    target = Path(path).expanduser().resolve(strict=False)
    if target.exists():
        raise EmbedValidationError("report output already exists")
    if not target.parent.is_dir():
        raise EmbedValidationError("report output directory must already exist")
    if _is_inside_git_repository(target):
        raise EmbedValidationError("report output must be outside every Git repository")
    return target


def write_evaluation_report(report: Mapping[str, object], path: Path) -> Path:
    """Atomically create a new external report without replacing an existing target."""
    target = validate_report_destination(path)
    serialized = canonical_json_bytes(report) + b"\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=".evaluation-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.link(temporary_path, target)
        temporary_path.unlink()
        temporary_path = None
        return target
    except FileExistsError:
        raise EmbedValidationError("report output already exists") from None
    except OSError:
        raise StorageError(
            "evaluation report could not be finalized atomically"
        ) from None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _validate_labels(
    document: Mapping[str, Any],
    run_data: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    expected_run_id: UUID,
) -> list[dict[str, str | None]]:
    if set(document) != {"schema_version", "run_id", "examples"}:
        raise EmbedValidationError(
            "labels document must contain only schema_version, run_id, and examples"
        )
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise EmbedValidationError("unsupported labels schema version")
    try:
        document_run_id = UUID(document["run_id"])
    except ValueError, TypeError, AttributeError:
        raise EmbedValidationError("labels run_id must be a UUID") from None
    if document_run_id != expected_run_id or str(run_data.get("run_id")) != str(
        expected_run_id
    ):
        raise EmbedValidationError("labels run_id does not match the selected run")
    values = document["examples"]
    if not isinstance(values, list):
        raise EmbedValidationError("labels examples must be an array")
    item_by_id = {str(item.get("crop_id")): item for item in items}
    candidate_ids = _candidate_ids(run_data)
    result: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for value in values:
        if (
            not isinstance(value, dict)
            or set(value)
            - {
                "crop_id",
                "expected_species_id",
                "truth_kind",
                "notes",
            }
            or not {"crop_id", "expected_species_id", "truth_kind"} <= set(value)
        ):
            raise EmbedValidationError("each label has an invalid field set")
        crop_id = value["crop_id"]
        expected = value["expected_species_id"]
        truth_kind = value["truth_kind"]
        if not isinstance(crop_id, str) or not crop_id.strip() or crop_id in seen:
            raise EmbedValidationError("label crop IDs must be nonblank and unique")
        if crop_id not in item_by_id:
            raise EmbedValidationError("labels contain a crop outside the selected run")
        if expected is not None and (
            not isinstance(expected, str) or not expected.strip()
        ):
            raise EmbedValidationError(
                "expected species IDs must be nonblank strings or null"
            )
        if not isinstance(truth_kind, str) or truth_kind not in {
            "species",
            "out_of_list",
            "unidentifiable",
        }:
            raise EmbedValidationError("label truth_kind is invalid")
        if truth_kind == "species" and expected not in candidate_ids:
            raise EmbedValidationError("species truth must name a selected candidate")
        if truth_kind == "out_of_list" and expected in candidate_ids:
            raise EmbedValidationError(
                "out-of-list truth cannot name a selected candidate"
            )
        if truth_kind == "unidentifiable" and expected is not None:
            raise EmbedValidationError(
                "unidentifiable truth requires a null species ID"
            )
        notes = value.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise EmbedValidationError("label notes must be a string")
        try:
            _item_lighting(item_by_id[crop_id])
        except ValueError:
            raise EmbedValidationError(
                "persisted run-item lighting is invalid"
            ) from None
        seen.add(crop_id)
        normalized_example: dict[str, str | None] = {
            "crop_id": crop_id,
            "expected_species_id": expected,
            "truth_kind": truth_kind,
        }
        if notes is not None:
            normalized_example["notes"] = notes
        result.append(normalized_example)
    return result


def _group_metrics(
    labels: Sequence[Mapping[str, str | None]],
    item_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, object]:
    completed = correct = incorrect = unknown = failed = pending = assigned = 0
    failures: list[dict[str, object]] = []
    for label in labels:
        crop_id = str(label["crop_id"])
        item = item_by_id[crop_id]
        status = item.get("status")
        decision = item.get("decision")
        if status in {"completed", "skipped"}:
            if not isinstance(decision, Mapping):
                raise EmbedValidationError("completed run item is missing its decision")
            completed += 1
            assigned_id = decision.get("assigned_species_id")
            if assigned_id in (None, "unknown"):
                unknown += 1
                failures.append(
                    {
                        "crop_id": crop_id,
                        "truth_kind": label["truth_kind"],
                        "expected_species_id": label["expected_species_id"],
                        "assigned_species_id": "unknown",
                        "reason": str(decision.get("reason", "unknown")),
                    }
                )
            else:
                assigned += 1
                if (
                    label["truth_kind"] == "species"
                    and assigned_id == label["expected_species_id"]
                ):
                    correct += 1
                else:
                    incorrect += 1
                    failures.append(
                        {
                            "crop_id": crop_id,
                            "truth_kind": label["truth_kind"],
                            "expected_species_id": label["expected_species_id"],
                            "assigned_species_id": assigned_id,
                            "reason": "incorrect_assignment",
                        }
                    )
        elif status == "failed":
            failed += 1
            failures.append(
                {
                    "crop_id": crop_id,
                    "truth_kind": label["truth_kind"],
                    "expected_species_id": label["expected_species_id"],
                    "reason": item.get("failure_code") or "processing_failed",
                }
            )
        elif status == "pending":
            pending += 1
            failures.append(
                {
                    "crop_id": crop_id,
                    "truth_kind": label["truth_kind"],
                    "expected_species_id": label["expected_species_id"],
                    "reason": "pending",
                }
            )
        else:
            raise EmbedValidationError("persisted run item has an invalid status")

    samples = len(labels)
    return {
        "sample_count": samples,
        "completed_count": completed,
        "correct_count": correct,
        "incorrect_count": incorrect,
        "unknown_count": unknown,
        "failed_count": failed,
        "pending_count": pending,
        "assigned_count": assigned,
        "precision": correct / assigned if assigned else None,
        "assignment_coverage": assigned / completed if completed else None,
        "processing_coverage": completed / samples if samples else None,
        "failure_examples": failures,
    }


def _candidate_ids(run_data: Mapping[str, Any]) -> set[str]:
    candidates = run_data.get("candidates")
    if isinstance(candidates, Mapping):
        candidates = candidates.get("species")
    if not isinstance(candidates, list):
        raise EmbedValidationError("selected run has no persisted candidate list")
    identifiers = {
        value.get("id")
        for value in candidates
        if isinstance(value, Mapping) and isinstance(value.get("id"), str)
    }
    if len(identifiers) != len(candidates) or not identifiers:
        raise EmbedValidationError("selected run candidate list is invalid")
    return identifiers


def _item_lighting(item: Mapping[str, Any]) -> str:
    lighting = item.get("lighting")
    if lighting not in {"day", "night", "unknown"}:
        provenance = item.get("provenance")
        lighting = (
            provenance.get("lighting") if isinstance(provenance, Mapping) else None
        )
    if lighting not in {"day", "night", "unknown"}:
        raise ValueError("run item has no valid lighting")
    return str(lighting)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _is_inside_git_repository(path: Path) -> bool:
    for candidate in (path, *path.parents):
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode == 0:
            return True
    return False
