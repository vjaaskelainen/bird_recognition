"""Static serving of the built web UI with SPA fallback."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
_DEFAULT_DIR = Path("frontend") / "dist"


def resolve_ui_dir(configured: Path | None) -> Path | None:
    """Return the bundle directory when it holds an index.html."""
    candidate = configured if configured is not None else _DEFAULT_DIR
    return candidate if (candidate / "index.html").is_file() else None


def mount_ui(app: FastAPI, ui_dir: Path | None) -> None:
    """Serve bundle files for GET requests no API route handled."""
    root = resolve_ui_dir(ui_dir)
    if root is None:
        return
    resolved = root.resolve()

    @app.middleware("http")
    async def serve_ui(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        path = request.url.path.lstrip("/")
        if (
            response.status_code != 404
            or request.method != "GET"
            or path == "v1"
            or path.startswith("v1/")
        ):
            return response
        target = (resolved / path).resolve()
        if path and target.is_file() and target.is_relative_to(resolved):
            served = FileResponse(target)
        else:
            served = FileResponse(resolved / "index.html")
        served.headers.update(_HEADERS)
        return served
