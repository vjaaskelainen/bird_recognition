"""Explicit, deterministic visit-level aggregation of persisted crop decisions."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from bird_recognition.embed.config import canonical_json_bytes
from bird_recognition.embed.evaluation import (
    validate_report_destination,
    write_evaluation_report,
)
from bird_recognition.embed.models import (
    CandidateScore,
    EmbedValidationError,
    SpeciesCandidate,
)
from bird_recognition.embed.scoring import decision_from_score_map


@dataclass(frozen=True, slots=True)
class VisitGroup:
    """One confidently owner-associated set of crops from a single source."""

    visit_id: str
    source_video_id: str
    crop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VisitGroupManifest:
    """Validated external visit groups and their canonical content identity."""

    manifest_fingerprint: str
    groups: tuple[VisitGroup, ...]


def load_visit_group_manifest(path: Path) -> VisitGroupManifest:
    """Load a strict version-1 visit manifest outside all Git repositories."""
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
        if _is_inside_git_repository(resolved):
            raise EmbedValidationError(
                "visit group manifest must be outside every Git repository"
            )
        document = json.loads(
            resolved.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except EmbedValidationError:
        raise
    except OSError, UnicodeError, json.JSONDecodeError, ValueError:
        raise EmbedValidationError(
            "visit group manifest is unreadable or invalid UTF-8 JSON"
        ) from None
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "groups"}
        or type(document["schema_version"]) is not int
        or document["schema_version"] != 1
        or not isinstance(document["groups"], list)
        or not document["groups"]
    ):
        raise EmbedValidationError("visit group manifest has an invalid schema")

    groups: list[VisitGroup] = []
    visit_ids: set[str] = set()
    crop_ids: set[str] = set()
    for value in document["groups"]:
        if not isinstance(value, dict) or set(value) != {
            "visit_id",
            "source_video_id",
            "crop_ids",
            "association_confident",
        }:
            raise EmbedValidationError("visit group has an invalid field set")
        visit_id = value["visit_id"]
        source_video_id = value["source_video_id"]
        members = value["crop_ids"]
        if (
            not isinstance(visit_id, str)
            or not visit_id.strip()
            or not isinstance(source_video_id, str)
            or not source_video_id.strip()
            or type(value["association_confident"]) is not bool
            or value["association_confident"] is not True
            or not isinstance(members, list)
            or len(members) < 2
            or any(
                not isinstance(crop_id, str) or not crop_id.strip()
                for crop_id in members
            )
        ):
            raise EmbedValidationError(
                "visit groups require a confident association and at least two "
                "unique crops"
            )
        visit_id = visit_id.strip()
        source_video_id = source_video_id.strip()
        normalized_members = tuple(sorted(crop_id.strip() for crop_id in members))
        if len(set(normalized_members)) != len(normalized_members):
            raise EmbedValidationError("visit crop IDs must be unique")
        if visit_id in visit_ids:
            raise EmbedValidationError("visit IDs must be unique")
        if crop_ids.intersection(normalized_members):
            raise EmbedValidationError("a crop may belong to at most one visit")
        visit_ids.add(visit_id)
        crop_ids.update(normalized_members)
        groups.append(VisitGroup(visit_id, source_video_id, normalized_members))

    groups.sort(key=lambda group: group.visit_id)
    canonical = {
        "schema_version": 1,
        "groups": [
            {
                "visit_id": group.visit_id,
                "source_video_id": group.source_video_id,
                "crop_ids": list(group.crop_ids),
                "association_confident": True,
            }
            for group in groups
        ],
    }
    fingerprint = hashlib.sha256(canonical_json_bytes(canonical)).hexdigest()
    return VisitGroupManifest(fingerprint, tuple(groups))


def build_visit_report(
    run_data: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
    manifest: VisitGroupManifest,
    *,
    expected_run_id: UUID,
) -> dict[str, object]:
    """Aggregate compatible persisted logits, preserving crop-level results."""
    if str(run_data.get("run_id")) != str(expected_run_id):
        raise EmbedValidationError("selected run ID does not match run data")
    config_fingerprint = run_data.get("config_fingerprint")
    model_fingerprint = run_data.get("model_fingerprint")
    candidate_fingerprint = run_data.get("candidate_set_fingerprint")
    candidate_ids = _candidate_ids(run_data)
    candidate_records = _candidate_records(run_data)
    candidates_by_id = {candidate.id: candidate for candidate in candidate_records}
    threshold = run_data.get("threshold")
    config = run_data.get("config", {})
    if not isinstance(config, Mapping):
        raise EmbedValidationError("selected run configuration is invalid")
    minimum_margin = config.get("minimum_margin")
    if minimum_margin is not None and len(candidate_ids) < 2:
        raise EmbedValidationError("minimum margin requires at least two candidates")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise EmbedValidationError("selected run threshold is invalid")

    item_by_crop: dict[str, Mapping[str, Any]] = {}
    for item in items:
        crop_id = item.get("crop_id")
        if not isinstance(crop_id, str) or not crop_id or crop_id in item_by_crop:
            raise EmbedValidationError("selected run has missing or duplicate crop IDs")
        item_by_crop[crop_id] = item

    visits: list[dict[str, object]] = []
    for group in manifest.groups:
        member_items: list[Mapping[str, Any]] = []
        for crop_id in group.crop_ids:
            item = item_by_crop.get(crop_id)
            if item is None:
                raise EmbedValidationError(
                    "visit references a crop outside the selected run"
                )
            provenance = item.get("provenance")
            decision = item.get("decision")
            if (
                not isinstance(provenance, Mapping)
                or provenance.get("source_id") != group.source_video_id
            ):
                raise EmbedValidationError(
                    "visit group crosses or mismatches source video"
                )
            if (
                item.get("status") not in {"completed", "skipped"}
                or not isinstance(decision, Mapping)
                or decision.get("reason") == "low_quality"
                or not isinstance(decision.get("decision_id"), str)
                or not decision.get("decision_id")
                or decision.get("config_fingerprint", config_fingerprint)
                != config_fingerprint
            ):
                raise EmbedValidationError(
                    "visit member has no compatible completed decision"
                )
            member_items.append(item)

        score_maps = []
        for item in member_items:
            member_scores = _candidate_scores(item["decision"], candidate_ids)
            validated_scores = decision_from_score_map(
                member_scores,
                candidate_records,
                threshold=float(threshold),
                minimum_margin=minimum_margin,
            )
            score_maps.append(tuple(score.logit for score in validated_scores.scores))
        mean_logits = tuple(
            math.fsum(score_map[index] for score_map in score_maps) / len(score_maps)
            for index in range(len(candidate_ids))
        )
        scores = _softmax_score_map(candidate_ids, mean_logits)
        decision = decision_from_score_map(
            scores,
            candidate_records,
            threshold=float(threshold),
            minimum_margin=minimum_margin,
        )
        visits.append(
            {
                "visit_id": group.visit_id,
                "source_video_id": group.source_video_id,
                "crop_ids": list(group.crop_ids),
                "decision_ids": [
                    str(item["decision"].get("decision_id")) for item in member_items
                ],
                "aggregation": "mean-logits-v1",
                "assigned_candidate_id": decision.assigned_species_id,
                "assigned_candidate_kind": (
                    candidates_by_id[decision.assigned_species_id].kind
                    if decision.assigned_species_id is not None
                    else None
                ),
                "assigned_category": (
                    candidates_by_id[decision.assigned_species_id].category
                    if decision.assigned_species_id is not None
                    else None
                ),
                "best_candidate_id": decision.best_candidate_id,
                "confidence": decision.confidence,
                "tied_candidate_ids": list(decision.tied_candidate_ids),
                "reason": decision.reason,
                "candidate_scores": [
                    {
                        "id": score.id,
                        "kind": candidates_by_id[score.id].kind,
                        "category": candidates_by_id[score.id].category,
                        "logit": score.logit,
                        "score": score.score,
                    }
                    for score in decision.scores
                ],
            }
        )

    return {
        "schema_version": 1,
        "report_id": str(uuid4()),
        "created_at": datetime.now(UTC).isoformat(),
        "run_id": str(expected_run_id),
        "config_fingerprint": config_fingerprint,
        "model_fingerprint": model_fingerprint,
        "candidate_set_fingerprint": candidate_fingerprint,
        "visit_group_manifest_fingerprint": manifest.manifest_fingerprint,
        "aggregation": "mean-logits-v1",
        "threshold": threshold,
        "minimum_margin": minimum_margin,
        "visit_count": len(visits),
        "visits": visits,
        "warnings": [
            "Visit results are derived summaries; crop-level decisions are unchanged.",
            "Candidate scores are relative to the selected setup, not calibrated "
            "probabilities.",
        ],
    }


def write_visit_report(report: Mapping[str, object], path: Path) -> Path:
    """Atomically create a new external visit report without overwriting files."""
    target = validate_report_destination(path)
    return write_evaluation_report(report, target)


def _candidate_records(run_data: Mapping[str, Any]) -> tuple[SpeciesCandidate, ...]:
    candidates = run_data.get("candidates")
    if isinstance(candidates, Mapping):
        candidates = candidates.get("candidates", candidates.get("species"))
    if not isinstance(candidates, list) or not candidates:
        raise EmbedValidationError("selected run candidates are unavailable")
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
            for value in candidates
        )
    except KeyError, TypeError, ValueError:
        raise EmbedValidationError("selected run candidates are invalid") from None


def _candidate_ids(run_data: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(candidate.id for candidate in _candidate_records(run_data)))


def _candidate_scores(
    decision: Mapping[str, Any], candidate_ids: tuple[str, ...]
) -> tuple[CandidateScore, ...]:
    values = decision.get("candidate_scores")
    if not isinstance(values, list):
        raise EmbedValidationError("visit member candidate scores are unavailable")
    if (
        any(not isinstance(value, Mapping) for value in values)
        or tuple(value.get("id") for value in values) != candidate_ids
    ):
        raise EmbedValidationError("visit member score map does not match candidates")
    logits = tuple(value.get("logit") for value in values)
    scores = tuple(value.get("score") for value in values)
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in (*logits, *scores)
    ):
        raise EmbedValidationError("visit member scores are invalid")
    return tuple(
        CandidateScore(candidate_id, float(logit), float(score))
        for candidate_id, logit, score in zip(
            candidate_ids, logits, scores, strict=True
        )
    )


def _softmax_score_map(
    candidate_ids: tuple[str, ...], logits: tuple[float, ...]
) -> tuple[CandidateScore, ...]:
    maximum = max(logits)
    exponentials = tuple(math.exp(value - maximum) for value in logits)
    total = math.fsum(exponentials)
    if not math.isfinite(total) or total <= 0:
        raise EmbedValidationError("aggregated candidate scores are invalid")
    return tuple(
        CandidateScore(candidate_id, logit, exponential / total)
        for candidate_id, logit, exponential in zip(
            candidate_ids, logits, exponentials, strict=True
        )
    )


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
