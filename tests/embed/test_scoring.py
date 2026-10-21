from __future__ import annotations

import math
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from bird_recognition.embed.models import (
    EmbedValidationError,
    SpeciesCandidate,
    SpeciesDecision,
)
from bird_recognition.embed.scoring import score_embeddings, validate_decision


@pytest.mark.parametrize("threshold", [0.5, 0.5000000001, 0.4999999999])
def test_score_embeddings_uses_stable_float64_softmax_and_checkpoint_scale(
    threshold: float,
) -> None:
    result = score_embeddings(
        (1.0, 0.0),
        ((1.0, 0.0), (0.0, 1.0)),
        (SpeciesCandidate("a", "A"), SpeciesCandidate("b", "B")),
        logit_scale=2.0,
        threshold=threshold,
    )

    assert result.scores[0].logit == 2.0
    assert result.scores[1].logit == 0.0
    assert result.scores[0].score == pytest.approx(1 / (1 + math.exp(-2)))
    assert sum(score.score for score in result.scores) == pytest.approx(1.0)
    assert result.assigned_species_id == (
        "a" if result.confidence >= threshold else None
    )


def test_score_embeddings_assigns_unique_best_at_threshold_equality() -> None:
    result = score_embeddings(
        (1.0, 0.0),
        ((1.0, 0.0), (0.0, 1.0)),
        (SpeciesCandidate("a", "A"), SpeciesCandidate("b", "B")),
        logit_scale=1.0,
        threshold=1 / (1 + math.exp(-1)),
    )

    assert result.assigned_species_id == "a"
    assert result.best_candidate_id == "a"
    assert result.reason == "assigned"


def test_score_embeddings_keeps_exact_ties_unknown_and_candidate_scores() -> None:
    result = score_embeddings(
        (1.0, 0.0),
        ((0.8, 0.6), (0.0, 1.0), (0.8, -0.6)),
        (
            SpeciesCandidate("c", "C"),
            SpeciesCandidate("a", "A"),
            SpeciesCandidate("b", "B"),
        ),
        logit_scale=1.0,
        threshold=0.99,
    )

    assert result.assigned_species_id is None
    assert result.best_candidate_id is None
    assert result.tied_candidate_ids == ("b", "c")
    assert result.reason == "exact_tie"
    assert tuple(score.id for score in result.scores) == ("a", "b", "c")
    assert result.scores[1].score == result.scores[2].score


def test_score_embeddings_does_not_treat_rounded_or_near_logits_as_ties() -> None:
    result = score_embeddings(
        (1.0, 0.0),
        ((1.0, 0.0), (1.0 - 1e-12, 0.0)),
        (SpeciesCandidate("a", "A"), SpeciesCandidate("b", "B")),
        logit_scale=1.0,
        threshold=0.0,
    )

    assert result.reason == "assigned"
    assert result.best_candidate_id == "a"
    assert result.tied_candidate_ids == ()


def test_score_embeddings_retains_below_threshold_unique_best_as_unknown() -> None:
    result = score_embeddings(
        (1.0, 0.0),
        ((0.0, 1.0), (1.0, 0.0)),
        (SpeciesCandidate("a", "A"), SpeciesCandidate("b", "B")),
        logit_scale=1.0,
        threshold=0.75,
    )

    assert result.assigned_species_id is None
    assert result.best_candidate_id == "b"
    assert result.reason == "below_threshold"
    assert result.confidence == max(score.score for score in result.scores)


def test_score_embeddings_single_candidate_warns_and_assigns() -> None:
    result = score_embeddings(
        (1.0, 0.0),
        ((0.0, 1.0),),
        (SpeciesCandidate("a", "A"),),
        logit_scale=1.0,
        threshold=1.0,
    )

    assert result.assigned_species_id == "a"
    assert result.confidence == 1.0
    assert len(result.warnings) == 2


def test_validate_decision_rejects_nonfinite_scores_and_threshold_disagreement() -> (
    None
):
    candidates = (SpeciesCandidate("a", "A"), SpeciesCandidate("b", "B"))
    result = score_embeddings(
        (1.0, 0.0),
        ((1.0, 0.0), (0.0, 1.0)),
        candidates,
        logit_scale=1.0,
        threshold=0.5,
    )
    decision = SpeciesDecision(
        decision_id=uuid4(),
        representation_id=uuid4(),
        config_fingerprint="1" * 64,
        assigned_species_id=result.assigned_species_id,
        best_candidate_id=result.best_candidate_id,
        confidence=result.confidence,
        tied_candidate_ids=result.tied_candidate_ids,
        candidate_scores=result.scores,
        reason=result.reason,
        warnings=result.warnings,
        processed_at=datetime.now(UTC),
        created_run_id=uuid4(),
    )

    validate_decision(decision, candidates, threshold=0.5)
    invalid_scores = replace(
        decision,
        candidate_scores=(
            replace(decision.candidate_scores[0], score=float("nan")),
            decision.candidate_scores[1],
        ),
    )

    with pytest.raises(EmbedValidationError):
        validate_decision(invalid_scores, candidates, threshold=0.5)
    with pytest.raises(EmbedValidationError):
        validate_decision(decision, candidates, threshold=0.9)


@pytest.mark.parametrize(
    ("image", "texts", "scale"),
    [
        ((1.0, 0.0), ((1.0,),), 1.0),
        ((0.0, 0.0), ((1.0, 0.0),), 1.0),
        ((1.0, 0.0), ((0.0, 0.0),), 1.0),
        ((float("nan"), 0.0), ((1.0, 0.0),), 1.0),
        ((1.0, 0.0), ((float("inf"), 0.0),), 1.0),
        ((1.0, 0.0), ((1.0, 0.0),), float("nan")),
        ((1.0, 0.0), ((1.0, 0.0),), 0.0),
        ((1.0, 0.0), ((1.0, 0.0),), -1.0),
    ],
)
def test_score_embeddings_rejects_invalid_vectors_and_scale(
    image: tuple[float, ...], texts: tuple[tuple[float, ...], ...], scale: float
) -> None:
    with pytest.raises(EmbedValidationError):
        score_embeddings(
            image,
            texts,
            (SpeciesCandidate("a", "A"),),
            logit_scale=scale,
            threshold=0.5,
        )
