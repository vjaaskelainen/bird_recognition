from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bird_recognition.embed.config import (
    build_tagging_config,
    canonical_json_bytes,
    load_species_candidates,
    resolve_embed_configuration,
    sanitize_error,
    validate_local_database_url,
    validate_threshold,
)
from bird_recognition.embed.models import EmbeddingModelRecord, EmbedValidationError


def _species_document(
    species: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "species": species,
    }


def _candidate_document(
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    return {"schema_version": 2, "candidates": candidates}


def _schema_2_candidates() -> list[dict[str, object]]:
    return [
        {
            "id": "great_tit",
            "kind": "species",
            "common_name": "Great tit",
            "taxonomic_description": "Parus major; owner-verified local taxon",
        },
        {
            "id": "broad_bird",
            "kind": "category",
            "category": "bird",
            "common_name": "Bird",
            "taxonomic_description": "A bird not identified to a listed species",
        },
        {
            "id": "broad_mammal",
            "kind": "category",
            "category": "mammal",
            "common_name": "Mammal",
            "taxonomic_description": "A mammal not identified to a listed species",
        },
    ]


def _write_species_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_species_candidates_missing_file_raises_validation_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(tmp_path / "missing.json")


def test_load_species_candidates_unreadable_file_raises_validation_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(tmp_path)


@pytest.mark.parametrize("content", ["", "   \n\t"])
def test_load_species_candidates_empty_file_raises_validation_error(
    tmp_path: Path, content: str
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(_write_species_file(tmp_path / "empty.json", content))


@pytest.mark.parametrize("content", ["{", "not-json", "null", "[]"])
def test_load_species_candidates_malformed_document_raises_validation_error(
    tmp_path: Path, content: str
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(_write_species_file(tmp_path / "invalid.json", content))


@pytest.mark.parametrize(
    "content",
    [
        '{"schema_version":1,"schema_version":1,"species":[{"id":"a","name":"A"}]}',
        '{"schema_version":1,"species":[{"id":"a","id":"b","name":"A"}]}',
    ],
)
def test_load_species_candidates_duplicate_json_keys_are_rejected(
    tmp_path: Path, content: str
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(
            _write_species_file(tmp_path / "duplicates.json", content)
        )


@pytest.mark.parametrize(
    "document",
    [
        {"schema_version": 1, "species": [{"id": "a", "name": "A"}], "extra": True},
        {
            "schema_version": 1,
            "species": [{"id": "a", "name": "A", "extra": True}],
        },
    ],
)
def test_load_species_candidates_unknown_fields_are_rejected(
    tmp_path: Path, document: dict[str, object]
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(
            _write_species_file(tmp_path / "unknown-field.json", json.dumps(document))
        )


@pytest.mark.parametrize(
    "species",
    [
        [],
        [{"id": " ", "name": "Common Raven"}],
        [{"id": "raven", "name": "\t"}],
        [{"id": 7, "name": "Common Raven"}],
        [{"id": "raven", "name": None}],
        [{"id": "unknown", "name": "Unknown bird"}],
        [{"id": "UnKnOwN", "name": "Unknown bird"}],
        [
            {"id": " Raven ", "name": "Common Raven"},
            {"id": "raven", "name": "Northern Raven"},
        ],
        [
            {"id": "Raven", "name": "Common Raven"},
            {"id": "raven", "name": "Northern Raven"},
        ],
        [
            {"id": "raven-one", "name": " Common Raven "},
            {"id": "raven-two", "name": "common raven"},
        ],
        [
            {"id": "bird-one", "name": "Straße"},
            {"id": "bird-two", "name": "STRASSE"},
        ],
    ],
)
def test_load_species_candidates_invalid_candidates_are_rejected(
    tmp_path: Path, species: list[dict[str, object]]
) -> None:
    document: dict[str, object] = {"schema_version": 1, "species": species}
    with pytest.raises(EmbedValidationError):
        load_species_candidates(
            _write_species_file(
                tmp_path / "invalid-candidate.json", json.dumps(document)
            )
        )


def test_load_species_candidates_trims_values_and_preserves_identifier_case(
    tmp_path: Path,
) -> None:
    document = _species_document([{"id": "  RavenID ", "name": "  Common Raven  "}])
    candidates = load_species_candidates(
        _write_species_file(tmp_path / "trimmed.json", json.dumps(document))
    )

    assert [(candidate.id, candidate.name) for candidate in candidates.candidates] == [
        ("RavenID", "Common Raven")
    ]


def test_load_species_candidates_file_order_and_whitespace_do_not_change_identity(
    tmp_path: Path,
) -> None:
    first = _species_document(
        [
            {"id": "corvus-corax", "name": "Common Raven"},
            {"id": "cyanocitta-cristata", "name": "Blue Jay"},
        ]
    )
    second = _species_document(
        [
            {"id": "cyanocitta-cristata", "name": "Blue Jay"},
            {"id": "corvus-corax", "name": "Common Raven"},
        ]
    )
    first_path = _write_species_file(
        tmp_path / "first.json", json.dumps(first, ensure_ascii=False)
    )
    second_path = _write_species_file(
        tmp_path / "second.json",
        json.dumps(second, ensure_ascii=False, indent=4, sort_keys=False),
    )

    first_candidates = load_species_candidates(first_path)
    second_candidates = load_species_candidates(second_path)

    assert first_candidates.candidates == second_candidates.candidates
    assert first_candidates.candidates_json == second_candidates.candidates_json
    assert first_candidates.candidate_set_fingerprint == (
        second_candidates.candidate_set_fingerprint
    )


def test_load_schema_2_candidates_normalizes_and_orders_typed_entries(
    tmp_path: Path,
) -> None:
    values = _schema_2_candidates()
    first = load_species_candidates(
        _write_species_file(
            tmp_path / "schema-2-first.json",
            json.dumps(_candidate_document(values)),
        )
    )
    second = load_species_candidates(
        _write_species_file(
            tmp_path / "schema-2-second.json",
            json.dumps(_candidate_document(list(reversed(values))), indent=2),
        )
    )

    assert first.schema_version == 2
    assert [candidate.id for candidate in first.candidates] == [
        "broad_bird",
        "broad_mammal",
        "great_tit",
    ]
    assert first.candidates == second.candidates
    assert first.candidates_json == second.candidates_json
    assert first.candidate_set_fingerprint == second.candidate_set_fingerprint
    assert first.candidates[0].kind == "category"
    assert first.candidates[0].category == "bird"
    assert first.candidates[-1].kind == "species"


@pytest.mark.parametrize(
    "candidates",
    [
        [item for item in _schema_2_candidates() if item.get("category") != "bird"],
        _schema_2_candidates()
        + [
            {
                "id": "another-bird",
                "kind": "category",
                "category": "bird",
                "common_name": "Another bird",
                "taxonomic_description": "Bird",
            }
        ],
        _schema_2_candidates()
        + [
            {
                "id": "other-tit",
                "kind": "species",
                "common_name": "Great tit",
                "taxonomic_description": "Different species",
            }
        ],
    ],
)
def test_load_schema_2_candidates_rejects_missing_or_duplicate_categories_and_names(
    tmp_path: Path, candidates: list[dict[str, object]]
) -> None:
    with pytest.raises(EmbedValidationError):
        load_species_candidates(
            _write_species_file(
                tmp_path / "invalid-schema-2.json",
                json.dumps(_candidate_document(candidates)),
            )
        )


@pytest.mark.parametrize(
    "candidate",
    [
        {
            "id": "tit",
            "kind": "species",
            "common_name": "Great tit",
            "taxonomic_description": "Parus major",
            "unexpected": "field",
        },
        {
            "id": "bird",
            "kind": "category",
            "category": "bird",
            "common_name": "Bird",
            "taxonomic_description": "Bird",
            "unexpected": "field",
        },
    ],
)
def test_load_schema_2_candidates_rejects_unknown_fields(
    tmp_path: Path, candidate: dict[str, object]
) -> None:
    candidates = _schema_2_candidates() + [candidate]

    with pytest.raises(EmbedValidationError):
        load_species_candidates(
            _write_species_file(
                tmp_path / "unknown-schema-2-field.json",
                json.dumps(_candidate_document(candidates)),
            )
        )


def test_load_schema_2_candidates_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    content = (
        '{"schema_version":2,"candidates":['
        '{"id":"great_tit","id":"other","kind":"species",'
        '"common_name":"Great tit","taxonomic_description":"Parus major"}]}'
    )

    with pytest.raises(EmbedValidationError):
        load_species_candidates(
            _write_species_file(tmp_path / "duplicate.json", content)
        )


def test_build_tagging_config_uses_exact_taxonomy_prompt_and_fingerprints_text(
    model_record: EmbeddingModelRecord, tmp_path: Path
) -> None:
    candidate_set = load_species_candidates(
        _write_species_file(
            tmp_path / "schema-2.json",
            json.dumps(_candidate_document(_schema_2_candidates())),
        )
    )

    config = build_tagging_config(model_record, candidate_set)
    changed_candidates = _schema_2_candidates()
    changed_candidates[2] = {
        **changed_candidates[2],
        "taxonomic_description": "A mammal outside the species list",
    }
    changed_set = load_species_candidates(
        _write_species_file(
            tmp_path / "schema-2-changed.json",
            json.dumps(_candidate_document(changed_candidates)),
        )
    )
    changed_config = build_tagging_config(model_record, changed_set)

    assert config.prompt_template == (
        "a photo of {common_name} ({taxonomic_description})."
    )
    assert config.prompt_version == "species-taxonomy-photo-v2"
    assert config.scoring_fingerprint != changed_config.scoring_fingerprint
    assert config.config_fingerprint != changed_config.config_fingerprint
    assert json.loads(config.scoring_json)["prompt_template"] == config.prompt_template


def test_format_candidate_prompt_reproduces_schema_1_and_schema_2_text(
    tmp_path: Path,
) -> None:
    from bird_recognition.embed.config import format_candidate_prompt

    legacy = load_species_candidates(
        _write_species_file(
            tmp_path / "legacy.json",
            json.dumps(_species_document([{"id": "tit", "name": "Great tit"}])),
        )
    )
    taxonomy = load_species_candidates(
        _write_species_file(
            tmp_path / "taxonomy.json",
            json.dumps(_candidate_document(_schema_2_candidates())),
        )
    )

    assert format_candidate_prompt(legacy.candidates[0], "a photo of {name}.") == (
        "a photo of Great tit."
    )
    assert (
        format_candidate_prompt(
            taxonomy.candidates[-1],
            "a photo of {common_name} ({taxonomic_description}).",
        )
        == "a photo of Great tit (Parus major; owner-verified local taxon)."
    )


def test_candidate_examples_load_as_schema_2_and_legacy_schema_1() -> None:
    repository_root = Path(__file__).resolve().parents[3]

    current = load_species_candidates(repository_root / "species.json.example")
    legacy = load_species_candidates(repository_root / "species.schema1.json.example")

    assert current.schema_version == 2
    assert {candidate.category for candidate in current.candidates} == {
        None,
        "bird",
        "mammal",
    }
    assert legacy.schema_version == 1


def test_canonical_json_bytes_are_sorted_compact_utf8() -> None:
    canonical = canonical_json_bytes({"zebra": "café", "alpha": 1})

    assert canonical == b'{"alpha":1,"zebra":"caf\xc3\xa9"}'
    assert canonical_json_bytes({"alpha": 1, "zebra": "café"}) == canonical


@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), -float("inf")]
)
def test_validate_threshold_rejects_booleans_and_nonfinite_values(
    value: object,
) -> None:
    with pytest.raises(EmbedValidationError):
        validate_threshold(value)


@pytest.mark.parametrize(
    "value", [-0.01, 1.01, "NaN", "Infinity", "-Infinity", "invalid"]
)
def test_validate_threshold_rejects_out_of_range_or_invalid_values(
    value: object,
) -> None:
    with pytest.raises(EmbedValidationError):
        validate_threshold(value)


def test_validate_threshold_normalizes_decimal_spellings_and_defaults_to_half() -> None:
    assert validate_threshold("0.50") == validate_threshold("0.5") == 0.5
    assert canonical_json_bytes({"threshold": validate_threshold("0.50")}) == (
        canonical_json_bytes({"threshold": validate_threshold("0.5")})
    )
    assert validate_threshold() == 0.5
    assert validate_threshold(0.0) == 0.0
    assert validate_threshold(1.0) == 1.0


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://bird:local-pass@localhost:5432/bird_db",
        "postgresql://bird:local-pass@127.0.0.1:5432/bird_db",
        "postgresql://bird:local-pass@[::1]:5432/bird_db",
    ],
)
def test_validate_local_database_url_accepts_local_targets(url: str) -> None:
    validate_local_database_url(url)


