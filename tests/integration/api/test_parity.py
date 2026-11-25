from __future__ import annotations

import json
import os
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings
from bird_recognition.cli import main
from bird_recognition.embed.models import StorageError
from bird_recognition.embed.storage import PgVectorStore

_SEARCH_QUERIES = (
    "bird at a feeder",
    "small bird on a branch",
    "bird facing the camera",
    "bird in daylight",
    "bird at night",
    "dark feathers",
    "brown bird",
    "bird near vegetation",
    "bird with a long tail",
    "bird in a garden",
)


@pytest.mark.real_database
def test_http_search_inspect_and_visits_match_cli_payloads() -> None:
    database_url = os.environ.get("BIRD_RECOGNITION_TEST_DATABASE_URL")
    model_value = os.environ.get("BIRD_RECOGNITION_BIOCLIP_MODEL_DIR")
    groups_value = os.environ.get("BIRD_RECOGNITION_TEST_VISIT_GROUPS")
    if not database_url or not model_value or not groups_value:
        pytest.skip(
            "disposable database, local model, and reviewed visit manifest are required"
        )
    model_dir = Path(model_value).expanduser().resolve(strict=True)
    groups_path = Path(groups_value).expanduser().resolve(strict=True)
    store = PgVectorStore(database_url)
    try:
        try:
            store.preflight(read_only=True)
        except StorageError:
            pytest.skip("the disposable database has no initialized embedding schema")
        runs = store.list_runs()
    finally:
        store.close()
    if not runs:
        pytest.skip("the disposable database has no indexed reference run")
    run = next(
        (item for item in runs if item["status"] in {"complete", "no_input"}),
        None,
    )
    if run is None:
        pytest.skip("the disposable database has no complete indexed run")
    run_id = run["run_id"]
    app = create_app(
        APISettings(database_url=database_url, model_dir=model_dir),
    )

    with TestClient(app) as client:
        for query in _SEARCH_QUERIES:
            response = client.post(
                "/v1/search",
                json={"run_id": run_id, "query": query, "limit": 5},
            )
            assert response.status_code == 200
            cli_payload = _run_cli_json(
                [
                    "search",
                    query,
                    "--run-id",
                    run_id,
                    "--database-url",
                    database_url,
                    "--model-dir",
                    str(model_dir),
                    "--json",
                ]
            )
            assert response.json() == cli_payload

        inspect_response = client.get(f"/v1/runs/{run_id}")
        cli_inspection = _run_cli_json(
            [
                "inspect",
                "--run-id",
                run_id,
                "--database-url",
                database_url,
                "--json",
            ]
        )
        assert inspect_response.status_code == 200
        assert inspect_response.json() == cli_inspection

        with tempfile.TemporaryDirectory() as output_directory:
            cli_visits = _run_cli_json(
                [
                    "aggregate-visits",
                    "--run-id",
                    run_id,
                    "--groups",
                    str(groups_path),
                    "--output",
                    str(Path(output_directory) / "visits.json"),
                    "--database-url",
                    database_url,
                    "--json",
                ]
            )
        visit_response = client.get(
            f"/v1/visits?run_id={run_id}&groups={quote(str(groups_path), safe='')}"
        )
        assert visit_response.status_code == 200
        for key, value in cli_visits["report"].items():
            if key not in {"report_id", "created_at"}:
                assert visit_response.json()[key] == value


def _run_cli_json(arguments: list[str]) -> dict[str, object]:
    output = StringIO()
    with redirect_stdout(output):
        exit_code = main(arguments)
    assert exit_code == 0
    return json.loads(output.getvalue())
