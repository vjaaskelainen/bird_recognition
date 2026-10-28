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
from bird_recognition.embed.models import (
    Lighting,
    RunStatus,
    SearchContext,
    SearchResult,
)


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
        "benchmark-species",
        "aggregate-visits",
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


def test_cli_index_accepts_optional_minimum_margin() -> None:
    arguments = _build_parser().parse_args(
        [
            "index",
            "--manifest",
            "manifest.sqlite3",
            "--species-list",
            "species.json",
            "--model-dir",
            "models",
            "--minimum-margin",
            "0.12",
        ]
    )

    assert arguments.minimum_margin == 0.12


def test_cli_index_accepts_reference_manifest_and_explicit_matching_criteria() -> None:
    arguments = _build_parser().parse_args(
        [
            "index",
            "--manifest",
            "manifest.sqlite3",
            "--species-list",
            "species.json",
            "--model-dir",
            "models",
            "--reference-set",
            "references.json",
            "--reference-split-mode",
            "recording_day",
            "--reference-min-similarity",
            "0.8",
            "--reference-min-agreement",
            "0.75",
        ]
    )

    assert arguments.reference_set == Path("references.json")
    assert arguments.reference_split_mode == "recording_day"
    assert arguments.reference_min_similarity == 0.8
    assert arguments.reference_min_agreement == 0.75


def test_cli_benchmark_requires_run_labels_sample_cap_and_local_assets() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as missing_arguments:
        parser.parse_args(["benchmark-species"])

    assert missing_arguments.value.code == 2
    arguments = parser.parse_args(
        [
            "benchmark-species",
            "--run-id",
            str(uuid4()),
            "--labels",
            "labels.json",
            "--output",
            "report.json",
            "--max-crops",
            "40",
            "--model-dir",
            "models",
        ]
    )
    assert arguments.max_crops == 40
    assert arguments.model_adapter == "bioclip"


