"""Strict configuration parsing and canonical identity helpers."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bird_recognition.embed.models import (
    EmbeddingModelRecord,
    EmbedValidationError,
    Sha256,
    SpeciesCandidate,
    SpeciesCandidateSet,
    TaggingConfig,
)

_DATABASE_URL_PATTERN = re.compile(
    r"(?i)\b(?:postgres(?:ql)?|postgresql\+[^:/\s]+)://[^\s\"'<>]+"
)
_CONNECTION_PARAMETER_PATTERN = re.compile(
    r"(?i)\b(hostaddr?|hostname|user(?:name)?|password|passfile|dbname|database|port|service)"
    r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_HOST_MESSAGE_PATTERN = re.compile(
    r"(?i)\b((?:host(?:name|\s+name)?|server at)\s+)"
    r"(?:\"[^\"]+\"|'[^']+'|[^\s,;]+)"
)
_EMBED_SETTING_ENVIRONMENT = {
    "database_url": "BIRD_RECOGNITION_DATABASE_URL",
    "model_dir": "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR",
    "species_list": "BIRD_RECOGNITION_SPECIES_LIST",
    "threshold": "BIRD_RECOGNITION_SPECIES_THRESHOLD",
}


class _DuplicateJsonKeyError(ValueError):
    """Raised when a JSON object repeats a key."""


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible content as deterministic UTF-8 bytes."""
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return serialized.encode("utf-8", errors="strict")
    except TypeError, ValueError, UnicodeError:
        raise EmbedValidationError(
            "content cannot be represented as canonical JSON"
        ) from None


def sha256_hex(value: bytes) -> Sha256:
    """Return the lowercase SHA-256 digest of bytes."""
    return hashlib.sha256(value).hexdigest()


def canonical_json_sha256(value: Any) -> Sha256:
    """Return the SHA-256 digest of canonical JSON content."""
    return sha256_hex(canonical_json_bytes(value))


def build_tagging_config(
    model: EmbeddingModelRecord,
    candidate_set: SpeciesCandidateSet,
    threshold: object = None,
    *,
    minimum_crop_width: int = 32,
    minimum_crop_height: int = 32,
    minimum_margin: object = None,
    reference_set_fingerprint: Sha256 | None = None,
    reference_split_mode: str | None = None,
    reference_min_similarity: object = None,
    reference_min_agreement: object = None,
) -> TaggingConfig:
    """Build canonical model, candidate, scoring, and decision identities."""
    validated_threshold = validate_threshold(threshold)
    validate_minimum_crop_dimensions(minimum_crop_width, minimum_crop_height)
    validated_margin = validate_minimum_margin(minimum_margin)
    if validated_margin is not None and len(candidate_set.candidates) < 2:
        raise EmbedValidationError("minimum margin requires at least two candidates")
    reference_values = (
        reference_set_fingerprint,
        reference_split_mode,
        reference_min_similarity,
        reference_min_agreement,
    )
    if any(value is not None for value in reference_values):
        if (
            not isinstance(reference_set_fingerprint, str)
            or not re.fullmatch(r"[0-9a-f]{64}", reference_set_fingerprint)
            or reference_split_mode not in {"source_video", "recording_day"}
        ):
            raise EmbedValidationError("reference setup identity is invalid")
        reference = {
            "set_fingerprint": reference_set_fingerprint,
            "split_mode": reference_split_mode,
            "minimum_similarity": _validate_reference_fraction(
                reference_min_similarity, "minimum similarity"
            ),
            "minimum_agreement": _validate_reference_fraction(
                reference_min_agreement, "minimum agreement"
            ),
            "algorithm_version": "top-five-cosine-consensus-v1",
        }
    elif any(value is not None for value in reference_values[1:]):
        raise EmbedValidationError("reference setup identity is incomplete")
    else:
        reference = None
    prompt_template, prompt_version = _prompt_identity(candidate_set.schema_version)
    scoring = {
        "schema_version": 1,
        "model_fingerprint": model.model_fingerprint,
        "candidate_set_fingerprint": candidate_set.candidate_set_fingerprint,
        "candidates": json.loads(candidate_set.candidates_json),
        "prompt_template": prompt_template,
        "prompt_version": prompt_version,
        "effective_logit_scale": model.logit_scale,
        "score_formula": (
            "effective_logit_scale * dot(normalized_image, normalized_text)"
        ),
        "normalization": "L2-unit-float32-tolerance-1e-5",
        "softmax": "stable-float64-v1",
        "tie_policy": "exact-equal-maximum-logits-v1",
        "score_order": "candidate-id-ascending",
    }
    scoring_json = canonical_json_bytes(scoring).decode("utf-8")
    scoring_fingerprint = canonical_json_sha256(scoring)
    canonical = {
        "schema_version": 1,
        "model_fingerprint": model.model_fingerprint,
        "model": json.loads(model.canonical_json),
        "candidate_set_fingerprint": candidate_set.candidate_set_fingerprint,
        "candidates": json.loads(candidate_set.candidates_json),
        "scoring_fingerprint": scoring_fingerprint,
        "scoring": scoring,
        "threshold": validated_threshold,
        "minimum_margin": validated_margin,
        "minimum_crop_width": minimum_crop_width,
        "minimum_crop_height": minimum_crop_height,
    }
    if reference is not None:
        canonical["reference"] = reference
    canonical_json = canonical_json_bytes(canonical).decode("utf-8")
    return TaggingConfig(
        config_fingerprint=canonical_json_sha256(canonical),
        model_fingerprint=model.model_fingerprint,
        candidate_set_fingerprint=candidate_set.candidate_set_fingerprint,
        scoring_fingerprint=scoring_fingerprint,
        prompt_template=prompt_template,
        prompt_version=prompt_version,
        effective_logit_scale=model.logit_scale,
        scoring_json=scoring_json,
        threshold=validated_threshold,
        minimum_margin=validated_margin,
        canonical_json=canonical_json,
        minimum_crop_width=minimum_crop_width,
        minimum_crop_height=minimum_crop_height,
        reference_set_fingerprint=reference_set_fingerprint,
        reference_split_mode=reference_split_mode,
        reference_min_similarity=(
            reference["minimum_similarity"] if reference is not None else None
        ),
        reference_min_agreement=(
            reference["minimum_agreement"] if reference is not None else None
        ),
    )


