"""RFC 9457 problem details and error translation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException


class ProblemDetails(BaseModel):
    """Machine-readable API problem response."""

    type: str
    title: str
    status: int
    detail: str
    code: str
    errors: list[dict[str, str]] | None = None


class APIError(Exception):
    """An expected API failure with a stable public error code."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str,
        *,
        errors: list[dict[str, str]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
        self.errors = errors


_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    422: "Validation Error",
    503: "Service Unavailable",
    500: "Internal Server Error",
}


def install_error_handlers(app: FastAPI) -> None:
    """Register stable, sanitized problem responses."""

    @app.exception_handler(APIError)
    async def api_error_handler(_: Request, error: APIError) -> JSONResponse:
        return _response(error.status, error.code, error.detail, errors=error.errors)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        errors = [
            {
                "field": ".".join(str(part) for part in item["loc"][1:]) or "request",
                "message": _validation_message(item),
            }
            for item in error.errors()
        ]
        return _response(
            422,
            "validation_error",
            "The request contains invalid fields.",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _: Request, error: StarletteHTTPException
    ) -> JSONResponse:
        status = error.status_code
        codes = {404: "not_found", 405: "method_not_allowed"}
        return _response(
            status,
            codes.get(status, "http_error"),
            "The requested resource is unavailable."
            if status == 404
            else "The request could not be completed.",
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(_: Request, __: Exception) -> JSONResponse:
        return _response(500, "internal_error", "An internal error occurred.")


def _response(
    status: int,
    code: str,
    detail: str,
    *,
    errors: list[dict[str, str]] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {
        "type": f"urn:bird-recognition:error:{code}",
        "title": _TITLES.get(status, "Request Error"),
        "status": status,
        "detail": detail,
        "code": code,
    }
    if errors is not None:
        content["errors"] = errors
    return JSONResponse(
        status_code=status,
        content=content,
        media_type="application/problem+json",
    )


def _validation_message(error: Mapping[str, Any]) -> str:
    message = str(error.get("msg", "Invalid value."))
    if "url" in message.casefold() or "path" in message.casefold():
        return "Invalid value."
    return message
