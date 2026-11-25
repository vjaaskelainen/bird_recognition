"""Configuration resolution for the optional local HTTP service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, find_dotenv


@dataclass(frozen=True, slots=True)
class APISettings:
    """Resolved HTTP service settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    api_key: str | None = None
    jobs_dir: Path | None = None
    allowed_roots: tuple[Path, ...] = ()
    database_url: str | None = None
    model_dir: Path | None = None


def load_settings(
    overrides: Mapping[str, object] | None = None,
    *,
    process_environment: Mapping[str, str | None] | None = None,
    dotenv_environment: Mapping[str, str | None] | None = None,
) -> APISettings:
    """Resolve explicit values, process environment, dotenv, then defaults."""
    process_values = (
        process_environment if process_environment is not None else os.environ
    )
    if dotenv_environment is None:
        dotenv_path = find_dotenv(usecwd=True)
        dotenv_values_map = dotenv_values(dotenv_path) if dotenv_path else {}
    else:
        dotenv_values_map = dotenv_environment

    def value(name: str, override_name: str, default: object = None) -> object:
        if overrides is not None and override_name in overrides:
            return overrides[override_name]
        environment_name = f"BIRD_RECOGNITION_API_{name}"
        candidate = process_values.get(environment_name)
        if candidate is None or candidate == "":
            candidate = dotenv_values_map.get(environment_name)
        if candidate is None or candidate == "":
            return default
        return candidate

    host_value = value("HOST", "host", "127.0.0.1")
    port_value = value("PORT", "port", "8000")
    if not isinstance(host_value, str) or not host_value.strip():
        raise ValueError("API host must not be empty")
    try:
        port = int(port_value)
    except TypeError, ValueError:
        raise ValueError("API port must be an integer from 1 to 65535") from None
    if not 1 <= port <= 65535:
        raise ValueError("API port must be an integer from 1 to 65535")

    api_key = _optional_string(
        value("KEY", "api_key"),
    )
    jobs_dir = _optional_path(value("JOBS_DIR", "jobs_dir"))
    allowed_roots_value = value("ALLOWED_ROOTS", "allowed_roots")
    if isinstance(allowed_roots_value, str):
        allowed_roots = tuple(
            Path(item).expanduser().resolve()
            for item in allowed_roots_value.split(os.pathsep)
            if item.strip()
        )
    elif isinstance(allowed_roots_value, (tuple, list)):
        allowed_roots = tuple(
            Path(item).expanduser().resolve() for item in allowed_roots_value
        )
    else:
        allowed_roots = ()

    database_url = _optional_string(
        _environment_value(
            "BIRD_RECOGNITION_DATABASE_URL",
            process_values,
            dotenv_values_map,
        )
    )
    model_dir = _optional_path(
        _environment_value(
            "BIRD_RECOGNITION_BIOCLIP_MODEL_DIR",
            process_values,
            dotenv_values_map,
        )
    )
    return APISettings(
        host=host_value.strip(),
        port=port,
        api_key=api_key,
        jobs_dir=jobs_dir,
        allowed_roots=allowed_roots,
        database_url=database_url,
        model_dir=model_dir,
    )


def _environment_value(
    name: str,
    process_values: Mapping[str, str | None],
    dotenv_values_map: Mapping[str, str | None],
) -> str | None:
    return process_values.get(name) or dotenv_values_map.get(name)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("API settings must be strings")
    return value.strip() or None


def _optional_path(value: object) -> Path | None:
    string_value = _optional_string(value)
    return Path(string_value).expanduser().resolve() if string_value else None
