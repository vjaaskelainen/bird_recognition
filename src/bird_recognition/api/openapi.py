"""Deterministic OpenAPI export and drift checking."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_openapi() -> dict[str, Any]:
    """Generate the API's OpenAPI 3.1 document."""
    from bird_recognition.api.app import create_app
    from bird_recognition.api.settings import APISettings

    document = create_app(APISettings()).openapi()
    document["openapi"] = "3.1.0"
    document["info"]["version"] = "1.0.0"
    problem_schema = {
        "content": {
            "application/problem+json": {
                "schema": {
                    "$ref": "#/components/schemas/ProblemDetails",
                }
            }
        }
    }
    for path in document.get("paths", {}).values():
        for operation in path.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            for status in ("400", "401", "403", "404", "409", "422", "500", "503"):
                response = operation["responses"].setdefault(
                    status,
                    {"description": "Problem details response."},
                )
                response["content"] = problem_schema["content"]
    return document


def export_openapi(output: Path, *, check: bool = False) -> bool:
    """Write the canonical OpenAPI JSON or report whether it is current."""
    document = build_openapi()
    rendered = (
        json.dumps(
            document,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    target = Path(output)
    if check:
        try:
            return target.read_text(encoding="utf-8") == rendered
        except OSError:
            return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(rendered, encoding="utf-8", newline="\n")
    return True
