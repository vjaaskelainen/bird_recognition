from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from bird_recognition.embed.config import (
    build_tagging_config,
    canonical_json_bytes,
    load_species_candidates,
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
