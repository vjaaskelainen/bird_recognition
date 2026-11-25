"""API key authentication and local-bind checks."""

from __future__ import annotations

import ipaddress
import secrets
from typing import Annotated

from fastapi import Depends, Header, Request

from bird_recognition.api.errors import APIError
from bird_recognition.api.settings import APISettings


def is_loopback_host(host: str) -> bool:
    """Return whether a bind host resolves syntactically to loopback."""
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind(settings: APISettings) -> None:
    """Refuse non-loopback service exposure without a configured key."""
    if not is_loopback_host(settings.host) and not settings.api_key:
        raise ValueError("non-loopback API binding requires BIRD_RECOGNITION_API_KEY")


def require_api_key(
    request: Request,
    supplied_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Enforce the configured key for all routes except the health endpoint."""
    settings: APISettings = request.app.state.settings
    if settings.api_key is None:
        return
    if supplied_key is None or not secrets.compare_digest(
        supplied_key.encode("utf-8"), settings.api_key.encode("utf-8")
    ):
        raise APIError(401, "unauthorized", "A valid X-API-Key is required.")


Authenticated = Depends(require_api_key)