@pytest.mark.skipif(
    sys.platform == "win32", reason="Unix domain sockets are unavailable"
)
def test_validate_local_database_url_accepts_unix_socket() -> None:
    validate_local_database_url("postgresql:///bird_db?host=/var/run/postgresql")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql://bird:private-pass@database.example:5432/bird_db",
        "postgresql://bird:private-pass@192.0.2.10:5432/bird_db",
        "postgresql://bird:private-pass@localhost:5432/bird_db?host=database.example",
        "https://localhost/bird_db",
        "postgresql://bird:private-pass@localhost:5432",
    ],
)
def test_validate_local_database_url_rejects_invalid_or_remote_targets(
    url: str,
) -> None:
    with pytest.raises(EmbedValidationError) as error:
        validate_local_database_url(url)

    assert "private-pass" not in str(error.value)
    assert "database.example" not in str(error.value)


def test_sanitize_error_redacts_database_credentials_and_url() -> None:
    raw_error = "connection failed for postgresql://bird:private-pass@database.example:5432/bird_db"

    sanitized = sanitize_error(raw_error)

    assert "private-pass" not in sanitized
    assert "database.example" not in sanitized
    assert "postgresql://" not in sanitized


def test_build_tagging_config_keeps_scoring_identity_threshold_independent(
    model_record: EmbeddingModelRecord, tmp_path: Path
) -> None:
    first_file = _write_species_file(
        tmp_path / "species.json",
        json.dumps(
            _species_document(
                [
                    {"id": "bird-b", "name": "Blue Bird"},
                    {"id": "bird-a", "name": "Red Bird"},
                ]
            )
        ),
    )
    candidate_set = load_species_candidates(first_file)

    first = build_tagging_config(model_record, candidate_set, 0.5)
    retagged = build_tagging_config(model_record, candidate_set, 0.75)

    assert first.scoring_fingerprint == retagged.scoring_fingerprint
    assert first.config_fingerprint != retagged.config_fingerprint
    assert first.prompt_template == "a photo of {name}."
    assert first.prompt_version == "species-photo-v1"
    assert json.loads(first.scoring_json)["score_formula"] == (
        "effective_logit_scale * dot(normalized_image, normalized_text)"
    )
    assert json.loads(first.canonical_json)["threshold"] == 0.5
    assert json.loads(retagged.canonical_json)["threshold"] == 0.75


