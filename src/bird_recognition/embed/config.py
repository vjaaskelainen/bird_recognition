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
) -> TaggingConfig:
    """Build canonical model, candidate, scoring, and decision identities."""
    validated_threshold = validate_threshold(threshold)
    scoring = {
        "schema_version": 1,
        "model_fingerprint": model.model_fingerprint,
        "candidate_set_fingerprint": candidate_set.candidate_set_fingerprint,
        "candidates": json.loads(candidate_set.candidates_json),
        "prompt_template": "a photo of {name}.",
        "prompt_version": "species-photo-v1",
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
    }
    canonical_json = canonical_json_bytes(canonical).decode("utf-8")
    return TaggingConfig(
        config_fingerprint=canonical_json_sha256(canonical),
        model_fingerprint=model.model_fingerprint,
        candidate_set_fingerprint=candidate_set.candidate_set_fingerprint,
        scoring_fingerprint=scoring_fingerprint,
        prompt_template="a photo of {name}.",
        prompt_version="species-photo-v1",
        effective_logit_scale=model.logit_scale,
        scoring_json=scoring_json,
        threshold=validated_threshold,
        canonical_json=canonical_json,
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def load_species_candidates(path: Path) -> SpeciesCandidateSet:
    """Load and validate a nonempty, canonical species-candidate file."""
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

    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "species",
    }:
        raise EmbedValidationError(
            "species document must contain only schema_version and species"
        )
    schema_version = document["schema_version"]
    if type(schema_version) is not int or schema_version != 1:
        raise EmbedValidationError("unsupported species schema version")

    species = document["species"]
    if not isinstance(species, list) or not species:
        raise EmbedValidationError("species must be a nonempty array")

    candidates: list[SpeciesCandidate] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for item in species:
        if not isinstance(item, dict) or set(item) != {"id", "name"}:
            raise EmbedValidationError(
                "each species entry must contain only id and name"
            )
        candidate_id = item["id"]
        name = item["name"]
        if not isinstance(candidate_id, str) or not isinstance(name, str):
            raise EmbedValidationError("species identifiers and names must be strings")
        candidate_id = candidate_id.strip()
        name = name.strip()
        if not candidate_id or not name:
            raise EmbedValidationError(
                "species identifiers and names must not be blank"
            )
        folded_id = candidate_id.casefold()
        folded_name = name.casefold()
        if folded_id == "unknown":
            raise EmbedValidationError("the species identifier 'unknown' is reserved")
        if folded_id in seen_ids:
            raise EmbedValidationError("species identifiers must be unique")
        if folded_name in seen_names:
            raise EmbedValidationError("species names must be unique")
        seen_ids.add(folded_id)
        seen_names.add(folded_name)
        candidates.append(SpeciesCandidate(id=candidate_id, name=name))

    candidates.sort(key=lambda candidate: candidate.id)
    candidate_values = [
        {"id": candidate.id, "name": candidate.name} for candidate in candidates
    ]
    candidates_json = canonical_json_bytes(candidate_values).decode("utf-8")
    canonical_value = {"schema_version": 1, "species": candidate_values}
    canonical_json = canonical_json_bytes(canonical_value).decode("utf-8")
    return SpeciesCandidateSet(
        candidate_set_fingerprint=canonical_json_sha256(canonical_value),
        schema_version=1,
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
