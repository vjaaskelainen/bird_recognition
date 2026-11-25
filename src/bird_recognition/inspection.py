"""Inspection payload enrichment shared by the CLI and HTTP service."""

from __future__ import annotations

from typing import Any


def add_case_ids(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the stable source/frame/detection identity to inspected crops."""
    from bird_recognition.ingest.manifest import stable_case_id

    for item in items:
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            continue
        digest = provenance.get("source_content_sha256")
        frame_number = provenance.get("frame_number")
        detection_id = provenance.get("detection_id")
        box = provenance.get("detection_box_normalized")
        if (
            not isinstance(digest, str)
            or type(frame_number) is not int
            or not isinstance(detection_id, str)
            or not isinstance(box, (list, tuple))
            or len(box) != 4
        ):
            continue
        case_id = stable_case_id(
            digest,
            frame_number,
            detection_id,
            tuple(float(coordinate) for coordinate in box),
        )
        provenance["case_id"] = case_id
        item["case_id"] = case_id
    return items


def _candidate_records(run_data: dict[str, Any]) -> list[dict[str, Any]]:
    values = run_data.get("candidates")
    if isinstance(values, dict):
        values = values.get("candidates", values.get("species"))
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def add_candidate_details(
    run_data: dict[str, Any], items: list[dict[str, Any]]
) -> None:
    """Add candidate metadata to inspected decisions using the saved run setup."""
    records = {record.get("id"): record for record in _candidate_records(run_data)}
    for item in items:
        decision = item.get("decision")
        if not isinstance(decision, dict):
            continue
        assigned_id = decision.get("assigned_species_id")
        candidate = records.get(assigned_id)
        if candidate is not None:
            kind = candidate.get("kind", "species")
            decision["assigned_candidate_kind"] = kind
            decision["assigned_category"] = candidate.get("category")
            decision["assigned_candidate"] = candidate
        scores = decision.get("candidate_scores")
        if isinstance(scores, list):
            for score in scores:
                if isinstance(score, dict) and (record := records.get(score.get("id"))):
                    score["kind"] = record.get("kind", "species")
                    score["category"] = record.get("category")


def build_inspection_payload(
    run_data: dict[str, Any], items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build the same enriched inspection envelope used by the CLI."""
    from bird_recognition.embed.scoring import (
        RELATIVE_CONFIDENCE_WARNING,
        SINGLE_CANDIDATE_WARNING,
    )

    add_case_ids(items)
    candidates = _candidate_records(run_data)
    add_candidate_details(run_data, items)
    warnings = [RELATIVE_CONFIDENCE_WARNING]
    if len(candidates) == 1:
        warnings.append(SINGLE_CANDIDATE_WARNING)
    run_data["warnings"] = warnings
    return {"schema_version": 1, "run": run_data, "items": items}