def test_build_tagging_config_fingerprints_minimum_crop_dimensions(
    model_record: EmbeddingModelRecord, tmp_path: Path
) -> None:
    species_path = _write_species_file(
        tmp_path / "species.json",
        json.dumps(_species_document([{"id": "bird", "name": "Bird"}])),
    )
    candidates = load_species_candidates(species_path)

    baseline = build_tagging_config(model_record, candidates)
    stricter_quality = build_tagging_config(
        model_record, candidates, minimum_crop_width=40, minimum_crop_height=48
    )

    assert baseline.config_fingerprint != stricter_quality.config_fingerprint
    assert baseline.scoring_fingerprint == stricter_quality.scoring_fingerprint
    assert json.loads(stricter_quality.canonical_json)["minimum_crop_width"] == 40
    assert json.loads(stricter_quality.canonical_json)["minimum_crop_height"] == 48
    with pytest.raises(EmbedValidationError):
        build_tagging_config(model_record, candidates, minimum_crop_width=0)


def test_build_tagging_config_fingerprints_reference_setup_without_changing_scores(
    model_record: EmbeddingModelRecord, tmp_path: Path
) -> None:
    candidates = load_species_candidates(
        _write_species_file(
            tmp_path / "species.json",
            json.dumps(_species_document([{"id": "bird", "name": "Bird"}])),
        )
    )

    baseline = build_tagging_config(model_record, candidates)
    reference = build_tagging_config(
        model_record,
        candidates,
        reference_set_fingerprint="5" * 64,
        reference_split_mode="source_video",
        reference_min_similarity=0.8,
        reference_min_agreement=0.75,
    )

    assert baseline.scoring_fingerprint == reference.scoring_fingerprint
    assert baseline.config_fingerprint != reference.config_fingerprint
    assert reference.reference_set_fingerprint == "5" * 64
    assert json.loads(reference.canonical_json)["reference"] == {
        "algorithm_version": "top-five-cosine-consensus-v1",
        "minimum_agreement": 0.75,
        "minimum_similarity": 0.8,
        "set_fingerprint": "5" * 64,
        "split_mode": "source_video",
    }


