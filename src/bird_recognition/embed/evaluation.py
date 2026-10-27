"""Validation and persisted-only evaluation of species decisions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from PIL import Image

from bird_recognition.embed.config import canonical_json_bytes
from bird_recognition.embed.manifest import resolve_crop_path
from bird_recognition.embed.models import (
    EmbedValidationError,
    SpeciesCandidate,
    StorageError,
)
from bird_recognition.embed.scoring import (
    RELATIVE_CONFIDENCE_WARNING,
    SINGLE_CANDIDATE_WARNING,
    score_embeddings,
    validate_normalized_vector,
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
    if labels.get("schema_version") == 2:
        label_set = _validate_shared_labels(labels)
        if str(run_data.get("run_id")) != str(expected_run_id):
            raise EmbedValidationError("selected run ID does not match run data")
        setup, _ = _evaluate_shared_run(run_data, items, label_set)
        return {
            "schema_version": 2,
            "evaluation_id": str(uuid4()),
            "evaluated_at": datetime.now(UTC).isoformat(),
            "label_set": _label_set_identity(label_set, labels_sha256),
            "run": setup,
            "matched_case_count": setup["matched_case_count"],
            "unmatched_case_ids": setup["unmatched_case_ids"],
            "ambiguous_case_ids": setup["ambiguous_case_ids"],
            "warnings": _shared_warnings(),
        }
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
        "reference": _run_reference_identity(run_data),
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


def build_comparison_report(
    run_entries: Sequence[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]]]],
    labels_path: Path,
    *,
    expected_run_ids: Sequence[UUID],
) -> dict[str, object]:
    """Compare explicitly selected runs on shared labels using one-to-one cases."""
    if len(run_entries) < 2 or len(run_entries) != len(expected_run_ids):
        raise EmbedValidationError("comparison requires at least two selected runs")
    if len(set(expected_run_ids)) != len(expected_run_ids):
        raise EmbedValidationError("comparison run IDs must be unique")
    labels, labels_sha256, _ = load_label_file(labels_path)
    label_set = _validate_shared_labels(labels)
    setups: list[dict[str, object]] = []
    matched_by_run: list[dict[str, dict[str, Any]]] = []
    for (run_data, items), expected_run_id in zip(
        run_entries, expected_run_ids, strict=True
    ):
        if str(run_data.get("run_id")) != str(expected_run_id):
            raise EmbedValidationError("selected run ID does not match run data")
        setup, matched = _evaluate_shared_run(run_data, items, label_set)
        setups.append(setup)
        matched_by_run.append(matched)
    paired_case_ids = sorted(
        set.intersection(*(set(matches) for matches in matched_by_run))
    )
    return {
        "schema_version": 2,
        "comparison_id": str(uuid4()),
        "compared_at": datetime.now(UTC).isoformat(),
        "label_set": _label_set_identity(label_set, labels_sha256),
        "paired_case_count": len(paired_case_ids),
        "unpaired_case_count": len(label_set["examples"]) - len(paired_case_ids),
        "paired_case_ids": paired_case_ids,
        "setups": setups,
        "paired_changes": _paired_changes(setups, matched_by_run, paired_case_ids),
        "warnings": _shared_warnings(),
    }


def build_benchmark_report(
    run_data: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    labels_path: Path,
    *,
    model: Any,
    max_crops: int,
) -> dict[str, object]:
    """Re-evaluate a deterministic bounded cohort with an explicit local model."""
    if type(max_crops) is not int or not 1 <= max_crops <= 500:
        raise EmbedValidationError(
            "max crops must be a positive integer no greater than 500"
        )
    labels_document, labels_sha256, _ = load_label_file(labels_path)
    label_set = _validate_shared_labels(labels_document)
    if label_set["label_role"] != "held_out_evaluation":
        raise EmbedValidationError(
            "benchmark quality evaluation requires held-out labels"
        )
    if not model.identity.adapter_version.startswith("bioclip-local-"):
        raise EmbedValidationError("selected local model adapter is unsupported")
    candidates = _benchmark_candidates(run_data)
    candidate_ids = {candidate.id for candidate in candidates}
    item_by_case: dict[str, list[Mapping[str, Any]]] = {}
    for item in items:
        case_id = _item_case_id(item, item.get("provenance"))
        if case_id:
            item_by_case.setdefault(case_id, []).append(item)
    eligible = [
        (example, item_by_case[example["case_id"]][0])
        for example in label_set["examples"]
        if example["truth_kind"] != "unusable"
        and len(item_by_case.get(example["case_id"], ())) == 1
    ]
    selected = sorted(
        eligible,
        key=lambda pair: (
            hashlib.sha256(pair[0]["case_id"].encode("utf-8")).hexdigest(),
            pair[0]["case_id"],
        ),
    )[:max_crops]
    if not selected:
        raise EmbedValidationError("benchmark has no uniquely matched eligible crops")
    if any(
        example["truth_kind"] == "species"
        and example["expected_taxon_id"] not in candidate_ids
        for example, _ in selected
    ):
        raise EmbedValidationError(
            "benchmark labels include species outside the selected candidates"
        )
    candidate_document = run_data.get("candidates")
    if isinstance(candidate_document, Mapping):
        candidate_document = candidate_document.get(
            "candidates", candidate_document.get("species")
        )
    if not isinstance(candidate_document, list):
        raise EmbedValidationError("selected run has no persisted candidate list")
    prompt_config = run_data.get("config")
    if not isinstance(prompt_config, Mapping):
        prompt_config = {}
    scoring_config = prompt_config.get("scoring", {})
    if not isinstance(scoring_config, Mapping):
        scoring_config = {}
    prompt_template = scoring_config.get("prompt_template", "a photo of {name}.")
    if not isinstance(prompt_template, str):
        raise EmbedValidationError("selected run prompt identity is invalid")
    from bird_recognition.embed.config import format_candidate_prompt

    prompts = tuple(
        format_candidate_prompt(candidate, prompt_template) for candidate in candidates
    )
    started = time.perf_counter()
    try:
        text_vectors = tuple(
            validate_normalized_vector(vector) for vector in model.encode_texts(prompts)
        )
        if len(text_vectors) != len(candidates):
            raise EmbedValidationError(
                "selected local model returned incomplete text vectors"
            )
    except EmbedValidationError:
        raise
    except Exception:
        raise EmbedValidationError("selected local model benchmark failed") from None
    crop_root = run_data.get("crop_root")
    if not isinstance(crop_root, str) or not crop_root:
        raise EmbedValidationError("selected run has no crop root for benchmarking")
    threshold = run_data.get("threshold", 0.5)
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise EmbedValidationError("selected run threshold is invalid")
    benchmark_items: list[dict[str, Any]] = []
    selected_crop_ids: list[str] = []
    try:
        for example, item in selected:
            provenance = item.get("provenance")
            relative_path = (
                provenance.get("crop_original_image_path")
                if isinstance(provenance, Mapping)
                else None
            )
            crop_id = item.get("crop_id")
            lighting = _item_lighting(item)
            if not isinstance(relative_path, str) or not isinstance(crop_id, str):
                raise EmbedValidationError("benchmark crop provenance is incomplete")
            crop_path = resolve_crop_path(Path(crop_root), relative_path)
            with Image.open(crop_path) as image:
                image.load()
                image_vector = validate_normalized_vector(
                    model.encode_image(image.convert("RGB"))
                )
            decision = score_embeddings(
                image_vector,
                text_vectors,
                candidates,
                logit_scale=model.identity.logit_scale,
                threshold=float(threshold),
            )
            selected_crop_ids.append(crop_id)
            benchmark_items.append(
                {
                    "crop_id": crop_id,
                    "case_id": example["case_id"],
                    "status": "completed",
                    "lighting": lighting,
                    "decision": {
                        "assigned_species_id": decision.assigned_species_id,
                        "reason": decision.reason,
                    },
                    "provenance": provenance,
                }
            )
    except EmbedValidationError:
        raise
    except Exception:
        raise EmbedValidationError("benchmark crop could not be processed") from None
    elapsed_seconds = time.perf_counter() - started
    benchmark_run_data = {
        **run_data,
        "model_fingerprint": model.identity.model_fingerprint,
        "candidates": candidate_document,
    }
    matched, _ = _evaluate_shared_run(benchmark_run_data, benchmark_items, label_set)
    setup_identity = {
        "selected_run_id": str(run_data.get("run_id")),
        "baseline_model_fingerprint": run_data.get("model_fingerprint"),
        "baseline_config_fingerprint": run_data.get("config_fingerprint"),
        "model_fingerprint": model.identity.model_fingerprint,
        "candidate_set_fingerprint": run_data.get("candidate_set_fingerprint"),
        "scoring_fingerprint": run_data.get("scoring_fingerprint"),
        "prompt_template": prompt_template,
        "prompt_version": scoring_config.get("prompt_version", "species-photo-v1"),
        "input_view": json.loads(model.identity.preprocessing_json).get("input_view"),
        "threshold": float(threshold),
        "max_crops": max_crops,
        "sample_case_ids": [example["case_id"] for example, _ in selected],
        "sample_crop_ids": selected_crop_ids,
    }
    return {
        "schema_version": 1,
        "benchmark_id": str(uuid4()),
        "benchmarked_at": datetime.now(UTC).isoformat(),
        "label_set": _label_set_identity(label_set, labels_sha256),
        "setup": {
            **setup_identity,
            "benchmark_setup_fingerprint": hashlib.sha256(
                canonical_json_bytes(setup_identity)
            ).hexdigest(),
            "adapter_version": model.identity.adapter_version,
        },
        "max_crops": max_crops,
        "sample_count": len(selected),
        "elapsed_seconds": elapsed_seconds,
        "quality": matched["groups"],
        "sample_limitations": _sample_limitations(
            matched["groups"], str(label_set["label_role"])
        ),
        "warnings": _shared_warnings(),
    }


def _benchmark_candidates(run_data: Mapping[str, Any]) -> tuple[SpeciesCandidate, ...]:
    values = run_data.get("candidates")
    if isinstance(values, Mapping):
        values = values.get("candidates", values.get("species"))
    if not isinstance(values, list) or not values:
        raise EmbedValidationError("selected run has no persisted candidate list")
    try:
        return tuple(
            SpeciesCandidate(
                id=value["id"],
                name=value.get("name"),
                kind=value.get("kind", "species"),
                common_name=value.get("common_name"),
                taxonomic_description=value.get("taxonomic_description"),
                category=value.get("category"),
            )
            for value in values
        )
    except KeyError, TypeError, EmbedValidationError:
        raise EmbedValidationError("selected run candidate list is invalid") from None


def _validate_shared_labels(document: Mapping[str, Any]) -> dict[str, Any]:
    if set(document) != {
        "schema_version",
        "label_role",
        "split_mode",
        "source_split_keys",
        "source_split_sha256",
        "examples",
    }:
        raise EmbedValidationError("shared labels contain an invalid field set")
    if type(document["schema_version"]) is not int or document["schema_version"] != 2:
        raise EmbedValidationError("unsupported shared labels schema version")
    label_role = document["label_role"]
    split_mode = document["split_mode"]
    if not isinstance(label_role, str) or label_role not in {
        "tuning",
        "held_out_evaluation",
    }:
        raise EmbedValidationError("label_role must be tuning or held_out_evaluation")
    if not isinstance(split_mode, str) or split_mode not in {
        "source_video",
        "recording_day",
    }:
        raise EmbedValidationError("split_mode must be source_video or recording_day")
    split_keys = document["source_split_keys"]
    if (
        not isinstance(split_keys, list)
        or not split_keys
        or any(
            not isinstance(key, str) or key != key.strip() or not key
            for key in split_keys
        )
        or split_keys != sorted(set(split_keys))
    ):
        raise EmbedValidationError(
            "source_split_keys must be sorted, unique, and nonempty"
        )
    split_digest = hashlib.sha256(canonical_json_bytes(split_keys)).hexdigest()
    if document["source_split_sha256"] != split_digest:
        raise EmbedValidationError("source_split_sha256 does not match split keys")
    values = document["examples"]
    if not isinstance(values, list) or not values:
        raise EmbedValidationError("shared labels examples must be a nonempty array")
    examples: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    seen_crops: set[str] = set()
    for value in values:
        allowed = {
            "case_id",
            "reviewed_crop_id",
            "truth_kind",
            "expected_taxon_id",
            "expected_category",
            "notes",
        }
        if (
            not isinstance(value, dict)
            or set(value) - allowed
            or not {"case_id", "reviewed_crop_id", "truth_kind", "expected_taxon_id"}
            <= set(value)
        ):
            raise EmbedValidationError("each shared label has an invalid field set")
        case_id = value["case_id"]
        reviewed_crop_id = value["reviewed_crop_id"]
        truth_kind = value["truth_kind"]
        expected_taxon_id = value["expected_taxon_id"]
        expected_category = value.get("expected_category")
        notes = value.get("notes")
        if (
            not isinstance(case_id, str)
            or not case_id.strip()
            or case_id in seen_cases
            or not isinstance(reviewed_crop_id, str)
            or not reviewed_crop_id.strip()
            or reviewed_crop_id in seen_crops
        ):
            raise EmbedValidationError(
                "shared label case and crop IDs must be unique and nonblank"
            )
        if not isinstance(truth_kind, str) or truth_kind not in {
            "species",
            "out_of_list",
            "unidentifiable",
            "unusable",
        }:
            raise EmbedValidationError("shared label truth_kind is invalid")
        if expected_taxon_id is not None and (
            not isinstance(expected_taxon_id, str) or not expected_taxon_id.strip()
        ):
            raise EmbedValidationError("expected_taxon_id must be nonblank or null")
        if truth_kind == "species" and expected_taxon_id is None:
            raise EmbedValidationError("species truth requires expected_taxon_id")
        if (
            truth_kind in {"unidentifiable", "unusable"}
            and expected_taxon_id is not None
        ):
            raise EmbedValidationError(f"{truth_kind} truth requires a null taxon ID")
        if expected_category is not None and (
            not isinstance(expected_category, str)
            or expected_category not in {"bird", "mammal"}
        ):
            raise EmbedValidationError(
                "expected_category must be bird, mammal, or null"
            )
        if notes is not None and not isinstance(notes, str):
            raise EmbedValidationError("label notes must be a string")
        seen_cases.add(case_id)
        seen_crops.add(reviewed_crop_id)
        examples.append(
            {
                "case_id": case_id,
                "reviewed_crop_id": reviewed_crop_id,
                "truth_kind": truth_kind,
                "expected_taxon_id": expected_taxon_id,
                "expected_category": expected_category,
                "notes": notes,
            }
        )
    return {
        "label_role": label_role,
        "split_mode": split_mode,
        "source_split_keys": split_keys,
        "source_split_sha256": split_digest,
        "examples": examples,
    }


def _evaluate_shared_run(
    run_data: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    label_set: Mapping[str, Any],
) -> tuple[dict[str, object], dict[str, dict[str, Any]]]:
    item_by_case: dict[str, list[Mapping[str, Any]]] = {}
    seen_crop_ids: set[str] = set()
    for item in items:
        crop_id = item.get("crop_id")
        if not isinstance(crop_id, str) or not crop_id or crop_id in seen_crop_ids:
            raise EmbedValidationError("run crop IDs must be unique and nonblank")
        seen_crop_ids.add(crop_id)
        provenance = item.get("provenance")
        case_id = _item_case_id(item, provenance)
        if isinstance(case_id, str) and case_id.strip():
            item_by_case.setdefault(case_id, []).append(item)
    candidates = _candidate_kinds(run_data)
    examples = label_set["examples"]
    matched: dict[str, dict[str, Any]] = {}
    unmatched: list[str] = []
    ambiguous: list[str] = []
    for example in examples:
        case_id = example["case_id"]
        case_items = item_by_case.get(case_id, [])
        if not case_items:
            unmatched.append(case_id)
        elif len(case_items) != 1:
            ambiguous.append(case_id)
        else:
            item = case_items[0]
            try:
                _item_lighting(item)
            except ValueError:
                raise EmbedValidationError(
                    "persisted run-item lighting is invalid"
                ) from None
            matched[case_id] = {
                "label": example,
                "item": item,
                "candidates": candidates,
            }

    groups: dict[str, dict[str, object]] = {}
    for lighting in ("day", "night", "unknown"):
        group_examples = [
            matched[case_id]
            for case_id in matched
            if _item_lighting(matched[case_id]["item"]) == lighting
        ]
        groups[lighting] = _shared_group_metrics(group_examples, candidates)
    counts = run_data.get("counts")
    selected_count = (
        counts.get("selected", len(items))
        if isinstance(counts, Mapping)
        else len(items)
    )
    run_id = run_data.get("run_id")
    setup = {
        "run_id": str(run_id) if run_id is not None else None,
        "run_status": run_data.get("status"),
        "model_fingerprint": run_data.get("model_fingerprint"),
        "candidate_set_fingerprint": run_data.get("candidate_set_fingerprint"),
        "scoring_fingerprint": run_data.get("scoring_fingerprint"),
        "config_fingerprint": run_data.get("config_fingerprint"),
        "reference": _run_reference_identity(run_data),
        "threshold": run_data.get("threshold"),
        "candidate_count": len(candidates),
        "matched_case_count": len(matched),
        "unmatched_case_ids": sorted(unmatched),
        "ambiguous_case_ids": sorted(ambiguous),
        "unmatched_case_count": len(unmatched),
        "ambiguous_case_count": len(ambiguous),
        "unlabeled_run_item_count": max(int(selected_count) - len(matched), 0),
        "matched_crop_ids": {
            case_id: record["item"]["crop_id"]
            for case_id, record in sorted(matched.items())
        },
        "publication_ready": _publication_ready(groups, str(label_set["label_role"])),
        "sample_limitations": _sample_limitations(groups, str(label_set["label_role"])),
        "groups": groups,
    }
    return setup, matched


def _shared_group_metrics(
    records: Sequence[Mapping[str, Any]], candidates: Mapping[str, Mapping[str, Any]]
) -> dict[str, object]:
    counts = {
        key: 0
        for key in (
            "labeled_count",
            "eligible_count",
            "completed_count",
            "failed_count",
            "pending_count",
            "unusable_count",
            "species_correct_count",
            "species_incorrect_count",
            "species_assigned_count",
            "category_assigned_count",
            "category_match_count",
            "category_mismatch_count",
            "species_absent_from_candidate_count",
            "out_of_list_count",
            "out_of_list_species_assignment_count",
            "out_of_list_category_assignment_count",
            "out_of_list_unassigned_count",
            "unidentifiable_count",
            "unidentifiable_assigned_count",
            "unidentifiable_unassigned_count",
            "low_quality_count",
            "unassigned_count",
            "category_assessed_count",
        )
    }
    unassigned_reasons: dict[str, int] = {}
    decision_path_counts: dict[str, int] = {}
    errors: list[dict[str, object]] = []
    for record in records:
        label = record["label"]
        item = record["item"]
        counts["labeled_count"] += 1
        truth_kind = label["truth_kind"]
        if truth_kind == "unusable":
            counts["unusable_count"] += 1
            continue
        counts["eligible_count"] += 1
        if truth_kind == "species" and label["expected_taxon_id"] not in candidates:
            counts["species_absent_from_candidate_count"] += 1
        if truth_kind == "out_of_list":
            counts["out_of_list_count"] += 1
        if truth_kind == "unidentifiable":
            counts["unidentifiable_count"] += 1
        status = item.get("status")
        if status in {"completed", "skipped"}:
            decision = item.get("decision")
            if not isinstance(decision, Mapping):
                raise EmbedValidationError("completed run item is missing its decision")
            counts["completed_count"] += 1
            decision_path = decision.get("decision_path", "zero_shot")
            if decision_path not in {
                "zero_shot",
                "reference_match",
                "zero_shot_fallback",
            }:
                raise EmbedValidationError("persisted decision path is invalid")
            decision_path_counts[decision_path] = (
                decision_path_counts.get(decision_path, 0) + 1
            )
            assigned_id = decision.get("assigned_species_id")
            if assigned_id in (None, "unknown"):
                counts["unassigned_count"] += 1
                reason = str(decision.get("reason", "unknown"))
                unassigned_reasons[reason] = unassigned_reasons.get(reason, 0) + 1
                if reason == "low_quality":
                    counts["low_quality_count"] += 1
                if truth_kind == "out_of_list":
                    counts["out_of_list_unassigned_count"] += 1
                if truth_kind == "unidentifiable":
                    counts["unidentifiable_unassigned_count"] += 1
                errors.append(_shared_error(label, item, "unknown", reason))
                continue
            candidate = candidates.get(str(assigned_id))
            if candidate is None:
                raise EmbedValidationError(
                    "decision references a candidate outside its setup"
                )
            if candidate["kind"] == "category":
                counts["category_assigned_count"] += 1
                expected_category = label["expected_category"]
                if expected_category is not None:
                    counts["category_assessed_count"] += 1
                    if candidate.get("category") == expected_category:
                        counts["category_match_count"] += 1
                    else:
                        counts["category_mismatch_count"] += 1
                if truth_kind == "out_of_list":
                    counts["out_of_list_category_assignment_count"] += 1
                if truth_kind == "unidentifiable":
                    counts["unidentifiable_assigned_count"] += 1
                if (
                    expected_category is not None
                    and candidate.get("category") != expected_category
                ):
                    errors.append(
                        _shared_error(
                            label, item, str(assigned_id), "incorrect_category"
                        )
                    )
                continue
            counts["species_assigned_count"] += 1
            if truth_kind == "species" and assigned_id == label["expected_taxon_id"]:
                counts["species_correct_count"] += 1
            else:
                counts["species_incorrect_count"] += 1
                reason = (
                    "incorrect_assignment"
                    if truth_kind == "species"
                    else "assignment_for_non_species_truth"
                )
                errors.append(_shared_error(label, item, str(assigned_id), reason))
            if truth_kind == "out_of_list":
                counts["out_of_list_species_assignment_count"] += 1
            if truth_kind == "unidentifiable":
                counts["unidentifiable_assigned_count"] += 1
        elif status == "failed":
            counts["failed_count"] += 1
            errors.append(
                _shared_error(
                    label,
                    item,
                    "unknown",
                    str(item.get("failure_code") or "processing_failed"),
                )
            )
        elif status == "pending":
            counts["pending_count"] += 1
            errors.append(_shared_error(label, item, "unknown", "pending"))
        else:
            raise EmbedValidationError("persisted run item has an invalid status")
    completed = counts["completed_count"]
    eligible = counts["eligible_count"]
    species_assigned = counts["species_assigned_count"]
    any_assigned = species_assigned + counts["category_assigned_count"]
    return {
        **counts,
        "species_precision": (
            counts["species_correct_count"] / species_assigned
            if species_assigned
            else None
        ),
        "species_assignment_coverage": species_assigned / completed
        if completed
        else None,
        "any_assignment_coverage": any_assigned / completed if completed else None,
        "processing_coverage": completed / eligible if eligible else None,
        "unassigned_reason_counts": unassigned_reasons,
        "decision_path_counts": decision_path_counts,
        "errors": errors,
    }


def _shared_error(
    label: Mapping[str, Any], item: Mapping[str, Any], assigned_id: str, reason: str
) -> dict[str, object]:
    decision = item.get("decision")
    decision = decision if isinstance(decision, Mapping) else {}
    return {
        "case_id": label["case_id"],
        "crop_id": item["crop_id"],
        "truth_kind": label["truth_kind"],
        "expected_taxon_id": label["expected_taxon_id"],
        "assigned_candidate_id": assigned_id,
        "reason": reason,
        "decision_path": decision.get("decision_path", "zero_shot"),
        "reference_set_fingerprint": decision.get("reference_set_fingerprint"),
        "reference_split_mode": decision.get("reference_split_mode"),
    }


def _run_reference_identity(run_data: Mapping[str, Any]) -> dict[str, object] | None:
    config = run_data.get("config")
    reference = config.get("reference") if isinstance(config, Mapping) else None
    if not isinstance(reference, Mapping):
        return None
    return {
        "set_fingerprint": reference.get("set_fingerprint"),
        "split_mode": reference.get("split_mode"),
        "minimum_similarity": reference.get("minimum_similarity"),
        "minimum_agreement": reference.get("minimum_agreement"),
        "algorithm_version": reference.get("algorithm_version"),
    }


def _candidate_kinds(run_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    values = run_data.get("candidates")
    if isinstance(values, Mapping):
        values = values.get("candidates", values.get("species"))
    if not isinstance(values, list) or not values:
        raise EmbedValidationError("selected run has no persisted candidate list")
    result: dict[str, dict[str, Any]] = {}
    for candidate in values:
        if not isinstance(candidate, Mapping):
            raise EmbedValidationError("selected run candidate list is invalid")
        candidate_id = candidate.get("id")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in result
        ):
            raise EmbedValidationError("selected run candidate list is invalid")
        kind = candidate.get("kind", "species")
        category = candidate.get("category")
        if (
            not isinstance(kind, str)
            or kind not in {"species", "category"}
            or (
                kind == "category"
                and (
                    not isinstance(category, str) or category not in {"bird", "mammal"}
                )
            )
        ):
            raise EmbedValidationError("selected run candidate kinds are invalid")
        result[candidate_id] = {"kind": kind, "category": category}
    return result


def _item_case_id(item: Mapping[str, Any], provenance: object) -> str | None:
    case_id = item.get("case_id")
    if isinstance(case_id, str) and case_id.strip():
        return case_id
    if not isinstance(provenance, Mapping):
        return None
    case_id = provenance.get("case_id")
    if isinstance(case_id, str) and case_id.strip():
        return case_id
    content_digest = provenance.get("source_content_sha256")
    frame_number = provenance.get("frame_number")
    detection_id = provenance.get("detection_id")
    box = provenance.get("detection_box_normalized")
    if (
        not isinstance(content_digest, str)
        or len(content_digest) != 64
        or any(character not in "0123456789abcdef" for character in content_digest)
        or type(frame_number) is not int
        or frame_number < 0
        or not isinstance(detection_id, str)
        or not detection_id
        or not isinstance(box, (list, tuple))
        or len(box) != 4
    ):
        return None
    try:
        if any(isinstance(coordinate, bool) for coordinate in box):
            return None
        normalized_box = [float(coordinate) for coordinate in box]
    except TypeError, ValueError, OverflowError:
        return None
    if (
        any(
            not math.isfinite(coordinate) or not 0 <= coordinate <= 1
            for coordinate in normalized_box
        )
        or normalized_box[2] <= normalized_box[0]
        or normalized_box[3] <= normalized_box[1]
    ):
        return None
    identity = {
        "source_content_sha256": content_digest,
        "frame_number": frame_number,
        "detection_id": detection_id,
        "detection_box_normalized": normalized_box,
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def _label_set_identity(
    label_set: Mapping[str, Any], labels_sha256: str
) -> dict[str, object]:
    return {
        "sha256": labels_sha256,
        "role": label_set["label_role"],
        "split_mode": label_set["split_mode"],
        "source_split_sha256": label_set["source_split_sha256"],
        "source_split_count": len(label_set["source_split_keys"]),
        "example_count": len(label_set["examples"]),
    }


def _publication_ready(groups: Mapping[str, Mapping[str, object]], role: str) -> bool:
    return (
        role == "held_out_evaluation"
        and int(groups["day"]["labeled_count"]) >= 10
        and int(groups["night"]["labeled_count"]) >= 10
        and int(groups["day"]["completed_count"]) >= 10
        and int(groups["night"]["completed_count"]) >= 10
    )


def _sample_limitations(
    groups: Mapping[str, Mapping[str, object]], role: str
) -> list[str]:
    limitations = []
    if role != "held_out_evaluation":
        limitations.append("tuning_labels_cannot_support_publication_quality_claims")
    for lighting in ("day", "night"):
        group = groups[lighting]
        if int(group["labeled_count"]) < 10:
            limitations.append(f"fewer_than_10_{lighting}_labels")
        if int(group["completed_count"]) < 10:
            limitations.append(f"fewer_than_10_completed_{lighting}_decisions")
    return limitations


def _paired_changes(
    setups: Sequence[Mapping[str, Any]],
    matches_by_run: Sequence[Mapping[str, Mapping[str, Any]]],
    paired_case_ids: Sequence[str],
) -> list[dict[str, object]]:
    changes: list[dict[str, object]] = []
    for index in range(1, len(setups)):
        baseline_states = {
            case_id: _paired_state(matches_by_run[0][case_id])
            for case_id in paired_case_ids
        }
        candidate_states = {
            case_id: _paired_state(matches_by_run[index][case_id])
            for case_id in paired_case_ids
        }
        fields = ("species_correct", "category_match", "unassigned", "any_assigned")
        outcome_changes: dict[str, dict[str, int]] = {}
        for field in fields:
            result = {
                "false_to_true": 0,
                "true_to_false": 0,
                "unchanged": 0,
                "unavailable": 0,
            }
            for case_id in paired_case_ids:
                before = baseline_states[case_id][field]
                after = candidate_states[case_id][field]
                if before is None or after is None:
                    result["unavailable"] += 1
                elif before == after:
                    result["unchanged"] += 1
                elif after is True:
                    result["false_to_true"] += 1
                else:
                    result["true_to_false"] += 1
            outcome_changes[field] = result
        changes.append(
            {
                "baseline_run_id": setups[0]["run_id"],
                "compared_run_id": setups[index]["run_id"],
                "paired_case_count": len(paired_case_ids),
                "outcomes": outcome_changes,
                "coverage": _paired_coverage(baseline_states, candidate_states),
            }
        )
    return changes


def _paired_state(record: Mapping[str, Any]) -> dict[str, bool | None]:
    label = record["label"]
    item = record["item"]
    decision = item.get("decision")
    if label["truth_kind"] == "unusable":
        return {
            "species_correct": None,
            "category_match": None,
            "unassigned": None,
            "any_assigned": None,
            "species_assigned": None,
            "completed": None,
            "eligible": False,
        }
    if item.get("status") not in {"completed", "skipped"} or not isinstance(
        decision, Mapping
    ):
        return {
            "species_correct": None,
            "category_match": None,
            "unassigned": None,
            "any_assigned": None,
            "species_assigned": None,
            "completed": None,
            "eligible": True,
        }
    assigned_id = decision.get("assigned_species_id")
    candidates = record["candidates"]
    if assigned_id in (None, "unknown"):
        return {
            "species_correct": (False if label["truth_kind"] == "species" else None),
            "category_match": False if label["expected_category"] is not None else None,
            "unassigned": True,
            "any_assigned": False,
            "species_assigned": False,
            "completed": True,
            "eligible": True,
        }
    candidate = candidates.get(str(assigned_id))
    if candidate is None:
        raise EmbedValidationError("decision references a candidate outside its setup")
    category_match = None
    if label["expected_category"] is not None and candidate["kind"] == "category":
        category_match = candidate.get("category") == label["expected_category"]
    return {
        "species_correct": (
            bool(
                label["truth_kind"] == "species"
                and assigned_id == label["expected_taxon_id"]
            )
            if label["truth_kind"] == "species"
            else None
        ),
        "category_match": category_match,
        "unassigned": False,
        "any_assigned": True,
        "species_assigned": candidate["kind"] == "species",
        "completed": True,
        "eligible": True,
    }


def _paired_coverage(
    baseline: Mapping[str, Mapping[str, bool | None]],
    compared: Mapping[str, Mapping[str, bool | None]],
) -> dict[str, float | None]:
    def assignment_coverage(
        states: Mapping[str, Mapping[str, bool | None]], field: str
    ) -> float | None:
        completed = [
            state[field]
            for state in states.values()
            if state["eligible"] is True and state["completed"] is True
        ]
        return (
            sum(value is True for value in completed) / len(completed)
            if completed
            else None
        )

    def processing_coverage(
        states: Mapping[str, Mapping[str, bool | None]],
    ) -> float | None:
        eligible = [state for state in states.values() if state["eligible"] is True]
        return (
            sum(state["completed"] is True for state in eligible) / len(eligible)
            if eligible
            else None
        )

    result: dict[str, float | None] = {}
    for name, field in (
        ("species_assignment", "species_assigned"),
        ("any_assignment", "any_assigned"),
    ):
        before = assignment_coverage(baseline, field)
        after = assignment_coverage(compared, field)
        result[f"baseline_{name}"] = before
        result[f"compared_{name}"] = after
        delta = None
        if before is not None and after is not None:
            delta = after - before
        result[f"{name}_delta"] = delta
    before_processing = processing_coverage(baseline)
    after_processing = processing_coverage(compared)
    result["baseline_processing"] = before_processing
    result["compared_processing"] = after_processing
    result["processing_delta"] = (
        after_processing - before_processing
        if before_processing is not None and after_processing is not None
        else None
    )
    return result


def _shared_warnings() -> list[str]:
    return [
        RELATIVE_CONFIDENCE_WARNING,
        "unfamiliar species may receive high relative scores",
        "classification results may differ substantially between day and night",
    ]


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
