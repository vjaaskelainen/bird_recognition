from __future__ import annotations

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings
from bird_recognition.api.ui import resolve_ui_dir


def _bundle(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("secret", encoding="utf-8")
    return tmp_path


def _client(ui_dir) -> TestClient:
    return TestClient(create_app(APISettings(api_key="k", ui_dir=ui_dir)))


def test_serves_index_assets_and_fallback_with_security_headers(tmp_path) -> None:
    client = _client(_bundle(tmp_path))
    for path in ("/", "/review", "/videos/some/deep/path"):
        response = client.get(path)
        assert response.status_code == 200
        assert "app" in response.text
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    asset = client.get("/assets/app.js")
    assert asset.text == "console.log(1)"
    assert asset.headers["x-content-type-options"] == "nosniff"
    assert "access-control-allow-origin" not in client.get("/").headers


def test_api_paths_are_not_shadowed(tmp_path) -> None:
    client = _client(_bundle(tmp_path))
    response = client.get("/v1/unknown")
    assert response.status_code == 404
    assert "app" not in response.text


def test_path_traversal_falls_back_to_index(tmp_path) -> None:
    client = _client(_bundle(tmp_path))
    response = client.get("/..%2Fsecret.txt")
    assert "secret" not in response.text


def test_ui_is_absent_without_a_bundle(tmp_path) -> None:
    client = _client(tmp_path / "missing")
    assert client.get("/review").status_code == 404
    assert resolve_ui_dir(tmp_path / "missing") is None


def test_ui_routes_are_not_in_openapi(tmp_path) -> None:
    client = _client(_bundle(tmp_path))
    assert not any(
        not path.startswith("/v1")
        for path in client.get("/openapi.json").json()["paths"]
    )
