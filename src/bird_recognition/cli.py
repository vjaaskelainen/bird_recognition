"""Command-line path validation and entry point."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

from bird_recognition.ingest.detection import (
    MEGADETECTOR_CONFIG,
    MEGADETECTOR_VARIANT,
    Detector,
    MegaDetectorAdapter,
)
from bird_recognition.ingest.models import IngestSettings, ValidationError
from bird_recognition.ingest.pipeline import run_batch
from bird_recognition.ingest.video import discover_videos

_DEFAULT_EXTENSIONS = ".mp4,.mov,.m4v,.mkv,.avi,.mpeg,.mpg"


def canonicalize_input(path: str | Path) -> Path:
    """Return an existing input directory's canonical path."""
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ValidationError(f"input path cannot be resolved: {candidate}") from error
    if not resolved.is_dir():
        raise ValidationError(f"input path is not a directory: {resolved}")
    return resolved


def canonicalize_output(path: str | Path) -> Path:
    """Return a canonical output path without creating it."""
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as error:
        raise ValidationError(f"output path cannot be resolved: {candidate}") from error
    if resolved.exists() and not resolved.is_dir():
        raise ValidationError(f"output path is not a directory: {resolved}")
    return resolved


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _git_root(path: Path) -> Path | None:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode:
        return None
    return Path(result.stdout.strip()).resolve()


def _environment_defaults() -> dict[str, str | None]:
    dotenv_path = find_dotenv(usecwd=True)
    dotenv_defaults = dotenv_values(dotenv_path) if dotenv_path else {}
    return {**dotenv_defaults, **os.environ}


def validate_destination(input_root: Path, output_root: Path) -> None:
    """Reject overlapping input/output trees and version-controlled destinations."""
    if _overlaps(input_root, output_root):
        raise ValidationError("input and output directories must be disjoint")
    project_root = _git_root(Path(__file__).resolve())
    working_root = _git_root(Path.cwd())
    destination_root = _git_root(output_root)
    roots = {
        root
        for root in (project_root, working_root, destination_root)
        if root is not None
    }
    for root in roots:
        if _overlaps(root, input_root):
            raise ValidationError("input footage must be outside the Git repository")
        if _overlaps(root, output_root):
            raise ValidationError("output directory must be outside the Git repository")
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise ValidationError("cannot verify whether output is Git-tracked")
        for raw_path in result.stdout.split(b"\0"):
            if raw_path:
                tracked_path = (root / Path(raw_path.decode("utf-8"))).resolve()
                if _overlaps(tracked_path, output_root):
                    raise ValidationError(
                        "output directory overlaps Git-tracked content"
                    )


def _build_parser() -> argparse.ArgumentParser:
    environment = _environment_defaults()
    parser = argparse.ArgumentParser(prog="bird-recognition")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest_parser = commands.add_parser(
        "ingest",
        help="ingest local trail-camera videos",
        description=(
            "Filter local videos with MegaDetector V6 MIT YOLOv9-C and save animal "
            "crops."
        ),
        epilog=(
            "Defaults: interval=1.0s, animal threshold=0.2, person threshold=0.2. "
            "Extensions: .mp4,.mov,.m4v,.mkv,.avi,.mpeg,.mpg. "
            "Lighting rule: pixel-evidence-v1. Keep output outside Git and input. "
            f"Model variant: {MEGADETECTOR_VARIANT}. Model weights and config are "
            "local-only; ingestion never downloads them."
        ),
    )
    ingest_parser.add_argument(
        "--input", required=True, type=Path, help="video directory"
    )
    ingest_parser.add_argument(
        "--output", required=True, type=Path, help="private output directory"
    )
    ingest_parser.add_argument(
        "--interval",
        type=float,
        default=environment.get("BIRD_RECOGNITION_INTERVAL") or "1.0",
        metavar="SECONDS",
    )
    ingest_parser.add_argument(
        "--animal-threshold",
        type=float,
        default=environment.get("BIRD_RECOGNITION_ANIMAL_THRESHOLD") or "0.2",
        metavar="VALUE",
    )
    ingest_parser.add_argument(
        "--person-threshold",
        type=float,
        default=environment.get("BIRD_RECOGNITION_PERSON_THRESHOLD") or "0.2",
        metavar="VALUE",
    )
    ingest_parser.add_argument(
        "--model",
        type=Path,
        default=environment.get("BIRD_RECOGNITION_MEGADETECTOR_MODEL") or None,
        metavar="PATH",
        help=(
            "local MDV6-mit-yolov9-c weights file; defaults to "
            "BIRD_RECOGNITION_MEGADETECTOR_MODEL"
        ),
    )
    ingest_parser.add_argument(
        "--model-config",
        type=Path,
        default=environment.get("BIRD_RECOGNITION_MEGADETECTOR_CONFIG") or None,
        metavar="PATH",
        help=(
            f"local {MEGADETECTOR_CONFIG} file; defaults to that filename beside "
            "--model or BIRD_RECOGNITION_MEGADETECTOR_CONFIG"
        ),
    )
    ingest_parser.add_argument(
        "--extensions",
        default=environment.get("BIRD_RECOGNITION_EXTENSIONS") or _DEFAULT_EXTENSIONS,
        help="comma-separated supported filename extensions",
    )
    return parser


