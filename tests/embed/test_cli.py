from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from bird_recognition.cli import _build_parser, main
from bird_recognition.embed.models import RunStatus


def test_cli_parser_exposes_story_one_commands_and_exact_selection_options() -> None:
    parser = _build_parser()
    actions = next(
        action
        for action in parser._actions
        if getattr(action, "dest", None) == "command"
    )

    assert set(actions.choices) >= {
        "database-init",
        "index",
        "inspect",
        "evaluate-species",
    }
    with pytest.raises(SystemExit) as usage_error:
        parser.parse_args(["inspect"])
    assert usage_error.value.code == 2


def test_cli_existing_help_does_not_import_bioclip() -> None:
    sys.modules.pop("bird_recognition.embed.bioclip", None)

    with pytest.raises(SystemExit) as help_exit:
        main(["extract-frame", "--help"])

    assert help_exit.value.code == 0
    assert "bird_recognition.embed.bioclip" not in sys.modules


@pytest.mark.parametrize(
    "command", [["--help"], ["ingest", "--help"], ["extract-frame", "--help"]]
)
def test_cli_legacy_help_does_not_load_bioclip(command: list[str]) -> None:
    sys.modules.pop("bird_recognition.embed.bioclip", None)

    with pytest.raises(SystemExit) as help_exit:
        main(command)

    assert help_exit.value.code == 0
    assert "bird_recognition.embed.bioclip" not in sys.modules


def test_cli_inspect_lists_runs_as_json_without_model_or_manifest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def list_runs(self) -> list[dict[str, object]]:
            return [{"run_id": "run-1", "status": "complete"}]

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)

    result = main(
        [
            "inspect",
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--list-runs",
            "--json",
        ]
    )
    output = capsys.readouterr()

    assert result == 0
    assert output.err == ""
    assert json.loads(output.out) == {
        "schema_version": 1,
        "runs": [{"run_id": "run-1", "status": "complete"}],
    }