@pytest.mark.parametrize("minimum", [True, float("nan"), -0.1, 1.1, "invalid"])
def test_build_tagging_config_rejects_invalid_reference_criteria(
    model_record: EmbeddingModelRecord, tmp_path: Path, minimum: object
) -> None:
    candidates = load_species_candidates(
        _write_species_file(
            tmp_path / "species.json",
            json.dumps(_species_document([{"id": "bird", "name": "Bird"}])),
        )
    )

    with pytest.raises(EmbedValidationError):
        build_tagging_config(
            model_record,
            candidates,
            reference_set_fingerprint="5" * 64,
            reference_split_mode="source_video",
            reference_min_similarity=minimum,
            reference_min_agreement=0.5,
        )


def test_resolve_embed_configuration_uses_cli_environment_dotenv_then_default() -> None:
    resolved = resolve_embed_configuration(
        "index",
        explicit={"database_url": "postgresql://cli@localhost/cli_db"},
        process_environment={
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://process@localhost/process_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "process-model",
            "BIRD_RECOGNITION_SPECIES_LIST": "process-species.json",
        },
        dotenv_environment={
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://dotenv@localhost/dotenv_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "dotenv-model",
            "BIRD_RECOGNITION_SPECIES_LIST": "dotenv-species.json",
            "BIRD_RECOGNITION_SPECIES_THRESHOLD": "0.7",
        },
    )

    assert resolved == {
        "database_url": "postgresql://cli@localhost/cli_db",
        "model_dir": "process-model",
        "species_list": "process-species.json",
        "threshold": 0.7,
    }


