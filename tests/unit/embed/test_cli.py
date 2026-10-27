from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from bird_recognition.cli import _add_candidate_details, _build_parser, main
from bird_recognition.embed.models import RunStatus


def _write_shared_labels(path: Path, case_id: str = "case-1") -> Path:
    from bird_recognition.embed.config import canonical_json_bytes

    split_keys = ["source-video-1"]
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "label_role": "held_out_evaluation",
                "split_mode": "source_video",
                "source_split_keys": split_keys,
                "source_split_sha256": hashlib.sha256(
                    canonical_json_bytes(split_keys)
                ).hexdigest(),
                "examples": [
                    {
                        "case_id": case_id,
                        "reviewed_crop_id": "reviewed-crop-1",
                        "truth_kind": "species",
                        "expected_taxon_id": "bird",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_inspection_candidate_details_mark_category_assignments_as_coarse() -> None:
    run_data: dict[str, object] = {
        "candidates": {
            "schema_version": 2,
            "candidates": [
                {
                    "id": "broad_bird",
                    "kind": "category",
                    "category": "bird",
                    "common_name": "Bird",
                    "taxonomic_description": "An unidentified bird",
                },
                {
                    "id": "great_tit",
                    "kind": "species",
                    "common_name": "Great tit",
                    "taxonomic_description": "Parus major",
                },
            ],
        }
    }
    items: list[dict[str, object]] = [
        {
            "decision": {
                "assigned_species_id": "broad_bird",
                "candidate_scores": [
                    {"id": "broad_bird", "logit": 1.0, "score": 0.7},
                    {"id": "great_tit", "logit": 0.0, "score": 0.3},
                ],
            }
        }
    ]

    _add_candidate_details(run_data, items)

    decision = items[0]["decision"]
    assert isinstance(decision, dict)
    assert decision["assigned_candidate_kind"] == "category"
    assert decision["assigned_category"] == "bird"
    assert decision["assigned_candidate"]["common_name"] == "Bird"
    assert decision["candidate_scores"][0]["kind"] == "category"
    assert decision["candidate_scores"][1]["kind"] == "species"


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
        "compare-species",
    }
    with pytest.raises(SystemExit) as usage_error:
        parser.parse_args(["inspect"])
    assert usage_error.value.code == 2


def test_cli_index_accepts_versioned_input_view_and_quality_dimensions() -> None:
    arguments = _build_parser().parse_args(
        [
            "index",
            "--manifest",
            "manifest.sqlite3",
            "--species-list",
            "species.json",
            "--model-dir",
            "models",
            "--input-view",
            "fit-pad-v1",
            "--minimum-crop-width",
            "48",
            "--minimum-crop-height",
            "40",
        ]
    )

    assert arguments.input_view == "fit-pad-v1"
    assert arguments.minimum_crop_width == 48
    assert arguments.minimum_crop_height == 40


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
    sys.modules.pop("bird_recognition.embed.bioclip", None)
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
    assert "bird_recognition.embed.bioclip" not in sys.modules


def test_cli_inspect_selects_run_and_crop_without_assets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sys.modules.pop("bird_recognition.embed.bioclip", None)
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
    assert "bird_recognition.embed.bioclip" not in sys.modules


def test_cli_inspect_exports_crop_independent_case_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage
    from bird_recognition.ingest.manifest import stable_case_id

    source_digest = "a" * 64
    detector_box = (0.234567891, 0.123456789, 0.876543219, 0.765432198)
    expected_case_id = stable_case_id(source_digest, 3, "detection-4", detector_box)

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
                {"candidates": {"species": []}},
                [
                    {
                        "crop_id": "crop-4",
                        "provenance": {
                            "source_content_sha256": source_digest,
                            "frame_number": 3,
                            "detection_id": "detection-4",
                            "detection_box_normalized": list(detector_box),
                        },
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
    item = payload["items"][0]
    assert result == 0
    assert item["case_id"] == expected_case_id
    assert item["provenance"]["case_id"] == expected_case_id


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


def test_cli_remote_database_error_is_rejected_and_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    def fail_if_connected(database_url: str) -> None:
        raise AssertionError(f"database connection was attempted: {database_url}")

    monkeypatch.setattr(storage, "PgVectorStore", fail_if_connected)
    result = main(
        [
            "inspect",
            "--database-url",
            "postgresql://private-user:private-password@remote.example/bird_db",
            "--list-runs",
            "--json",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert json.loads(output.out)["status"] == "preflight_failure"
    assert "private-user" not in output.out
    assert "private-password" not in output.out
    assert "remote.example" not in output.out


def test_cli_does_not_use_test_database_as_an_implicit_runtime_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    test_database_url = "postgresql://test-user:test-password@localhost/bird_test"

    def fail_if_connected(database_url: str) -> None:
        raise AssertionError(f"database connection was attempted: {database_url}")

    monkeypatch.setenv("BIRD_RECOGNITION_TEST_DATABASE_URL", test_database_url)
    monkeypatch.delenv("BIRD_RECOGNITION_DATABASE_URL", raising=False)
    monkeypatch.setattr("bird_recognition.cli.find_dotenv", lambda usecwd: "")
    monkeypatch.setattr(storage, "PgVectorStore", fail_if_connected)

    result = main(["inspect", "--list-runs", "--json"])

    output = capsys.readouterr()
    assert result == 2
    assert json.loads(output.out)["status"] == "preflight_failure"
    assert test_database_url not in output.out
    assert "test-password" not in output.out


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

    def fail_if_migrated(*args: object, **kwargs: object) -> None:
        raise AssertionError("index must not initialize or migrate the database")

    monkeypatch.setattr(storage, "initialize_database", fail_if_migrated)
    monkeypatch.setattr(storage, "apply_pending_migrations", fail_if_migrated)

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
        "candidate_schema_version",
        "scoring_fingerprint",
        "prompt_template",
        "prompt_version",
        "threshold",
        "counts",
        "failures",
        "warnings",
        "durable_status_confirmed",
        "unconfirmed_crop_ids",
    } <= set(payload)
    assert payload["candidate_schema_version"] == 1
    assert payload["prompt_version"] == "species-photo-v1"


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
    sys.modules.pop("bird_recognition.embed.bioclip", None)
    from bird_recognition.embed import storage

    run_id = UUID("00000000-0000-0000-0000-000000000001")
    database_url = "postgresql://private-user:private-password@localhost/private_db"

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert (
                database_url
                == "postgresql://private-user:private-password@localhost/private_db"
            )

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
            database_url,
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
    assert "bird_recognition.embed.bioclip" not in sys.modules
    for private_value in ("private-user", "private-password", "private_db"):
        assert private_value not in output.out
        assert private_value not in report_path.read_text(encoding="utf-8")


def test_cli_evaluate_species_accepts_shared_labels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
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
                    "candidates": {"species": [{"id": "bird", "name": "Bird"}]},
                },
                [
                    {
                        "crop_id": "crop-1",
                        "case_id": "case-1",
                        "status": "completed",
                        "lighting": "unknown",
                        "decision": {
                            "assigned_species_id": "bird",
                            "reason": "assigned",
                        },
                    }
                ],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    labels = _write_shared_labels(tmp_path / "shared-labels.json")
    report_path = tmp_path / "shared-evaluation.json"
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

    payload = json.loads(capsys.readouterr().out)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["status"] == "evaluated"
    assert report["schema_version"] == 2
    assert report["run"]["matched_case_count"] == 1
    assert report["run"]["groups"]["unknown"]["species_correct_count"] == 1


def test_cli_evaluate_species_requires_explicit_run_labels_and_output() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as missing_arguments:
        parser.parse_args(["evaluate-species"])

    assert missing_arguments.value.code == 2


def test_cli_compare_species_requires_at_least_two_explicit_runs() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as missing_arguments:
        parser.parse_args(["compare-species"])
    assert missing_arguments.value.code == 2

    with pytest.raises(SystemExit) as one_run:
        main(
            [
                "compare-species",
                "--run-id",
                str(uuid4()),
                "--labels",
                "labels.json",
                "--output",
                "report.json",
                "--database-url",
                "postgresql://bird@localhost/bird_db",
            ]
        )
    assert one_run.value.code == 2


def test_cli_compare_species_writes_shared_report_for_explicit_run_ids(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from bird_recognition.embed import storage

    run_ids = [
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    ]
    database_url = "postgresql://private-user:private-password@localhost/private_db"
    inspected: list[UUID] = []

    class ReadOnlyStore:
        def __init__(self, selected_database_url: str) -> None:
            assert selected_database_url == database_url

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, selected_run_id: UUID
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            inspected.append(selected_run_id)
            return (
                {
                    "run_id": str(selected_run_id),
                    "status": "complete",
                    "counts": {"selected": 1},
                    "model_fingerprint": "1" * 64,
                    "candidate_set_fingerprint": "2" * 64,
                    "scoring_fingerprint": "3" * 64,
                    "config_fingerprint": "4" * 64,
                    "threshold": 0.5,
                    "candidates": {"species": [{"id": "bird", "name": "Bird"}]},
                },
                [
                    {
                        "crop_id": f"crop-{str(selected_run_id)[-1]}",
                        "case_id": "case-1",
                        "status": "completed",
                        "lighting": "unknown",
                        "decision": {
                            "assigned_species_id": "bird",
                            "reason": "assigned",
                        },
                    }
                ],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    labels = _write_shared_labels(tmp_path / "labels.json")
    report_path = tmp_path / "comparison.json"
    result = main(
        [
            "compare-species",
            "--run-id",
            str(run_ids[0]),
            "--run-id",
            str(run_ids[1]),
            "--labels",
            str(labels),
            "--output",
            str(report_path),
            "--database-url",
            database_url,
            "--json",
        ]
    )

    output = capsys.readouterr()
    payload = json.loads(output.out)
    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)
    assert result == 0
    assert output.err == ""
    assert payload["status"] == "compared"
    assert payload["output"] == str(report_path.resolve())
    assert inspected == run_ids
    assert report["paired_case_count"] == 1
    assert [setup["run_id"] for setup in report["setups"]] == [
        str(run_id) for run_id in run_ids
    ]
    for private_value in ("private-user", "private-password", "private_db"):
        assert private_value not in output.out
        assert private_value not in report_text


def test_cli_compare_species_rejects_repository_report_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from bird_recognition.embed import storage

    def unexpected_store(database_url: str) -> None:
        pytest.fail(f"database should not be accessed: {database_url}")

    monkeypatch.setattr(storage, "PgVectorStore", unexpected_store)
    labels = tmp_path / "labels.json"
    labels.write_text('{"schema_version":2}', encoding="utf-8")
    output_path = Path(__file__).resolve().parents[2] / ".comparison-private-test.json"

    result = main(
        [
            "compare-species",
            "--run-id",
            str(uuid4()),
            "--run-id",
            str(uuid4()),
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
