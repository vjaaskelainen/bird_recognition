from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bird_recognition.embed.models import (
    EmbedValidationError,
    SpeciesCandidate,
    SpeciesCandidateSet,
)


def _candidate_set(
    candidates: tuple[SpeciesCandidate, ...], schema_version: int = 2
) -> SpeciesCandidateSet:
    return SpeciesCandidateSet(
        candidate_set_fingerprint="a" * 64,
        schema_version=schema_version,
        candidates=candidates,
        candidates_json="[]",
        canonical_json="{}",
        created_at=datetime.now(UTC),
    )


def _schema_2_candidates() -> tuple[SpeciesCandidate, ...]:
    return (
        SpeciesCandidate(
            id="broad_bird",
            kind="category",
            common_name="Bird",
            taxonomic_description="Any bird not identified to a listed species",
            category="bird",
        ),
        SpeciesCandidate(
            id="broad_mammal",
            kind="category",
            common_name="Mammal",
            taxonomic_description="Any mammal not identified to a listed species",
            category="mammal",
        ),
        SpeciesCandidate(
            id="great_tit",
            kind="species",
            common_name="Great tit",
            taxonomic_description="Parus major",
        ),
    )


def test_candidate_model_normalizes_common_name_and_legacy_name() -> None:
    candidate = SpeciesCandidate(id=" great_tit ", name=" Great tit ")

    assert candidate.id == "great_tit"
    assert candidate.name == candidate.common_name == "Great tit"
    assert candidate.kind == "species"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"id": " "}, "candidate ID"),
        ({"id": "unknown", "name": "Unknown"}, "candidate ID"),
        ({"id": "bird"}, "name or common name is required"),
        (
            {"id": "bird", "name": "Animal", "common_name": "Bird"},
            "must match",
        ),
        ({"id": "bird", "name": " ", "kind": "species"}, "must not be blank"),
        (
            {
                "id": "bird",
                "name": "Bird",
                "kind": "category",
                "category": "reptile",
            },
            "bird or mammal",
        ),
        (
            {
                "id": "bird",
                "name": "Bird",
                "kind": "species",
                "category": "bird",
            },
            "cannot have a category",
        ),
    ],
)
def test_candidate_model_rejects_invalid_fields(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(EmbedValidationError, match=message):
        SpeciesCandidate(**kwargs)


def test_candidate_set_accepts_schema_1_legacy_species() -> None:
    candidate = SpeciesCandidate(id="raven", name="Common raven")

    assert _candidate_set((candidate,), schema_version=1).candidates == (candidate,)


@pytest.mark.parametrize(
    "candidates",
    [
        (),
        (_schema_2_candidates()[0], _schema_2_candidates()[2]),
        _schema_2_candidates() + (_schema_2_candidates()[0],),
        (
            SpeciesCandidate(
                id="bird-one",
                kind="category",
                common_name="Bird",
                taxonomic_description="Bird",
                category="bird",
            ),
            SpeciesCandidate(
                id="bird-two",
                kind="category",
                common_name="Other bird",
                taxonomic_description="Bird",
                category="bird",
            ),
            SpeciesCandidate(
                id="mammal",
                kind="category",
                common_name="Mammal",
                taxonomic_description="Mammal",
                category="mammal",
            ),
        ),
    ],
)
def test_candidate_set_rejects_missing_or_duplicate_category_kinds(
    candidates: tuple[SpeciesCandidate, ...],
) -> None:
    with pytest.raises(EmbedValidationError):
        _candidate_set(candidates)


def test_candidate_set_rejects_duplicate_ids_and_names() -> None:
    with pytest.raises(EmbedValidationError, match="IDs must be unique"):
        _candidate_set(
            _schema_2_candidates()
            + (
                SpeciesCandidate(
                    id="GREAT_TIT",
                    kind="species",
                    common_name="Blue tit",
                    taxonomic_description="Cyanistes caeruleus",
                ),
            )
        )

    with pytest.raises(EmbedValidationError, match="names must be unique"):
        _candidate_set(
            _schema_2_candidates()
            + (
                SpeciesCandidate(
                    id="other_tit",
                    kind="species",
                    common_name=" GREAT TIT ",
                    taxonomic_description="Another taxon",
                ),
            )
        )