def test_cli_benchmark_rejects_unsupported_adapter_without_database_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    from bird_recognition.embed import storage

    def unexpected_store(database_url: str) -> None:
        pytest.fail(f"database should not be accessed: {database_url}")

    monkeypatch.setattr(storage, "PgVectorStore", unexpected_store)
    labels = _write_shared_labels(tmp_path / "labels.json")
    result = main(
        [
            "benchmark-species",
            "--run-id",
            str(uuid4()),
            "--labels",
            str(labels),
            "--output",
            str(tmp_path / "report.json"),
            "--max-crops",
            "20",
            "--model-dir",
            str(tmp_path / "model"),
            "--model-adapter",
            "network-model",
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["status"] == "preflight_failure"
    assert "unsupported" in payload["message"]


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


def test_cli_aggregate_visits_writes_separate_linked_report(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from bird_recognition.embed import storage

    run_id = UUID("00000000-0000-0000-0000-000000000001")
    inspected: list[UUID] = []

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, selected_run_id: UUID, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            assert crop_id is None
            inspected.append(selected_run_id)
            return (
                {
                    "run_id": str(run_id),
                    "status": "complete",
                    "config_fingerprint": "1" * 64,
                    "model_fingerprint": "2" * 64,
                    "candidate_set_fingerprint": "3" * 64,
                    "threshold": 0.5,
                    "config": {"minimum_margin": None},
                    "candidates": {
                        "schema_version": 1,
                        "species": [
                            {"id": "a", "name": "A"},
                            {"id": "b", "name": "B"},
                        ],
                    },
                },
                [
                    {
                        "crop_id": crop_id,
                        "status": "completed",
                        "provenance": {"source_id": "source-1"},
                        "decision": {
                            "decision_id": f"decision-{index}",
                            "config_fingerprint": "1" * 64,
                            "reason": "assigned",
                            "candidate_scores": scores,
                        },
                    }
                    for index, (crop_id, scores) in enumerate(
                        [
                            (
                                "crop-1",
                                [
                                    {
                                        "id": "a",
                                        "logit": 1.0,
                                        "score": 0.7310585786300049,
                                    },
                                    {
                                        "id": "b",
                                        "logit": 0.0,
                                        "score": 0.2689414213699951,
                                    },
                                ],
                            ),
                            (
                                "crop-2",
                                [
                                    {
                                        "id": "a",
                                        "logit": 0.0,
                                        "score": 0.2689414213699951,
                                    },
                                    {
                                        "id": "b",
                                        "logit": 1.0,
                                        "score": 0.7310585786300049,
                                    },
                                ],
                            ),
                        ],
                        start=1,
                    )
                ],
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    groups = tmp_path / "groups.json"
    groups.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "groups": [
                    {
                        "visit_id": "visit-1",
                        "source_video_id": "source-1",
                        "crop_ids": ["crop-1", "crop-2"],
                        "association_confident": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "visits.json"

    result = main(
        [
            "aggregate-visits",
            "--run-id",
            str(run_id),
            "--groups",
            str(groups),
            "--output",
            str(output_path),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--json",
        ]
    )

    output = capsys.readouterr()
    payload = json.loads(output.out)
    saved_report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert output.err == ""
    assert payload["status"] == "aggregated"
    assert inspected == [run_id]
    assert saved_report["visit_count"] == 1
    assert saved_report["visits"][0]["crop_ids"] == ["crop-1", "crop-2"]
    assert saved_report["visits"][0]["decision_ids"] == [
        "decision-1",
        "decision-2",
    ]


def test_cli_aggregate_visits_requires_explicit_run_groups_and_output() -> None:
    parser = _build_parser()

    with pytest.raises(SystemExit) as missing_arguments:
        parser.parse_args(["aggregate-visits"])

    assert missing_arguments.value.code == 2


def test_cli_evaluates_baseline_then_compares_revision_on_shared_labels(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from bird_recognition.embed import storage

    run_ids = (
        UUID("00000000-0000-0000-0000-000000000001"),
        UUID("00000000-0000-0000-0000-000000000002"),
    )
    run_records = {
        run_id: (
            {
                "run_id": str(run_id),
                "status": "complete",
                "counts": {"selected": 1},
                "model_fingerprint": f"{index}" * 64,
                "candidate_set_fingerprint": f"{index + 2}" * 64,
                "scoring_fingerprint": f"{index + 4}" * 64,
                "config_fingerprint": f"{index + 6}" * 64,
                "threshold": 0.5,
                "candidates": {
                    "schema_version": 1,
                    "species": [{"id": "bird", "name": "Bird"}],
                },
            },
            [
                {
                    "crop_id": f"crop-{index}",
                    "case_id": "case-1",
                    "status": "completed",
                    "lighting": "day",
                    "decision": {
                        "assigned_species_id": "bird",
                        "reason": "assigned",
                    },
                }
            ],
        )
        for index, run_id in enumerate(run_ids, start=1)
    }

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def inspect_run(
            self, selected_run_id: UUID, crop_id: str | None = None
        ) -> tuple[dict[str, object], list[dict[str, object]]]:
            assert crop_id is None
            return run_records[selected_run_id]

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    labels = _write_shared_labels(tmp_path / "held-out-labels.json")
    baseline_report_path = tmp_path / "baseline-evaluation.json"
    database_args = ["--database-url", "postgresql://bird@localhost/bird_db"]

    baseline_result = main(
        [
            "evaluate-species",
            "--run-id",
            str(run_ids[0]),
            "--labels",
            str(labels),
            "--output",
            str(baseline_report_path),
            *database_args,
            "--json",
        ]
    )

    baseline_output = json.loads(capsys.readouterr().out)
    baseline_report = json.loads(baseline_report_path.read_text(encoding="utf-8"))
    comparison_report_path = tmp_path / "candidate-comparison.json"
    comparison_result = main(
        [
            "compare-species",
            "--run-id",
            str(run_ids[0]),
            "--run-id",
            str(run_ids[1]),
            "--labels",
            str(labels),
            "--output",
            str(comparison_report_path),
            *database_args,
            "--json",
        ]
    )

    comparison_output = json.loads(capsys.readouterr().out)
    comparison_report = json.loads(comparison_report_path.read_text(encoding="utf-8"))
    assert baseline_result == 0
    assert comparison_result == 0
    assert baseline_output["status"] == "evaluated"
    assert comparison_output["status"] == "compared"
    assert (
        baseline_report["label_set"]["sha256"]
        == comparison_report["label_set"]["sha256"]
    )
    assert baseline_report["run"]["groups"]["day"]["species_correct_count"] == 1
    assert comparison_report["paired_case_count"] == 1
    assert [setup["run_id"] for setup in comparison_report["setups"]] == [
        str(run_id) for run_id in run_ids
    ]


def test_cli_search_blank_query_is_input_failure_before_database_access(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import storage

    def unexpected_store(database_url: str) -> None:
        pytest.fail(f"database should not be accessed: {database_url}")

    monkeypatch.setattr(storage, "PgVectorStore", unexpected_store)
    result = main(
        [
            "search",
            "   ",
            "--run-id",
            str(uuid4()),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--model-dir",
            "local-model",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["status"] == "preflight_failure"
    assert payload["code"] == "invalid_query"


def test_cli_search_operational_failure_is_distinct_from_empty_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import search, storage
    from bird_recognition.embed.models import SearchOperationalError

    run_id = uuid4()
    context = SimpleNamespace(
        run_id=run_id,
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("crow",),
        selected_crop_ids=(),
        model_input_view="fit-pad-v1",
    )

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            del database_url

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def load_search_collection(
            self, request: object
        ) -> tuple[object, tuple[object, ...]]:
            assert request.run_id == run_id
            return context, ()

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    monkeypatch.setattr(
        "bird_recognition.embed.bioclip.load_bioclip", lambda *a, **k: object()
    )

    def fail_search(*args: object, **kwargs: object) -> None:
        raise SearchOperationalError("stored vector is invalid")

    monkeypatch.setattr(search, "execute_search", fail_search)
    result = main(
        [
            "search",
            "owl",
            "--run-id",
            str(run_id),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--model-dir",
            "local-model",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 1
    assert payload["status"] == "operational_failure"
    assert payload["code"] == "invalid_numeric_result"
    assert "results" not in payload


def test_cli_search_requires_query_and_explicit_run_id() -> None:
    parser = _build_parser()
    with pytest.raises(SystemExit) as missing:
        parser.parse_args(["search", "owl"])

    assert missing.value.code == 2
    arguments = parser.parse_args(
        ["search", "owl", "--run-id", str(uuid4()), "--limit", "3"]
    )
    assert arguments.limit == 3


def test_cli_search_emits_successful_empty_json_and_resolves_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import search, storage

    run_id = UUID("00000000-0000-0000-0000-000000000001")
    context = SimpleNamespace(
        run_id=run_id,
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("crow",),
        selected_crop_ids=(),
        model_input_view="fit-pad-v1",
    )
    loaded_model_directories: list[Path] = []

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def load_search_collection(
            self, request: object
        ) -> tuple[object, tuple[object, ...]]:
            assert request.run_id == run_id
            return context, ()

        def close(self) -> None:
            return None

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    monkeypatch.setattr(
        "bird_recognition.embed.bioclip.load_bioclip",
        lambda model_dir, **kwargs: (
            loaded_model_directories.append(model_dir) or object()
        ),
    )
    monkeypatch.setattr(
        search,
        "execute_search",
        lambda request, model, selected_store, *, context=None, candidates=None: (
            SimpleNamespace(
                request=request,
                context=context,
                returned_count=0,
                results=(),
                warnings=("Similarity is relative relevance, not a probability.",),
            )
        ),
    )
    monkeypatch.setattr("bird_recognition.cli.find_dotenv", lambda usecwd: "local.env")
    monkeypatch.setattr(
        "bird_recognition.cli.dotenv_values",
        lambda path: {
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://dotenv@localhost/dotenv_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "dotenv-model",
        },
    )
    monkeypatch.setenv(
        "BIRD_RECOGNITION_DATABASE_URL", "postgresql://process@localhost/process_db"
    )
    monkeypatch.setenv("BIRD_RECOGNITION_BIOCLIP_MODEL_DIR", "process-model")

    result = main(
        [
            "search",
            "owl",
            "--run-id",
            str(run_id),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--model-dir",
            "local-model",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["status"] == "searched"
    assert payload["returned_count"] == 0
    assert payload["results"] == []
    assert payload["context"]["run_id"] == str(run_id)
    assert loaded_model_directories == [Path("local-model")]


def test_cli_search_parses_metadata_filters_and_rejects_malformed_values() -> None:
    parser = _build_parser()
    run_id = str(uuid4())
    arguments = parser.parse_args(
        [
            "search",
            "owl at night",
            "--run-id",
            run_id,
            "--start-date",
            "2026-01-02",
            "--end-date",
            "2026-01-03",
            "--lighting",
            "day",
            "--species-id",
            "crow",
        ]
    )

    assert arguments.start_date.isoformat() == "2026-01-02"
    assert arguments.end_date.isoformat() == "2026-01-03"
    assert arguments.lighting == "day"
    assert arguments.species_id == "crow"
    with pytest.raises(SystemExit) as malformed_date:
        parser.parse_args(
            ["search", "owl", "--run-id", run_id, "--start-date", "2026-02-30"]
        )
    assert malformed_date.value.code == 2
    with pytest.raises(SystemExit) as invalid_lighting:
        parser.parse_args(
            ["search", "owl", "--run-id", run_id, "--lighting", "unknown"]
        )
    assert invalid_lighting.value.code == 2


def test_cli_search_passes_explicit_metadata_filters_without_query_inference(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from bird_recognition.embed import search, storage

    run_id = UUID("00000000-0000-0000-0000-000000000001")
    context = SimpleNamespace(
        run_id=run_id,
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("crow",),
        selected_crop_ids=(),
        model_input_view="fit-pad-v1",
    )
    seen_requests: list[object] = []

    class ReadOnlyStore:
        def __init__(self, database_url: str) -> None:
            assert database_url == "postgresql://bird@localhost/bird_db"

        def preflight(self, *, read_only: bool = False) -> None:
            assert read_only

        def load_search_collection(
            self, request: object
        ) -> tuple[object, tuple[object, ...]]:
            assert request.run_id == run_id
            return context, ()

        def close(self) -> None:
            return None

    def capture_search_request(
        request: object,
        model: object,
        store: object,
        *,
        context: object = None,
        candidates: tuple[object, ...] | None = None,
    ) -> object:
        del model, store, candidates
        seen_requests.append(request)
        return SimpleNamespace(
            request=request,
            context=context,
            returned_count=0,
            results=(),
            warnings=("Similarity is relative relevance, not a probability.",),
        )

    monkeypatch.setattr(storage, "PgVectorStore", ReadOnlyStore)
    monkeypatch.setattr(
        "bird_recognition.embed.bioclip.load_bioclip", lambda *args, **kwargs: object()
    )
    monkeypatch.setattr(search, "execute_search", capture_search_request)

    result = main(
        [
            "search",
            "owl at night on January 2",
            "--run-id",
            str(run_id),
            "--database-url",
            "postgresql://bird@localhost/bird_db",
            "--model-dir",
            "local-model",
            "--start-date",
            "2026-01-02",
            "--end-date",
            "2026-01-02",
            "--lighting",
            "day",
            "--species-id",
            "crow",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.start_date.isoformat() == "2026-01-02"
    assert request.end_date.isoformat() == "2026-01-02"
    assert request.lighting.value == "day"
    assert request.species_id == "crow"
    assert payload["filters"] == {
        "start_date": "2026-01-02",
        "end_date": "2026-01-02",
        "lighting": "day",
        "species_id": "crow",
    }


@pytest.mark.parametrize("json_output", [True, False])
def test_cli_search_reports_full_provenance_and_distinct_score_meanings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    json_output: bool,
) -> None:
    from bird_recognition.embed import search, storage

    run_id = UUID("00000000-0000-0000-0000-000000000001")
    context = SearchContext(
        run_id=run_id,
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("owl",),
        selected_crop_ids=("crop-1",),
    )
    result = SearchResult(
        rank=1,
        similarity=0.75,
        crop_id="crop-1",
        snapshot_id="d" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        config_fingerprint=context.config_fingerprint,
        assigned_species_id=None,
        species_confidence=None,
        crop_path=tmp_path / "missing-crop.jpg",
        image_status="available",
        source_id="source-1",
        source_video="camera.mp4",
        source_original_path="recordings/camera.mp4",
        frame_number=10,
        elapsed_seconds=5.0,
        capture_time=None,
        capture_timezone=None,
        lighting=Lighting.UNKNOWN,
        detection_id="detection-1",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.1, 0.2, 0.5, 0.6),
        crop_box_pixels=(10, 20, 50, 60),
        frame_width=100,
        frame_height=100,
    )
    vector = (1.0,) + (0.0,) * 511
    candidate = search.SearchCandidate(result=result, embedding=vector)
    store = SimpleNamespace(
        preflight=lambda *, read_only=False: None,
        load_search_collection=lambda request: (context, (candidate,)),
        close=lambda: None,
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda prompts: (vector,),
    )
    monkeypatch.setattr(storage, "PgVectorStore", lambda database_url: store)
    monkeypatch.setattr(
        "bird_recognition.embed.bioclip.load_bioclip", lambda *args, **kwargs: model
    )

    arguments = [
        "search",
        "owl",
        "--run-id",
        str(run_id),
        "--database-url",
        "postgresql://bird@localhost/bird_db",
        "--model-dir",
        "local-model",
    ]
    if json_output:
        arguments.append("--json")

    exit_code = main(arguments)
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.err == ""
    if not json_output:
        assert "similarity=" in output.out
        assert "species confidence" in output.out.casefold()
        assert "detection confidence" in output.out.casefold()
        assert "unavailable" in output.out
        return
    payload = json.loads(output.out)
    match = payload["results"][0]
    assert match["image_status"] == "unavailable"
    assert match["source"] == {
        "source_id": "source-1",
        "video": "camera.mp4",
        "original_path": "recordings/camera.mp4",
        "frame_number": 10,
        "elapsed_seconds": 5.0,
    }
    assert match["capture"] == {"time": None, "timezone": None}
    assert match["lighting"] == "unknown"
    assert match["detection"] == {
        "id": "detection-1",
        "category": "animal",
        "confidence": 0.9,
        "box_normalized": [0.1, 0.2, 0.5, 0.6],
        "crop_box_pixels": [10, 20, 50, 60],
        "frame_width": 100,
        "frame_height": 100,
    }
    assert match["species"] == {
        "assigned_species_id": "unknown",
        "confidence": None,
        "config_fingerprint": "b" * 64,
    }
    assert match["crop_id"] == "crop-1"
    assert match["snapshot_id"] == "d" * 64
    assert match["representation_id"] == "00000000-0000-0000-0000-000000000002"
    assert match["decision_id"] == "00000000-0000-0000-0000-000000000003"
    assert payload["score"]["name"] == "cosine_similarity"
    assert any("candidate set" in warning for warning in payload["warnings"])