def test_cli_inspect_selects_run_and_crop_without_assets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    selected_run_id = uuid4()

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, run_id: UUID, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            assert run_id == selected_run_id
            assert crop_id == "crop-1"
            return (
                {"run_id": str(run_id), "status": "complete"},
                [{"crop_id": crop_id, "status": "skipped", "decision": {"id": "old"}}],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    result = main(
        [
            "inspect",
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--run-id",
            str(selected_run_id),
            "--crop-id",
            "crop-1",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert json.loads(output.out)["items"][0]["status"] == "skipped"


def test_cli_index_writer_preflight_emits_usage_exit_and_no_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from bird_recognition.embed import pipeline
    from bird_recognition.embed.models import PreflightError

    def fail_preflight(*args: object, **kwargs: object) -> None:
        raise PreflightError("writer_busy: another index writer is active")

    monkeypatch.setattr(pipeline, "index_manifest", fail_preflight)
    manifest = tmp_path / "manifest.sqlite3"
    manifest.touch()
    result = main(
        [
            "index",
            "--manifest",
            str(manifest),
            "--model-dir",
            str(tmp_path / "model"),
            "--species-list",
            str(tmp_path / "species.json"),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert result == 2
    assert output.err == ""
    assert payload["status"] == "preflight_failure"
    assert payload["code"] == "writer_busy"
    assert payload["run_id"] is None


def test_cli_inspect_requires_run_or_list_and_crop_requires_run() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as missing_selection:
        parser.parse_args(
            ["inspect", "--database-url", "postgresql://localhost/bird_db"]
        )

    assert missing_selection.value.code == 2
    with pytest.raises(SystemExit) as crop_without_run:
        main(
            [
                "inspect",
                "--database-url",
                "postgresql://localhost/bird_db",
                "--crop-id",
                "crop-1",
                "--list-runs",
            ]
        )
    assert crop_without_run.value.code == 2


def test_cli_database_init_emits_versioned_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    monkeypatch.setattr(
        storage,
        "initialize_database",
        lambda database_url: SimpleNamespace(
            schema_version=1, vector_available=True, changes_applied=True
        ),
    )

    result = main(
        [
            "database-init",
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 0
    assert output.err == ""
    assert json.loads(output.out)["database_schema_version"] == 1


@pytest.mark.parametrize(
    ("status", "expected_exit"),
    [
        (RunStatus.COMPLETE, 0),
        (RunStatus.NO_INPUT, 0),
        (RunStatus.PARTIAL_FAILURE, 1),
        (RunStatus.FAILED, 1),
        (RunStatus.INTERRUPTED, 1),
    ],
)
def test_cli_index_emits_required_summary_keys_without_assets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    status: RunStatus,
    expected_exit: int,
) -> None:
    from bird_recognition.embed import pipeline, storage

    class Store:
        def __init__(self, database_url: str) -> None:
            self.database_url = database_url

        def get_run_configuration(self, run_id: object) -> dict[str, object]:
            return {
                "model_fingerprint": "1" * 64,
                "candidate_set_fingerprint": "2" * 64,
                "scoring_fingerprint": "3" * 64,
                "threshold": 0.5,
                "candidate_count": 2,
            }

        def close(self) -> None:
            return None

    now = datetime.now(UTC)
    manifest = tmp_path / "manifest.sqlite3"
    manifest.touch()
    run = SimpleNamespace(
        run_id=uuid4(),
        status=status,
        config_fingerprint="4" * 64,
        selected_count=1,
        completed_count=1,
        skipped_count=0,
        failed_count=0,
        assigned_count=1,
        unknown_count=0,
        pending_count=0,
        failures=(),
        started_at=now,
        model_fingerprint="1" * 64,
        candidate_set_fingerprint="2" * 64,
        scoring_fingerprint="3" * 64,
        threshold=0.5,
        candidate_count=2,
        durable_status_confirmed=True,
        unconfirmed_crop_ids=(),
    )
    monkeypatch.setattr(storage, "PgVectorStore", Store)
    monkeypatch.setattr(pipeline, "index_manifest", lambda *args, **kwargs: run)

    result = main(
        [
            "index",
            "--manifest",
            str(manifest),
            "--model-dir",
            str(tmp_path / "model"),
            "--species-list",
            str(tmp_path / "species.json"),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert result == expected_exit
    assert output.err == ""
    assert {
        "schema_version",
        "run_id",
        "status",
        "config_fingerprint",
        "model_fingerprint",
        "candidate_set_fingerprint",
        "scoring_fingerprint",
        "threshold",
        "counts",
        "failures",
        "warnings",
        "durable_status_confirmed",
        "unconfirmed_crop_ids",
    } <= set(payload)


def test_cli_index_resolves_process_environment_and_dotenv_values(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from bird_recognition.embed import pipeline, storage

    manifest = tmp_path / "manifest.sqlite3"
    manifest.touch()
    monkeypatch.setattr("bird_recognition.cli.find_dotenv", lambda usecwd: "local.env")
    monkeypatch.setattr(
        "bird_recognition.cli.dotenv_values",
        lambda path: {
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://dotenv@localhost/dotenv_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "dotenv-model",
            "BIRD_RECOGNITION_SPECIES_LIST": "dotenv-species.json",
            "BIRD_RECOGNITION_SPECIES_THRESHOLD": "0.25",
        },
    )
    monkeypatch.setenv(
        "BIRD_RECOGNITION_DATABASE_URL", "postgresql://bird@localhost/bird_db"
    )
    monkeypatch.setenv(
        "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR", str(tmp_path / "env-model")
    )
    monkeypatch.setenv(
        "BIRD_RECOGNITION_SPECIES_LIST", str(tmp_path / "env-species.json")
    )
    monkeypatch.setenv("BIRD_RECOGNITION_SPECIES_THRESHOLD", "0.75")
    captured: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class Store:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def get_run_configuration(self, run_id: object) -> dict[str, object]:
            return {}

        def close(self) -> None:
            return None

    run = SimpleNamespace(
        run_id=uuid4(),
        status=RunStatus.COMPLETE,
        config_fingerprint="4" * 64,
        selected_count=0,
        completed_count=0,
        skipped_count=0,
        failed_count=0,
        assigned_count=0,
        unknown_count=0,
        pending_count=0,
        failures=(),
        model_fingerprint="1" * 64,
        candidate_set_fingerprint="2" * 64,
        scoring_fingerprint="3" * 64,
        threshold=0.75,
        candidate_count=2,
        durable_status_confirmed=True,
        unconfirmed_crop_ids=(),
    )

    def fake_index_manifest(*args: object, **kwargs: object) -> SimpleNamespace:
        captured.append((args, kwargs))
        return run

    monkeypatch.setattr(storage, "PgVectorStore", Store)
    monkeypatch.setattr(pipeline, "index_manifest", fake_index_manifest)

    result = main(["index", "--manifest", str(manifest), "--json"])

    output = capsys.readouterr()
    assert result == 0
    assert json.loads(output.out)["threshold"] == 0.75
    assert captured[0][1]["model_directory"] == tmp_path / "env-model"
    assert captured[0][1]["species_path"] == tmp_path / "env-species.json"
    assert captured[0][1]["threshold"] == 0.75


def test_cli_inspect_includes_full_relative_confidence_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            del database_url

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, run_id: UUID, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            del run_id, crop_id
            return (
                {
                    "candidate_set_fingerprint": "2" * 64,
                    "candidates": {
                        "species": [
                            {"id": "Exact-ID", "name": "Species One"},
                            {"id": "second", "name": "Species Two"},
                        ]
                    },
                    "config_fingerprint": "4" * 64,
                    "model_fingerprint": "1" * 64,
                    "scoring_fingerprint": "3" * 64,
                    "threshold": 0.5,
                },
                [
                    {
                        "decision": {
                            "best_candidate_id": "Exact-ID",
                            "candidate_scores": [
                                {"id": "Exact-ID", "logit": 1.0, "score": 0.5},
                                {"id": "second", "logit": 1.0, "score": 0.5},
                            ],
                            "tied_candidate_ids": ["Exact-ID", "second"],
                            "warnings": ["relative warning"],
                        }
                    }
                ],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)

    result = main(
        [
            "inspect",
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--run-id",
            str(uuid4()),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["run"]["threshold"] == 0.5
    assert payload["run"]["config_fingerprint"] == "4" * 64
    assert payload["run"]["model_fingerprint"] == "1" * 64
    assert payload["run"]["candidate_set_fingerprint"] == "2" * 64
    assert payload["run"]["scoring_fingerprint"] == "3" * 64
    assert payload["run"]["candidates"]["species"][0]["id"] == "Exact-ID"
    assert payload["items"][0]["decision"]["tied_candidate_ids"] == [
        "Exact-ID",
        "second",
    ]
    assert [
        score["score"] for score in payload["items"][0]["decision"]["candidate_scores"]
    ] == [
        0.5,
        0.5,
    ]
    assert payload["items"][0]["decision"]["warnings"]
    assert "different candidate sets are not directly comparable" in json.dumps(payload)
    assert "Out-of-list animals can score highly" in json.dumps(payload)


def test_cli_inspect_warns_when_persisted_candidate_set_has_one_species(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            del database_url

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, run_id: str, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            del run_id, crop_id
            return (
                {"candidates": {"species": [{"id": "one", "name": "One"}]}},
                [],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)

    result = main(
        [
            "inspect",
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--run-id",
            str(uuid4()),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert any("single candidate" in warning for warning in payload["run"]["warnings"])


def test_cli_evaluate_species_writes_read_only_low_quality_report_without_assets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from bird_recognition.embed import storage

    run_id = UUID("00000000-0000-0000-0000-000000000001")

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, selected_run_id: UUID, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            assert selected_run_id == run_id
            assert crop_id is None
            return (
                {
                    "run_id": str(run_id),
                    "status": "complete",
                    "counts": {"selected": 1},
                    "model_fingerprint": "1" * 64,
                    "candidate_set_fingerprint": "2" * 64,
                    "scoring_fingerprint": "3" * 64,
                    "config_fingerprint": "4" * 64,
                    "threshold": 0.5,
                    "candidates": {
                        "schema_version": 1,
                        "species": [{"id": "bird", "name": "Bird"}],
                    },
                },
                [
                    {
                        "crop_id": "crop-1",
                        "status": "completed",
                        "lighting": "unknown",
                        "decision": {
                            "assigned_species_id": "unknown",
                            "reason": "below_threshold",
                        },
                        "provenance": None,
                    }
                ],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": str(run_id),
                "examples": [
                    {
                        "crop_id": "crop-1",
                        "expected_species_id": "bird",
                        "truth_kind": "species",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    result = main(
        [
            "evaluate-species",
            "--run-id",
            str(run_id),
            "--labels",
            str(labels),
            "--output",
            str(report_path),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    output = capsys.readouterr()
    payload = json.loads(output.out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert output.err == ""
    assert payload["status"] == "evaluated"
    assert payload["output"] == str(report_path.resolve())
    assert report["publication_ready"] is False
    assert report["groups"]["unknown"]["unknown_count"] == 1


def test_cli_evaluate_species_requires_explicit_run_labels_and_output() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as missing_arguments:
        parser.parse_args(["evaluate-species"])

    assert missing_arguments.value.code == 2


def test_cli_evaluate_species_rejects_repository_report_path_before_database_access(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    labels = tmp_path / "labels.json"
    labels.write_text(
        '{"schema_version":1,"run_id":"00000000-0000-0000-0000-000000000001","examples":[]}',
        encoding="utf-8",
    )
    output_path = Path(__file__).resolve().parents[2] / ".evaluation-private-test.json"

    result = main(
        [
            "evaluate-species",
            "--run-id",
            "00000000-0000-0000-0000-000000000001",
            "--labels",
            str(labels),
            "--output",
            str(output_path),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["status"] == "preflight_failure"
    assert not output_path.exists()


def test_cli_evaluate_species_database_read_failure_is_operational(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from bird_recognition.embed import storage
    from bird_recognition.embed.models import StorageError

    class BrokenReadStore:
        def __init__(self, database_url: str) -> None:
            del database_url

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, run_id: UUID, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            del run_id, crop_id
            raise StorageError("persisted run read failed")

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", BrokenReadStore)
    run_id = "00000000-0000-0000-0000-000000000001"
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps({"schema_version": 1, "run_id": run_id, "examples": []}),
        encoding="utf-8",
    )
    output_path = tmp_path / "report.json"

    result = main(
        [
            "evaluate-species",
            "--run-id",
            run_id,
            "--labels",
            str(labels),
            "--output",
            str(output_path),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["status"] == "operational_failure"
    assert not output_path.exists()
