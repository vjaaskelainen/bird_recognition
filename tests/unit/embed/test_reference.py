from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.embed.models import EmbedValidationError
from bird_recognition.embed.reference import (
    ReferenceExample,
    ReferenceSet,
    load_reference_manifest,
    match_reference,
    validate_reference_split,
)

MODEL_FINGERPRINT = "1" * 64
INPUT_FINGERPRINT = "2" * 64


def _reference_set(
    embeddings: tuple[tuple[str, tuple[float, ...]], ...],
    *,
    source_id: str | None = "reference-video",
) -> ReferenceSet:
    return ReferenceSet(
        set_id="local-set",
        fingerprint="3" * 64,
        model_fingerprint=MODEL_FINGERPRINT,
        input_view_fingerprint=INPUT_FINGERPRINT,
        review_provenance="owner-reviewed",
        examples=tuple(
            ReferenceExample(
                f"crop-{index}",
                source_id,
                "2025-01-01",
                species_id,
                Path(f"reference-{index}.png"),
                vector,
            )
            for index, (species_id, vector) in enumerate(embeddings)
        ),
    )


def test_load_reference_manifest_validates_fields_and_model_identity(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "reference.png"
    Image.new("RGB", (12, 12)).save(image_path)
    image_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "references.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "set_id": "local-set",
                "model_fingerprint": MODEL_FINGERPRINT,
                "input_view_fingerprint": INPUT_FINGERPRINT,
                "review_provenance": "owner-reviewed",
                "references": [
                    {
                        "crop_id": "crop-1",
                        "source_video_id": "video-1",
                        "recording_day": "2025-01-01",
                        "species_id": "species-a",
                        "image_path": image_path.name,
                        "image_sha256": image_sha256,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    references = load_reference_manifest(
        manifest_path,
        model_fingerprint=MODEL_FINGERPRINT,
        input_view_fingerprint=INPUT_FINGERPRINT,
    )

    assert references.set_id == "local-set"
    canonical_document = json.loads(manifest_path.read_text(encoding="utf-8"))
    canonical_document["references"][0].pop("image_path")
    assert (
        references.fingerprint
        == hashlib.sha256(
            json.dumps(
                canonical_document,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )
    assert references.examples[0].image_path == image_path.resolve()


def test_load_reference_manifest_rejects_incompatible_input_identity(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "references.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "set_id": "set",
                "model_fingerprint": MODEL_FINGERPRINT,
                "input_view_fingerprint": INPUT_FINGERPRINT,
                "review_provenance": "reviewed",
                "references": [
                    {
                        "crop_id": "crop-1",
                        "source_video_id": "video-1",
                        "recording_day": None,
                        "species_id": "species-a",
                        "image_path": "missing.png",
                        "image_sha256": "6" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(EmbedValidationError, match="incompatible"):
        load_reference_manifest(
            manifest_path,
            model_fingerprint=MODEL_FINGERPRINT,
            input_view_fingerprint="4" * 64,
        )


def test_validate_reference_split_rejects_crop_source_and_day_leakage() -> None:
    references = _reference_set((("species-a", (1.0, 0.0)),))

    with pytest.raises(EmbedValidationError, match="split keys overlap"):
        validate_reference_split(
            references, [{"crop_id": "eval-1", "source_id": "reference-video"}]
        )
    with pytest.raises(EmbedValidationError, match="crops overlap"):
        validate_reference_split(
            references,
            [{"crop_id": "crop-0", "source_id": "evaluation-video"}],
        )
    with pytest.raises(EmbedValidationError, match="split keys overlap"):
        validate_reference_split(
            references,
            [{"crop_id": "eval-2", "capture_time": "2025-01-01T10:00:00"}],
            split_mode="recording_day",
        )


def test_validate_reference_split_fails_closed_when_selected_split_is_unknown() -> None:
    references = _reference_set((("species-a", (1.0, 0.0)),), source_id=None)

    with pytest.raises(EmbedValidationError, match="cannot be verified"):
        validate_reference_split(
            references,
            [{"crop_id": "eval-1", "source_id": "evaluation-video"}],
        )


def test_match_reference_uses_top_five_and_returns_consistent_species() -> None:
    references = _reference_set(
        (
            ("species-a", (1.0, 0.0)),
            ("species-a", (1.0, 0.0)),
            ("species-a", (1.0, 0.0)),
            ("species-a", (1.0, 0.0)),
            ("species-b", (1.0, 0.0)),
            ("species-b", (0.0, 1.0)),
        )
    )

    result = match_reference(
        (1.0, 0.0), references, minimum_similarity=0.9, minimum_agreement=0.75
    )

    assert result.species_id == "species-a"
    assert result.decision_path == "reference_match"
    assert result.retained_reference_ids == tuple(f"crop-{index}" for index in range(5))
    assert result.agreement == 0.8


@pytest.mark.parametrize(
    ("embeddings", "minimum_similarity", "minimum_agreement"),
    [
        ((("species-a", (1.0, 0.0)), ("species-a", (1.0, 0.0))), 0.5, 0.5),
        (
            (
                ("species-a", (1.0, 0.0)),
                ("species-a", (1.0, 0.0)),
                ("species-b", (1.0, 0.0)),
            ),
            0.5,
            0.75,
        ),
        (
            (
                ("species-a", (1.0, 0.0)),
                ("species-a", (0.0, 1.0)),
                ("species-a", (0.0, 1.0)),
            ),
            0.9,
            0.5,
        ),
    ],
)
def test_match_reference_falls_back_for_weak_or_inconsistent_neighbors(
    embeddings: tuple[tuple[str, tuple[float, ...]], ...],
    minimum_similarity: float,
    minimum_agreement: float,
) -> None:
    result = match_reference(
        (1.0, 0.0),
        _reference_set(embeddings),
        minimum_similarity=minimum_similarity,
        minimum_agreement=minimum_agreement,
    )

    assert result.species_id is None
    assert result.decision_path == "zero_shot_fallback"
