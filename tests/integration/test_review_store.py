from __future__ import annotations

import psycopg
import pytest

from bird_recognition.embed.migrate import apply_pending_migrations
from bird_recognition.review.store import (
    AlreadyUndoneError,
    PgReviewStore,
    ReviewInput,
)
from tests.integration.embed import conftest as embed_fixtures

database_url = embed_fixtures.database_url
disposable_embed_schema = embed_fixtures.disposable_embed_schema


@pytest.fixture
def store(disposable_embed_schema: str) -> PgReviewStore:
    with psycopg.connect(disposable_embed_schema, autocommit=True) as connection:
        apply_pending_migrations(connection)
    return PgReviewStore(disposable_embed_schema)


def test_reviews_undo_fall_back_and_are_append_only(
    store: PgReviewStore, disposable_embed_schema: str
) -> None:
    first = store.add_review("s1", ReviewInput("confirmed"), {"status": "no_animals"})
    second = store.add_review(
        "s1", ReviewInput("corrected", "species_present", ("robin",)), {}
    )

    assert store.current("s1").review_id == second.review_id
    store.undo(second.review_id)
    assert store.current("s1").review_id == first.review_id
    assert store.review_states() == {"s1": "confirmed"}
    with pytest.raises(AlreadyUndoneError):
        store.undo(second.review_id)
    assert [item.undone for item in store.history("s1")] == [True, False]

    with psycopg.connect(disposable_embed_schema) as connection:
        with pytest.raises(psycopg.errors.RaiseException):
            connection.execute("UPDATE bird_embed.video_review SET note='x'")


def test_bulk_and_corrections(store: PgReviewStore) -> None:
    bulk_id, records = store.add_bulk([("a", {}), ("b", {})])
    assert {item.bulk_id for item in records} == {bulk_id}

    store.set_correction("c1", "a", "species", "robin")
    store.set_correction("c1", "a", "out_of_list", None)
    assert store.current_corrections("a")["c1"].truth_kind == "out_of_list"
    store.clear_correction("c1")
    assert store.current_corrections("a")["c1"].species_id == "robin"
