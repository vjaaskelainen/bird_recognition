from __future__ import annotations


def post_review(client, source_id: str, **body):
    return client.post(f"/v1/videos/{source_id}/reviews", json=body)


def test_create_history_and_undo(review_env) -> None:
    client, _, _ = review_env

    first = post_review(client, "b", outcome="confirmed")
    assert first.status_code == 201
    assert first.json()["auto_result"]["status"] == "no_animals"
    second = post_review(
        client, "b", outcome="corrected", correction_kind="no_animal", note="x"
    )
    assert second.status_code == 201
    history = client.get("/v1/videos/b/reviews").json()
    assert [item["outcome"] for item in history] == ["corrected", "confirmed"]
    assert client.get("/v1/videos/b").json()["review_state"] == "corrected"

    undo = client.post(f"/v1/reviews/{second.json()['review_id']}/undo")
    assert undo.status_code == 204
    assert client.get("/v1/videos/b").json()["review_state"] == "confirmed"
    again = client.post(f"/v1/reviews/{second.json()['review_id']}/undo")
    assert again.status_code == 409 and again.json()["code"] == "already_undone"
    assert client.post("/v1/reviews/missing/undo").status_code == 404


def test_invalid_review_combinations_are_422(review_env) -> None:
    client, _, _ = review_env

    assert post_review(client, "b", outcome="corrected").status_code == 422
    bad = post_review(client, "b", outcome="confirmed", species=["x"])
    assert bad.status_code == 422
    missed = post_review(
        client, "b", outcome="corrected", correction_kind="animal_missed"
    )
    assert missed.status_code == 422
    assert post_review(client, "zzz", outcome="confirmed").status_code == 404


def test_bulk_only_for_no_animals(review_env) -> None:
    client, _, _ = review_env

    rejected = client.post(
        "/v1/reviews/bulk",
        json={"source_ids": ["b", "a", "zzz"], "outcome": "confirmed"},
    )
    assert rejected.status_code == 422
    assert {e["source_id"] for e in rejected.json()["errors"]} == {"a", "zzz"}
    assert client.get("/v1/videos/b").json()["review_state"] == "unreviewed"

    accepted = client.post(
        "/v1/reviews/bulk", json={"source_ids": ["b", "c"], "outcome": "confirmed"}
    )
    assert accepted.status_code == 201
    assert len(accepted.json()["reviews"]) == 2
    too_many = client.post(
        "/v1/reviews/bulk",
        json={"source_ids": [str(i) for i in range(501)], "outcome": "confirmed"},
    )
    assert too_many.status_code == 422


def test_crop_correction_put_and_delete(review_env) -> None:
    client, _, _ = review_env

    body = {"source_id": "a", "truth_kind": "species", "species_id": "robin"}
    assert client.put("/v1/crops/c1/correction", json=body).status_code == 201
    crop = client.get("/v1/videos/a").json()["crops"][0]
    assert crop["current_correction"]["species_id"] == "robin"
    invalid = {"source_id": "a", "truth_kind": "species"}
    assert client.put("/v1/crops/c1/correction", json=invalid).status_code == 422
    assert client.put("/v1/crops/zzz/correction", json=body).status_code == 404
    assert client.delete("/v1/crops/c1/correction").status_code == 204
    assert client.delete("/v1/crops/c1/correction").status_code == 404


def test_queue_orders_and_excludes(review_env) -> None:
    client, _, _ = review_env

    queue = client.get("/v1/videos/queue", params={"limit": 3}).json()
    assert [item["source_id"] for item in queue["items"]] == ["c", "b", "a"]
    assert queue["remaining"] == 3
    skipped = client.get("/v1/videos/queue", params={"exclude": ["c"]}).json()
    assert [item["source_id"] for item in skipped["items"]] == ["b", "a"]
