"""Pure scoring and decision validation for candidate-relative species tags."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from bird_recognition.embed.models import (
    CandidateScore,
    EmbedValidationError,
    SpeciesCandidate,
    SpeciesDecision,
    Vector,
)

RELATIVE_CONFIDENCE_WARNING = (
    "Confidence is a relative score within the selected candidate set, not a "
    "calibrated probability of biological correctness or the ingestion detector's "
    "confidence. Scores from different candidate sets are not directly comparable. "
    "Out-of-list animals can score highly."
)
SINGLE_CANDIDATE_WARNING = (
    "A single candidate always receives a score of 1.0 and cannot be interpreted "
    "as calibrated confidence."
)
VECTOR_NORM_TOLERANCE = 1e-5
SCORE_SUM_TOLERANCE = 1e-12


@dataclass(frozen=True, slots=True)
class ScoreResult:
    """Candidate scores and the corresponding threshold/tie decision."""

    assigned_species_id: str | None
    best_candidate_id: str | None
    confidence: float | None
    tied_candidate_ids: tuple[str, ...]
    scores: tuple[CandidateScore, ...]
    reason: str
    warnings: tuple[str, ...]


def score_embeddings(
    image_vector: Sequence[float],
    text_vectors: Sequence[Sequence[float]],
    candidates: Sequence[SpeciesCandidate],
    *,
    logit_scale: float,
    threshold: float,
) -> ScoreResult:
    """Score normalized embeddings and choose a candidate or unknown."""
    if not candidates or len(candidates) != len(text_vectors):
        raise EmbedValidationError("candidate and text-vector counts must match")
    if (
        isinstance(logit_scale, bool)
        or not isinstance(logit_scale, (int, float))
        or not math.isfinite(logit_scale)
        or logit_scale <= 0
    ):
        raise EmbedValidationError("logit scale must be finite and positive")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise EmbedValidationError("threshold must be finite and within [0, 1]")
    ordered_pairs = sorted(
        zip(candidates, text_vectors, strict=True), key=lambda item: item[0].id
    )
    ordered = [candidate for candidate, _ in ordered_pairs]
    if len({candidate.id for candidate in ordered}) != len(ordered):
        raise EmbedValidationError("candidate identifiers must be unique")
    if any(not candidate.id or not candidate.name for candidate in ordered):
        raise EmbedValidationError("candidate identifiers and names are required")

    image = _validated_unit_vector(image_vector)
    text_rows = [_validated_unit_vector(vector) for _, vector in ordered_pairs]
    if any(vector.size != image.size for vector in text_rows):
        raise EmbedValidationError("image and text vector dimensions must match")
    text = np.stack(text_rows)

    with np.errstate(over="ignore", invalid="ignore"):
        logits = np.asarray(text @ image * np.float64(logit_scale), dtype=np.float64)
    if logits.shape != (len(ordered),) or not np.isfinite(logits).all():
        raise EmbedValidationError("candidate logits must be finite")
    exponentials = np.exp(logits - np.max(logits))
    scores = exponentials / np.sum(exponentials, dtype=np.float64)
    return decision_from_score_map(
        tuple(
            CandidateScore(candidate.id, float(logits[index]), float(scores[index]))
            for index, candidate in enumerate(ordered)
        ),
        ordered,
        threshold=threshold,
    )


def decision_from_score_map(
    scores: Sequence[CandidateScore],
    candidates: Sequence[SpeciesCandidate],
    *,
    threshold: float,
) -> ScoreResult:
    """Validate persisted logits/scores and apply a threshold-only retag."""
    ordered = tuple(sorted(candidates, key=lambda candidate: candidate.id))
    if not ordered or tuple(score.id for score in scores) != tuple(
        candidate.id for candidate in ordered
    ):
        raise EmbedValidationError("stored score map does not match candidates")
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 <= threshold <= 1
    ):
        raise EmbedValidationError("threshold must be finite and within [0, 1]")
    logits = np.asarray([score.logit for score in scores], dtype=np.float64)
    persisted_scores = np.asarray([score.score for score in scores], dtype=np.float64)
    if (
        logits.shape != (len(ordered),)
        or not np.isfinite(logits).all()
        or not np.isfinite(persisted_scores).all()
        or np.any(persisted_scores < 0)
        or np.any(persisted_scores > 1)
        or not math.isclose(float(np.sum(persisted_scores)), 1.0, abs_tol=1e-9)
    ):
        raise EmbedValidationError("stored score map is invalid")
    with np.errstate(over="ignore", invalid="ignore"):
        exponentials = np.exp(logits - np.max(logits))
    denominator = np.sum(exponentials, dtype=np.float64)
    normalized_scores = exponentials / denominator
    if (
        not np.isfinite(normalized_scores).all()
        or np.any(normalized_scores < 0)
        or np.any(normalized_scores > 1)
        or not math.isclose(
            float(np.sum(normalized_scores)), 1.0, abs_tol=SCORE_SUM_TOLERANCE
        )
        or not np.allclose(normalized_scores, persisted_scores, rtol=0, atol=1e-12)
    ):
        raise EmbedValidationError("stored scores disagree with their logits")

    maximum = np.max(logits)
    tied_indices = tuple(
        index for index, value in enumerate(logits) if value == maximum
    )
    candidate_scores = tuple(
        CandidateScore(
            id=candidate.id,
            logit=float(logits[index]),
            score=float(normalized_scores[index]),
        )
        for index, candidate in enumerate(ordered)
    )
    confidence = max(score.score for score in candidate_scores)
    warnings = (RELATIVE_CONFIDENCE_WARNING,)
    if len(ordered) == 1:
        warnings += (SINGLE_CANDIDATE_WARNING,)
    if len(tied_indices) > 1:
        return ScoreResult(
            assigned_species_id=None,
            best_candidate_id=None,
            confidence=confidence,
            tied_candidate_ids=tuple(ordered[index].id for index in tied_indices),
            scores=candidate_scores,
            reason="exact_tie",
            warnings=warnings,
        )

    best_id = ordered[tied_indices[0]].id
    assigned_id = best_id if confidence >= threshold else None
    return ScoreResult(
        assigned_species_id=assigned_id,
        best_candidate_id=best_id,
        confidence=confidence,
        tied_candidate_ids=(),
        scores=candidate_scores,
        reason="assigned" if assigned_id is not None else "below_threshold",
        warnings=warnings,
    )


def validate_normalized_vector(vector: Sequence[float]) -> Vector:
    """Return a finite unit vector or raise a validation error."""
    return tuple(float(value) for value in _validated_unit_vector(vector))


def validate_decision(
    decision: SpeciesDecision,
    candidates: Sequence[SpeciesCandidate],
    *,
    threshold: float | None = None,
) -> None:
    """Validate decision fields and all persisted scores against candidates."""
    candidate_ids = tuple(sorted(candidate.id for candidate in candidates))
    scores = decision.candidate_scores
    if decision.reason == "low_quality":
        if (
            decision.assigned_species_id is not None
            or decision.best_candidate_id is not None
            or decision.tied_candidate_ids
            or decision.confidence is not None
            or scores
        ):
            raise EmbedValidationError(
                "low-quality decisions must be unassigned and scoreless"
            )
        return
    if tuple(score.id for score in scores) != candidate_ids:
        raise EmbedValidationError(
            "decision scores must contain every candidate in ID order"
        )
    values = tuple(score.score for score in scores)
    if any(
        not math.isfinite(score.logit)
        or not math.isfinite(score.score)
        or not 0 <= score.score <= 1
        for score in scores
    ) or not math.isclose(math.fsum(values), 1.0, abs_tol=1e-9):
        raise EmbedValidationError("decision candidate scores are invalid")
    maximum = max(score.logit for score in scores)
    tied = tuple(score.id for score in scores if score.logit == maximum)
    confidence = max(values)
    if (
        decision.confidence is None
        or not math.isfinite(decision.confidence)
        or not 0 <= decision.confidence <= 1
    ):
        raise EmbedValidationError(
            "decision confidence must be finite and within [0, 1]"
        )
    if not math.isclose(decision.confidence, confidence, abs_tol=1e-12):
        raise EmbedValidationError("decision confidence does not match its score map")
    if len(tied) > 1:
        valid = (
            decision.best_candidate_id is None
            and decision.tied_candidate_ids == tied
            and (
                decision.reason == "exact_tie"
                and decision.assigned_species_id is None
                or decision.reason == "reference_match"
                and decision.decision_path == "reference_match"
                and decision.assigned_species_id in candidate_ids
            )
        )
    else:
        best_id = tied[0]
        valid = (
            decision.best_candidate_id == best_id
            and not decision.tied_candidate_ids
            and (
                decision.reason == "assigned"
                and decision.assigned_species_id == best_id
                or decision.reason == "below_threshold"
                and decision.assigned_species_id is None
                or decision.reason == "reference_match"
                and decision.decision_path == "reference_match"
                and decision.assigned_species_id in candidate_ids
            )
        )
    if not valid:
        raise EmbedValidationError("decision fields disagree with scores and reason")
    if (
        decision.assigned_species_id not in candidate_ids
        and decision.assigned_species_id is not None
    ):
        raise EmbedValidationError("assigned identifier is not a candidate")
    if (
        decision.best_candidate_id not in candidate_ids
        and decision.best_candidate_id is not None
    ):
        raise EmbedValidationError("best identifier is not a candidate")
    if threshold is not None:
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise EmbedValidationError("decision threshold is invalid")
        if len(tied) == 1 and (
            decision.reason == "assigned"
            and confidence < threshold
            or decision.reason == "below_threshold"
            and confidence >= threshold
        ):
            raise EmbedValidationError("decision reason disagrees with threshold")
    if (
        decision.reason == "reference_match"
        and decision.decision_path != "reference_match"
    ):
        raise EmbedValidationError(
            "reference-match reason requires reference provenance"
        )
    if (
        decision.reason != "reference_match"
        and decision.decision_path == "reference_match"
    ):
        raise EmbedValidationError("reference decision path requires a reference match")
    required_warnings = [RELATIVE_CONFIDENCE_WARNING]
    if len(candidate_ids) == 1:
        required_warnings.append(SINGLE_CANDIDATE_WARNING)
    if any(warning not in decision.warnings for warning in required_warnings):
        raise EmbedValidationError("decision is missing required confidence warnings")


def _validated_unit_vector(vector: Sequence[float]) -> np.ndarray:
    if any(isinstance(value, bool) for value in vector):
        raise EmbedValidationError("embedding vector values must be numeric")
    try:
        values = np.asarray(vector, dtype=np.float64)
    except TypeError, ValueError, OverflowError:
        raise EmbedValidationError("embedding vector is invalid") from None
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise EmbedValidationError(
            "embedding vector must be finite and one-dimensional"
        )
    norm = float(np.linalg.norm(values))
    if (
        not math.isfinite(norm)
        or norm == 0
        or not math.isclose(norm, 1.0, rel_tol=0, abs_tol=VECTOR_NORM_TOLERANCE)
    ):
        raise EmbedValidationError("embedding vector must be L2-normalized")
    return values
