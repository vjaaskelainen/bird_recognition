"""API key authentication and local-bind checks."""

from __future__ import annotations

import ipaddress
import secrets
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Header, Request

from bird_recognition.api.errors import APIError
from bird_recognition.api.sessions import SESSION_COOKIE, SessionStore
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
    """Enforce the configured key or a valid owner session cookie."""
    settings: APISettings = request.app.state.settings
    if settings.api_key is None:
        return
    if supplied_key is not None and secrets.compare_digest(
        supplied_key.encode("utf-8"), settings.api_key.encode("utf-8")
    ):
        return
    sessions: SessionStore = request.app.state.sessions
    if sessions.validate(request.cookies.get(SESSION_COOKIE)):
        _require_same_origin(request)
        return
    raise APIError(401, "unauthorized", "A valid X-API-Key or session is required.")


def require_media_access(
    request: Request,
    supplied_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Protect unfiltered owner-review media; refuse it when no key is configured."""
    settings: APISettings = request.app.state.settings
    if settings.api_key is None:
        raise APIError(
            403,
            "media_disabled",
            "Unfiltered media requires BIRD_RECOGNITION_API_KEY to be configured.",
        )
    require_api_key(request, supplied_key)


def _require_same_origin(request: Request) -> None:
    """Reject cookie-authenticated state changes from other origins."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    host = request.headers.get("host")
    if origin is None or host is None or urlsplit(origin).netloc != host:
        raise APIError(403, "bad_origin", "The request origin is not allowed.")


Authenticated = Depends(require_api_key)
MediaAuthenticated = Depends(require_media_access)
