from __future__ import annotations


def test_list_filters_and_requires_auth(review_env) -> None:
    client, _, _ = review_env

    everything = client.get("/v1/videos").json()
    assert everything["total"] == 4
    empty = client.get("/v1/videos", params={"status": "no_animals"}).json()
    assert {item["basename"] for item in empty["items"]} == {"b.mp4", "c.mp4"}
    first = empty["items"][0]
    assert first["review_state"] == "unreviewed"
    assert first["path"] == "videos/" + first["basename"]
    assert client.get("/v1/videos", headers={"X-API-Key": "bad"}).status_code == 401
    assert client.get("/v1/videos", params={"limit": 500}).status_code == 422


def test_review_filter_and_paging(review_env) -> None:
    client, store, _ = review_env
    from bird_recognition.review.store import ReviewInput

    store.add_review("b", ReviewInput("confirmed"), {})

    reviewed = client.get("/v1/videos", params={"review": "confirmed"}).json()
    assert [item["basename"] for item in reviewed["items"]] == ["b.mp4"]
    page = client.get("/v1/videos", params={"limit": 1, "offset": 1}).json()
    assert len(page["items"]) == 1 and page["total"] == 4


def test_detail_and_crop_image(review_env) -> None:
    client, _, _ = review_env

    detail = client.get("/v1/videos/a").json()
    assert detail["status"] == "animals"
    crop = detail["crops"][0]
    assert crop["crop_id"] == "c1" and crop["current_correction"] is None
    assert client.get(crop["image_url"]).content == b"jpeg"
    assert client.get("/v1/videos/a/crops/nope/image").status_code == 404
    assert client.get("/v1/videos/zzz").status_code == 404


def test_manifest_unavailable_returns_503(fake_store, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from bird_recognition.api.app import create_app
    from bird_recognition.api.settings import APISettings
    from bird_recognition.review.store import InMemoryReviewStore

    store = InMemoryReviewStore()
    for manifest in (None, tmp_path / "missing.sqlite3"):
        app = create_app(
            APISettings(manifest=manifest),
            review_store_factory=lambda _: store,
        )
        response = TestClient(app).get("/v1/videos")
        assert response.status_code == 503
        assert response.json()["code"] == "manifest_unavailable"