def test_resolve_embed_configuration_uses_dotenv_default() -> None:
    resolved = resolve_embed_configuration(
        "index",
        explicit={},
        process_environment={},
        dotenv_environment={
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://bird@localhost/bird_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "local-model",
            "BIRD_RECOGNITION_SPECIES_LIST": "species.json",
        },
    )

    assert resolved == {
        "database_url": "postgresql://bird@localhost/bird_db",
        "model_dir": "local-model",
        "species_list": "species.json",
        "threshold": 0.5,
    }


def test_resolve_search_configuration_uses_cli_process_dotenv_precedence() -> None:
    resolved = resolve_embed_configuration(
        "search",
        explicit={"database_url": "postgresql://cli@localhost/cli_db"},
        process_environment={
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://process@localhost/process_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "process-model",
            "BIRD_RECOGNITION_SPECIES_LIST": "ignored-species.json",
        },
        dotenv_environment={
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://dotenv@localhost/dotenv_db",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "dotenv-model",
            "BIRD_RECOGNITION_SPECIES_THRESHOLD": "0.9",
        },
    )

    assert resolved == {
        "database_url": "postgresql://cli@localhost/cli_db",
        "model_dir": "process-model",
    }


def test_resolve_search_configuration_requires_database_and_model_settings() -> None:
    with pytest.raises(EmbedValidationError, match="database url is required"):
        resolve_embed_configuration(
            "search",
            explicit={},
            process_environment={},
            dotenv_environment={},
        )

    with pytest.raises(EmbedValidationError, match="model dir is required"):
        resolve_embed_configuration(
            "search",
            explicit={"database_url": "postgresql://bird@localhost/bird_db"},
            process_environment={},
            dotenv_environment={},
        )