def _parse_extensions(value: str) -> tuple[str, ...]:
    extensions = tuple(item.strip() for item in value.split(",") if item.strip())
    if not extensions:
        raise ValidationError("at least one supported video extension is required")
    return extensions


def _render_summary(report: dict[str, object]) -> None:
    """Print source, frame, crop, and failure counts."""
    print(f"Run status: {report['status']}")
    if report["status"] == "no_input":
        print("No supported video inputs found.")
    for key in (
        "processed_sources",
        "skipped_sources",
        "failed_sources",
        "sampled",
        "person_excluded",
        "no_animal",
        "retained",
        "failed",
        "crops",
    ):
        print(f"{key.replace('_', ' ').title()}: {report.get(key, 0)}")
    for item in report.get("errors", []):
        if isinstance(item, dict):
            source = item.get("source", "unknown source")
            frame = f" frame {item['frame']}" if "frame" in item else ""
            print(
                f"Error: {source}{frame}: {item.get('error', 'processing failed')}",
                file=sys.stderr,
            )
        else:
            print(f"Error: {item}", file=sys.stderr)


def main(argv: list[str] | None = None, detector: Detector | None = None) -> int:
    """Run the bird-recognition command."""
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        input_root = canonicalize_input(arguments.input)
        output_root = canonicalize_output(arguments.output)
        validate_destination(input_root, output_root)
        extensions = _parse_extensions(arguments.extensions)
        settings = IngestSettings(
            interval=arguments.interval,
            animal_threshold=arguments.animal_threshold,
            person_threshold=arguments.person_threshold,
            extensions=extensions,
            model_path=Path(arguments.model).expanduser() if arguments.model else None,
            model_config_path=(
                Path(arguments.model_config).expanduser()
                if arguments.model_config
                else None
            ),
        )
        videos = discover_videos(input_root, settings.extensions)
        if detector is None and videos:
            if settings.model_path is None:
                raise ValidationError(
                    "provide --model or set BIRD_RECOGNITION_MEGADETECTOR_MODEL"
                )
            model_path = settings.model_path.resolve(strict=True)
            if not model_path.is_file():
                raise ValidationError(f"MegaDetector model is not a file: {model_path}")
            config_candidate = settings.model_config_path or (
                model_path.parent / MEGADETECTOR_CONFIG
            )
            try:
                model_config_path = config_candidate.resolve(strict=True)
            except OSError as error:
                raise ValidationError(
                    f"MegaDetector model config cannot be resolved: {config_candidate}"
                ) from error
            if not model_config_path.is_file():
                raise ValidationError(
                    f"MegaDetector model config is not a file: {model_config_path}"
                )
            settings = replace(
                settings,
                model_path=model_path,
                model_config_path=model_config_path,
            )
            try:
                detector = MegaDetectorAdapter(model_path, model_config_path)
            except Exception as error:
                raise ValidationError(
                    f"MegaDetector preflight failed: {error}"
                ) from error
            settings = replace(
                settings,
                detector_version=detector.model_version,
                model_sha256=detector.model_sha256,
                model_config_sha256=detector.model_config_sha256,
                model_variant=detector.model_variant,
            )
        if detector is None:
            detector = _NoInferenceDetector()
        if settings.model_variant != "unconfigured":
            print(
                f"Detector model: {settings.model_variant} "
                f"({settings.detector_version})"
            )
        summary, report = run_batch(input_root, output_root, settings, detector)
        del summary
        _render_summary(report)
        return 0 if report["status"] in {"complete", "no_input"} else 1
    except (ValidationError, OSError, ValueError) as error:
        print(f"Preflight error: {error}", file=sys.stderr)
        return 2
    except Exception as error:
        print(f"Ingestion error: {error}", file=sys.stderr)
        return 1


class _NoInferenceDetector:
    def detect(self, image: object) -> list[object]:
        raise RuntimeError("no detector configured")


if __name__ == "__main__":
    raise SystemExit(main())