def _validate_reference_fraction(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EmbedValidationError(f"reference {name} must be finite and within [0, 1]")
    try:
        result = float(value)
    except OverflowError, ValueError:
        raise EmbedValidationError(
            f"reference {name} must be finite and within [0, 1]"
        ) from None
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise EmbedValidationError(f"reference {name} must be finite and within [0, 1]")
    return 0.0 if result == 0 else result


def validate_minimum_crop_dimensions(width: object, height: object) -> tuple[int, int]:
    """Validate the positive pixel dimensions used by crop-quality gates."""
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        raise EmbedValidationError("minimum crop dimensions must be positive integers")
    return width, height


def validate_minimum_margin(value: object = None) -> float | None:
    """Validate an optional candidate-relative score margin in [0, 1]."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EmbedValidationError("minimum margin must be finite and within [0, 1]")
    try:
        margin = float(value)
    except OverflowError, ValueError:
        raise EmbedValidationError(
            "minimum margin must be finite and within [0, 1]"
        ) from None
    if not math.isfinite(margin) or not 0 <= margin <= 1:
        raise EmbedValidationError("minimum margin must be finite and within [0, 1]")
    return 0.0 if margin == 0 else margin


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _prompt_identity(schema_version: int) -> tuple[str, str]:
    if schema_version == 1:
        return "a photo of {name}.", "species-photo-v1"
    if schema_version == 2:
        return (
            "a photo of {common_name} ({taxonomic_description}).",
            "species-taxonomy-photo-v2",
        )
    raise EmbedValidationError("unsupported candidate-set schema version")


def format_candidate_prompt(candidate: SpeciesCandidate, template: str) -> str:
    """Format the prompt for a candidate using its immutable candidate text."""
    if "{common_name}" in template and candidate.common_name is None:
        raise EmbedValidationError("candidate common name is required by its prompt")
    if "{taxonomic_description}" in template and (
        candidate.taxonomic_description is None
    ):
        raise EmbedValidationError(
            "candidate taxonomic description is required by its prompt"
        )
    try:
        return template.format(
            name=candidate.name,
            common_name=candidate.common_name,
            taxonomic_description=candidate.taxonomic_description,
        )
    except KeyError, ValueError:
        raise EmbedValidationError("candidate prompt template is invalid") from None


def load_species_candidates(path: Path) -> SpeciesCandidateSet:
    """Load and validate a canonical schema-1 or schema-2 candidate file."""
    try:
        content = path.read_text(encoding="utf-8")
        document = json.loads(
            content,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_json_constant,
        )
    except OSError, UnicodeError, json.JSONDecodeError, ValueError:
        raise EmbedValidationError(
            "species file is unreadable or invalid UTF-8 JSON"
        ) from None

    if not isinstance(document, dict):
        raise EmbedValidationError("species document must be a JSON object")
    schema_version = document.get("schema_version")
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise EmbedValidationError("unsupported species schema version")
    entry_key = "species" if schema_version == 1 else "candidates"
    if set(document) != {"schema_version", entry_key}:
        raise EmbedValidationError(
            f"schema-{schema_version} document must contain only "
            f"schema_version and {entry_key}"
        )
    values = document[entry_key]
    if not isinstance(values, list) or not values:
        raise EmbedValidationError(f"{entry_key} must be a nonempty array")

    candidates: list[SpeciesCandidate] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in values:
        if not isinstance(item, dict):
            raise EmbedValidationError("each candidate entry must be an object")
        if schema_version == 1:
            if set(item) != {"id", "name"}:
                raise EmbedValidationError(
                    "each schema-1 species entry must contain only id and name"
                )
            candidate = SpeciesCandidate(id=item["id"], name=item["name"])
        else:
            kind = item.get("kind")
            expected_fields = (
                {"id", "kind", "common_name", "taxonomic_description", "category"}
                if kind == "category"
                else {"id", "kind", "common_name", "taxonomic_description"}
            )
            if set(item) != expected_fields:
                raise EmbedValidationError(
                    "schema-2 candidate fields do not match its supported kind"
                )
            candidate = SpeciesCandidate(
                id=item["id"],
                kind=kind,
                common_name=item["common_name"],
                taxonomic_description=item["taxonomic_description"],
                category=item.get("category"),
            )
        candidate_id = candidate.id
        candidate_name = candidate.common_name or ""
        folded_id = candidate_id.casefold()
        folded_name = candidate_name.casefold()
        if folded_id == "unknown":
            raise EmbedValidationError("the candidate identifier 'unknown' is reserved")
        if folded_id in seen_ids:
            raise EmbedValidationError("candidate identifiers must be unique")
        if folded_name in seen_names:
            raise EmbedValidationError("candidate names must be unique")
        seen_ids.add(folded_id)
        seen_names.add(folded_name)
        candidates.append(candidate)

    candidates.sort(key=lambda candidate: candidate.id)
    if schema_version == 1:
        candidate_values = [
            {"id": candidate.id, "name": candidate.name} for candidate in candidates
        ]
    else:
        candidate_values = [
            {
                "id": candidate.id,
                "kind": candidate.kind,
                "common_name": candidate.common_name,
                "taxonomic_description": candidate.taxonomic_description,
                **({"category": candidate.category} if candidate.category else {}),
            }
            for candidate in candidates
        ]
    candidates_json = canonical_json_bytes(candidate_values).decode("utf-8")
    canonical_value = {"schema_version": schema_version, entry_key: candidate_values}
    canonical_json = canonical_json_bytes(canonical_value).decode("utf-8")
    return SpeciesCandidateSet(
        candidate_set_fingerprint=canonical_json_sha256(canonical_value),
        schema_version=schema_version,
        candidates=tuple(candidates),
        candidates_json=candidates_json,
        canonical_json=canonical_json,
        created_at=datetime.now(UTC),
    )


def validate_threshold(value: object = None) -> float:
    """Return a finite threshold in [0, 1], defaulting to 0.5."""
    if value is None:
        return 0.5
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise EmbedValidationError("threshold must be a finite number within [0, 1]")
    try:
        threshold = float(value)
    except OverflowError, ValueError:
        raise EmbedValidationError(
            "threshold must be a finite number within [0, 1]"
        ) from None
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise EmbedValidationError("threshold must be a finite number within [0, 1]")
    return 0.0 if threshold == 0 else threshold


def resolve_embed_configuration(
    command: str,
    *,
    explicit: Mapping[str, object],
    process_environment: Mapping[str, str | None],
    dotenv_environment: Mapping[str, str | None],
) -> dict[str, str | float]:
    """Resolve command settings in CLI, process, dotenv, then default order."""
    required_by_command = {
        "database-init": ("database_url",),
        "index": ("database_url", "model_dir", "species_list"),
        "inspect": ("database_url",),
        "evaluate-species": ("database_url",),
        "compare-species": ("database_url",),
        "benchmark-species": ("database_url",),
        "aggregate-visits": ("database_url",),
        "search": ("database_url", "model_dir"),
    }
    if command not in required_by_command:
        raise EmbedValidationError("unsupported embedding command")

    relevant = set(required_by_command[command])
    if command == "index":
        relevant.add("threshold")
    resolved: dict[str, str | float] = {}
    for setting in _EMBED_SETTING_ENVIRONMENT:
        if setting not in relevant:
            continue
        alias = _EMBED_SETTING_ENVIRONMENT[setting]
        value = explicit.get(setting)
        if value is None:
            value = process_environment.get(alias)
        if value is None:
            value = dotenv_environment.get(alias)
        if value is None:
            if setting == "threshold":
                resolved[setting] = validate_threshold()
                continue
            if setting in required_by_command[command]:
                raise EmbedValidationError(f"{setting.replace('_', ' ')} is required")
            continue
        if setting == "threshold":
            resolved[setting] = validate_threshold(value)
            continue
        if isinstance(value, Path):
            value = str(value)
        if not isinstance(value, str) or not value.strip():
            raise EmbedValidationError(f"{setting.replace('_', ' ')} must not be empty")
        normalized = value.strip()
        if setting == "database_url":
            validate_local_database_url(normalized)
        resolved[setting] = normalized
    return resolved


def _is_local_host(host: str) -> bool:
    normalized_host = host.rstrip(".").casefold()
    if normalized_host == "localhost":
        return True
    if normalized_host.startswith("/"):
        return True
    try:
        return ipaddress.ip_address(normalized_host).is_loopback
    except ValueError:
        return False


def validate_local_database_url(url: str) -> None:
    """Require a PostgreSQL URL that can connect only to a local service."""
    if not isinstance(url, str) or not url:
        raise EmbedValidationError(
            "database URL must target a local PostgreSQL service"
        )
    try:
        parsed = urlsplit(url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        if parsed.scheme.casefold() not in {"postgres", "postgresql"}:
            raise ValueError
        if not parsed.path.strip("/"):
            raise ValueError
        if "service" in query or "servicefile" in query:
            raise ValueError

        if parsed.netloc:
            authority_host = parsed.hostname
            if authority_host is not None and not _is_local_host(authority_host):
                raise ValueError
            if authority_host is None and not query.get("host"):
                raise ValueError
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError

        query_hosts = query.get("host", [])
        for host in query_hosts:
            if not host or not all(_is_local_host(entry) for entry in host.split(",")):
                raise ValueError

        for host_address in query.get("hostaddr", []):
            if not host_address or not all(
                _is_loopback_address(entry) for entry in host_address.split(",")
            ):
                raise ValueError
    except TypeError, ValueError:
        raise EmbedValidationError(
            "database URL must specify a database on a local PostgreSQL service"
        ) from None


def _is_loopback_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return False


def sanitize_error(message: str) -> str:
    """Redact database URLs and connection details from an error message."""
    sanitized = _DATABASE_URL_PATTERN.sub("[database URL redacted]", message)
    sanitized = _CONNECTION_PARAMETER_PATTERN.sub(
        lambda match: f"{match.group(1)}=[redacted]", sanitized
    )
    return _HOST_MESSAGE_PATTERN.sub(r"\1[redacted]", sanitized)