@pytest.mark.parametrize(
    ("command", "explicit", "environment"),
    [
        (
            "index",
            {"species_list": ""},
            {"BIRD_RECOGNITION_SPECIES_LIST": "valid.json"},
        ),
        (
            "index",
            {"threshold": "invalid"},
            {"BIRD_RECOGNITION_SPECIES_THRESHOLD": "0.7"},
        ),
        ("index", {}, {"BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": ""}),
        ("database-init", {}, {"BIRD_RECOGNITION_DATABASE_URL": ""}),
    ],
)
def test_resolve_embed_configuration_rejects_empty_or_invalid_selected_values(
    command: str, explicit: dict[str, object], environment: dict[str, str]
) -> None:
    with pytest.raises(EmbedValidationError):
        resolve_embed_configuration(
            command,
            explicit=explicit,
            process_environment=environment,
            dotenv_environment={},
        )


def test_resolve_embed_configuration_requires_only_command_relevant_settings() -> None:
    resolved = resolve_embed_configuration(
        "inspect",
        explicit={},
        process_environment={
            "BIRD_RECOGNITION_DATABASE_URL": "postgresql://bird@localhost/bird_db",
            "BIRD_RECOGNITION_SPECIES_LIST": "",
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR": "",
        },
        dotenv_environment={},
    )

    assert resolved == {
        "database_url": "postgresql://bird@localhost/bird_db",
    }


def test_resolve_embed_configuration_ignores_unapproved_aliases() -> None:
    with pytest.raises(EmbedValidationError):
        resolve_embed_configuration(
            "index",
            explicit={},
            process_environment={
                "POSTGRES_DB": "bird_db",
                "POSTGRES_USER": "bird",
                "POSTGRES_PASSWORD": "private-password",
                "BIRD_RECOGNITION_MANIFEST": "manifest.sqlite3",
                "BIRD_RECOGNITION_RUN_ID": "run-1",
                "BIRD_RECOGNITION_LABELS": "labels.json",
                "BIRD_RECOGNITION_OUTPUT": "report.json",
                "BIRD_RECOGNITION_TEST_DATABASE_URL": "postgresql://test@localhost/bird_test",
            },
            dotenv_environment={},
        )


def test_resolve_embed_configuration_rejects_and_redacts_remote_database_url() -> None:
    with pytest.raises(EmbedValidationError) as error:
        resolve_embed_configuration(
            "inspect",
            explicit={},
            process_environment={
                "BIRD_RECOGNITION_DATABASE_URL": (
                    "postgresql://private-user:private-password@remote.example/bird_db"
                )
            },
            dotenv_environment={},
        )

    assert "private-password" not in str(error.value)
    assert "remote.example" not in str(error.value)
