from __future__ import annotations

import pytest

from bird_recognition.review.store import (
    AlreadyUndoneError,
    InMemoryReviewStore,
    ReviewInput,
    ReviewNotFoundError,
    ReviewValidationError,
    validate_correction,
    validate_review,
)


def test_confirmation_rejects_correction_fields() -> None:
    validate_review(ReviewInput("confirmed"))
    with pytest.raises(ReviewValidationError):
        validate_review(ReviewInput("confirmed", correction_kind="no_animal"))


@pytest.mark.parametrize(
    "data",
    [
        ReviewInput("corrected"),
        ReviewInput("corrected", "species_present"),
        ReviewInput("corrected", "animal_missed"),
        ReviewInput("corrected", "animal_missed", missed_times=(-1.0,)),
        ReviewInput("corrected", "no_animal", species=("x",)),
        ReviewInput("corrected", "no_animal", note="x" * 2001),
        ReviewInput("bogus"),
    ],
)
def test_invalid_corrections_rejected(data: ReviewInput) -> None:
    with pytest.raises(ReviewValidationError):
        validate_review(data)


def test_missed_time_beyond_duration_rejected() -> None:
    data = ReviewInput("corrected", "animal_missed", missed_times=(50.0,))
    with pytest.raises(ReviewValidationError):
        validate_review(data, duration=10.0)


def test_crop_correction_rules() -> None:
    validate_correction("species", "robin")
    validate_correction("unidentifiable", None)
    with pytest.raises(ReviewValidationError):
        validate_correction("species", None)
    with pytest.raises(ReviewValidationError):
        validate_correction("out_of_list", "robin")


def test_undo_falls_back_to_previous_review() -> None:
    store = InMemoryReviewStore()
    first = store.add_review("s", ReviewInput("confirmed"), {})
    second = store.add_review(
        "s", ReviewInput("corrected", "no_animal"), {"status": "animals"}
    )
    assert store.current("s").review_id == second.review_id
    store.undo(second.review_id)
    assert store.current("s").review_id == first.review_id
    assert store.review_states() == {"s": "confirmed"}
    store.undo(first.review_id)
    assert store.current("s") is None
    assert store.review_states() == {}
    with pytest.raises(AlreadyUndoneError):
        store.undo(first.review_id)
    with pytest.raises(ReviewNotFoundError):
        store.undo("missing")


def test_bulk_shares_id_and_corrections_clear() -> None:
    store = InMemoryReviewStore()
    bulk_id, records = store.add_bulk([("a", {}), ("b", {})])
    assert {r.bulk_id for r in records} == {bulk_id}
    store.set_correction("c1", "a", "species", "robin")
    store.set_correction("c1", "a", "unidentifiable", None)
    assert store.current_corrections("a")["c1"].truth_kind == "unidentifiable"
    store.clear_correction("c1")
    assert store.current_corrections("a")["c1"].truth_kind == "species"
    store.clear_correction("c1")
    assert "c1" not in store.current_corrections("a")
    with pytest.raises(ReviewNotFoundError):
        store.clear_correction("c1")
