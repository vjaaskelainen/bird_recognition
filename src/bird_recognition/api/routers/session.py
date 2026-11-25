"""Same-origin owner session exchange for browser clients."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.security import require_api_key
from bird_recognition.api.sessions import IDLE_SECONDS, SESSION_COOKIE

router = APIRouter(tags=["session"])


class SessionRequest(BaseModel):
    """Credentials exchanged once for a session cookie."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=512)


@router.post(
    "/session",
    status_code=204,
    summary="Exchange the API key for a session cookie",
    responses={
        401: {"model": ProblemDetails},
        403: {"model": ProblemDetails},
    },
)
def create_session(body: SessionRequest, request: Request) -> Response:
    """Set an HttpOnly same-site cookie when the supplied key is correct."""
    configured = request.app.state.settings.api_key
    if configured is None:
        raise APIError(
            403,
            "key_not_configured",
            "The service has no API key configured, so sessions are unavailable.",
        )
    if not secrets.compare_digest(body.key.encode("utf-8"), configured.encode("utf-8")):
        raise APIError(401, "unauthorized", "The key is not valid.")
    token = request.app.state.sessions.create()
    response = Response(status_code=204)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
        max_age=IDLE_SECONDS,
    )
    return response


@router.get(
    "/session",
    status_code=204,
    summary="Check whether the caller is authenticated",
    dependencies=[Depends(require_api_key)],
    responses={401: {"model": ProblemDetails}},
)
def get_session() -> Response:
    """Return 204 when authenticated so the UI can skip the key prompt."""
    return Response(status_code=204)


@router.delete(
    "/session",
    status_code=204,
    summary="End the session",
)
def delete_session(request: Request) -> Response:
    """Invalidate the cookie's token and clear the cookie."""
    request.app.state.sessions.revoke(request.cookies.get(SESSION_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return response
