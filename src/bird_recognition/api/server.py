"""Console entry point for serving the HTTP API and exporting its contract."""

from __future__ import annotations

import argparse
from pathlib import Path

from bird_recognition.api.app import create_app
from bird_recognition.api.security import validate_bind
from bird_recognition.api.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    """Serve the API or export/check its generated OpenAPI document."""
    parser = argparse.ArgumentParser(prog="bird-recognition-api")
    commands = parser.add_subparsers(dest="command", required=True)
    serve_parser = commands.add_parser("serve", help="start the local HTTP service")
    serve_parser.add_argument("--host")
    serve_parser.add_argument("--port", type=int)
    export_parser = commands.add_parser(
        "export-openapi", help="write or check the generated OpenAPI contract"
    )
    export_parser.add_argument("--check", action="store_true")
    export_parser.add_argument(
        "--output", type=Path, default=Path("docs/api/openapi.json")
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "export-openapi":
        from bird_recognition.api.openapi import export_openapi

        current = export_openapi(arguments.output, check=arguments.check)
        if not current:
            if arguments.check:
                parser.exit(1, "OpenAPI document is missing or stale.\n")
            return 1
        return 0

    settings = load_settings(
        {
            key: value
            for key, value in (("host", arguments.host), ("port", arguments.port))
            if value is not None
        }
    )
    try:
        validate_bind(settings)
    except ValueError as error:
        parser.error(str(error))
    import uvicorn

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        workers=1,
    )
    return 0
