"""Validated local reference sets and deterministic nearest-reference matching."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

import numpy as np

from bird_recognition.embed.config import canonical_json_bytes
from bird_recognition.embed.models import EmbedValidationError, Vector
from bird_recognition.embed.scoring import validate_normalized_vector


@dataclass(frozen=True, slots=True)
class ReferenceExample:
    """One reviewed reference crop and its local image locator."""

    crop_id: str
    source_video_id: str | None
    recording_day: str | None
    species_id: str
    image_path: Path
    embedding: Vector | None = None


@dataclass(frozen=True, slots=True)
class ReferenceSet:
    """Canonical reference-set identity and its reviewed example records."""

    set_id: str
    fingerprint: str
    model_fingerprint: str
    input_view_fingerprint: str
    review_provenance: str
    examples: tuple[ReferenceExample, ...]


@dataclass(frozen=True, slots=True)
class ReferenceMatch:
    """Reference suggestion or an explicit zero-shot fallback outcome."""

    species_id: str | None
    decision_path: Literal["reference_match", "zero_shot_fallback"]
    similarity: float | None
    retained_reference_ids: tuple[str, ...]
    agreement: float | None


def load_reference_manifest(
    path: Path,
    *,
    model_fingerprint: str,
    input_view_fingerprint: str,
) -> ReferenceSet:
    """Load a strict external manifest and verify model/input compatibility."""
    try:
        manifest_path = Path(path).expanduser().resolve(strict=True)
        if not manifest_path.is_file() or _inside_git(manifest_path):
            raise OSError
        document = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except OSError, UnicodeError, ValueError, json.JSONDecodeError:
        raise EmbedValidationError(
            "reference manifest is unavailable or invalid UTF-8 JSON"
        ) from None
    fields = {
        "schema_version",
        "set_id",
        "model_fingerprint",
        "input_view_fingerprint",
        "review_provenance",
        "references",
    }
    if not isinstance(document, dict) or set(document) != fields:
        raise EmbedValidationError("reference manifest has an invalid field set")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise EmbedValidationError("unsupported reference manifest schema version")
    for key in ("set_id", "review_provenance"):
        if not isinstance(document[key], str) or not document[key].strip():
            raise EmbedValidationError(f"reference {key.replace('_', ' ')} is required")
    for key, expected in (
        ("model_fingerprint", model_fingerprint),
        ("input_view_fingerprint", input_view_fingerprint),
    ):
        value = document[key]
        if not _is_sha256(value):
            raise EmbedValidationError(f"reference {key.replace('_', ' ')} is invalid")
        if value != expected:
            raise EmbedValidationError("reference model or input view is incompatible")
    values = document["references"]
    if not isinstance(values, list) or not values:
        raise EmbedValidationError("reference manifest requires nonempty references")
    examples: list[ReferenceExample] = []
    seen_crops: set[str] = set()
    for value in values:
        if not isinstance(value, dict) or set(value) != {
            "crop_id",
            "source_video_id",
            "recording_day",
            "species_id",
            "image_path",
            "image_sha256",
        }:
            raise EmbedValidationError("reference example has an invalid field set")
        crop_id = value["crop_id"]
        species_id = value["species_id"]
        if (
            not isinstance(crop_id, str)
            or not crop_id.strip()
            or crop_id in seen_crops
            or not isinstance(species_id, str)
            or not species_id.strip()
        ):
            raise EmbedValidationError(
                "reference crop and species IDs must be unique and nonblank"
            )
        source_id = value["source_video_id"]
        day = value["recording_day"]
        if source_id is not None and (
            not isinstance(source_id, str) or not source_id.strip()
        ):
            raise EmbedValidationError(
                "reference source-video ID must be nonblank or null"
            )
        if day is not None:
            if not isinstance(day, str) or not _is_iso_day(day):
                raise EmbedValidationError(
                    "reference recording day must be an ISO date or null"
                )
        locator = value["image_path"]
        if not isinstance(locator, str) or not locator.strip():
            raise EmbedValidationError("reference image path is required")
        image_sha256 = value["image_sha256"]
        if not _is_sha256(image_sha256):
            raise EmbedValidationError("reference image digest is invalid")
        try:
            image_path = (manifest_path.parent / locator).resolve(strict=True)
            image_content = image_path.read_bytes()
        except OSError:
            raise EmbedValidationError(
                "reference image is unavailable outside Git"
            ) from None
        if not image_path.is_file() or _inside_git(image_path):
            raise EmbedValidationError("reference image is unavailable outside Git")
        if hashlib.sha256(image_content).hexdigest() != image_sha256:
            raise EmbedValidationError(
                "reference image content does not match its digest"
            )
        if source_id is None and day is None:
            raise EmbedValidationError(
                "reference requires a source-video ID or recording day"
            )
        seen_crops.add(crop_id)
        examples.append(
            ReferenceExample(crop_id, source_id, day, species_id, image_path)
        )
    canonical_document = {
        key: value for key, value in document.items() if key != "references"
    }
    canonical_document["references"] = [
        {key: value for key, value in example.items() if key != "image_path"}
        for example in sorted(values, key=lambda value: value["crop_id"])
    ]
    return ReferenceSet(
        set_id=document["set_id"].strip(),
        fingerprint=hashlib.sha256(
            canonical_json_bytes(canonical_document)
        ).hexdigest(),
        model_fingerprint=model_fingerprint,
        input_view_fingerprint=input_view_fingerprint,
        review_provenance=document["review_provenance"].strip(),
        examples=tuple(sorted(examples, key=lambda item: item.crop_id)),
    )


def validate_reference_split(
    reference_set: ReferenceSet,
    evaluation_examples: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    split_mode: Literal["source_video", "recording_day"] = "source_video",
) -> None:
    """Reject reference/evaluation overlap by crop and the selected provenance split."""
    if split_mode not in {"source_video", "recording_day"}:
        raise EmbedValidationError("reference split mode is unsupported")
    evaluation_crops: set[str] = set()
    evaluation_keys: set[str] = set()
    reference_keys: set[str] = set()
    for example in reference_set.examples:
        key = (
            example.source_video_id
            if split_mode == "source_video"
            else example.recording_day
        )
        if not key:
            raise EmbedValidationError("reference split cannot be verified")
        reference_keys.add(key)
    for example in evaluation_examples:
        crop_id = example.get("crop_id")
        if (
            not isinstance(crop_id, str)
            or not crop_id.strip()
            or crop_id in evaluation_crops
        ):
            raise EmbedValidationError(
                "evaluation crop IDs must be unique and nonblank"
            )
        evaluation_crops.add(crop_id)
        key = (
            example.get("source_id")
            if split_mode == "source_video"
            else example.get("recording_day")
        )
        if split_mode == "recording_day" and not key:
            key = _capture_day(example)
        if not isinstance(key, str) or not key.strip():
            raise EmbedValidationError("evaluation split cannot be verified")
        evaluation_keys.add(key)
    if evaluation_crops & {example.crop_id for example in reference_set.examples}:
        raise EmbedValidationError("reference and evaluation crops overlap")
    if evaluation_keys & reference_keys:
        raise EmbedValidationError("reference and evaluation split keys overlap")


def encode_reference_examples(reference_set: ReferenceSet, model: Any) -> ReferenceSet:
    """Encode each reference image with the compatible local model."""
    if model.identity.model_fingerprint != reference_set.model_fingerprint:
        raise EmbedValidationError("reference model does not match the loaded model")
    encoded: list[ReferenceExample] = []
    for example in reference_set.examples:
        try:
            from PIL import Image

            with Image.open(example.image_path) as image:
                image.load()
                vector = validate_normalized_vector(
                    model.encode_image(image.convert("RGB"))
                )
        except Exception:
            raise EmbedValidationError("reference image could not be encoded") from None
        encoded.append(
            ReferenceExample(
                example.crop_id,
                example.source_video_id,
                example.recording_day,
                example.species_id,
                example.image_path,
                vector,
            )
        )
    return ReferenceSet(
        reference_set.set_id,
        reference_set.fingerprint,
        reference_set.model_fingerprint,
        reference_set.input_view_fingerprint,
        reference_set.review_provenance,
        tuple(encoded),
    )


def match_reference(
    image_embedding: Vector,
    reference_set: ReferenceSet,
    *,
    minimum_similarity: object,
    minimum_agreement: object,
) -> ReferenceMatch:
    """Apply top-five cosine similarity, minimum-neighbor, and agreement gates."""
    similarity_gate = _validate_fraction(minimum_similarity, "minimum similarity")
    agreement_gate = _validate_fraction(minimum_agreement, "minimum agreement")
    query = np.asarray(validate_normalized_vector(image_embedding), dtype=np.float64)
    vectors: list[tuple[float, ReferenceExample]] = []
    for example in reference_set.examples:
        if example.embedding is None:
            raise EmbedValidationError("reference embeddings have not been prepared")
        vector = np.asarray(
            validate_normalized_vector(example.embedding), dtype=np.float64
        )
        if vector.shape != query.shape:
            raise EmbedValidationError(
                "reference embedding dimensions are incompatible"
            )
        similarity = float(np.dot(query, vector))
        if not math.isfinite(similarity):
            raise EmbedValidationError("reference similarity is invalid")
        vectors.append((similarity, example))
    neighbors = sorted(vectors, key=lambda item: (-item[0], item[1].crop_id))[:5]
    retained = [item for item in neighbors if item[0] >= similarity_gate]
    if len(retained) < 3:
        return ReferenceMatch(
            None,
            "zero_shot_fallback",
            None,
            tuple(item[1].crop_id for item in retained),
            None,
        )
    counts = Counter(item[1].species_id for item in retained)
    maximum = max(counts.values())
    winners = sorted(
        species_id for species_id, count in counts.items() if count == maximum
    )
    agreement = maximum / len(retained)
    if len(winners) != 1 or agreement < agreement_gate:
        return ReferenceMatch(
            None,
            "zero_shot_fallback",
            retained[0][0],
            tuple(item[1].crop_id for item in retained),
            agreement,
        )
    return ReferenceMatch(
        winners[0],
        "reference_match",
        retained[0][0],
        tuple(item[1].crop_id for item in retained),
        agreement,
    )


def input_view_fingerprint(model: Any) -> str:
    """Return the model's canonical preprocessing-input-view identity."""
    try:
        preprocessing = json.loads(model.identity.preprocessing_json)
        view = preprocessing["input_view"]
    except KeyError, TypeError, json.JSONDecodeError:
        raise EmbedValidationError("model input-view identity is unavailable") from None
    from bird_recognition.embed.config import canonical_json_sha256

    return canonical_json_sha256(view)


def _capture_day(example: dict[str, Any]) -> str | None:
    for field in ("capture_time", "source_capture_start"):
        value = example.get(field)
        if isinstance(value, str) and len(value) >= 10 and _is_iso_day(value[:10]):
            return value[:10]
    return None


def _is_iso_day(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _validate_fraction(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EmbedValidationError(f"reference {name} must be finite and within [0, 1]")
    try:
        result = float(value)
    except ValueError, OverflowError:
        raise EmbedValidationError(
            f"reference {name} must be finite and within [0, 1]"
        ) from None
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise EmbedValidationError(f"reference {name} must be finite and within [0, 1]")
    return result


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _inside_git(path: Path) -> bool:
    candidate = path if path.is_dir() else path.parent
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    return result.returncode == 0
