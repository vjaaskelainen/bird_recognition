"""Command-line path validation and entry point."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from dotenv import dotenv_values, find_dotenv

from bird_recognition.ingest.detection import (
    MEGADETECTOR_CONFIG,
    MEGADETECTOR_VARIANT,
    Detector,
    MegaDetectorAdapter,
)
from bird_recognition.ingest.models import (
    IngestSettings,
    ProcessingError,
    ValidationError,
)
from bird_recognition.ingest.pipeline import run_batch
from bird_recognition.ingest.video import discover_videos, iter_video_frames

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


def _add_case_ids(items: list[dict[str, object]]) -> list[dict[str, object]]:
    from bird_recognition.ingest.manifest import stable_case_id

    for item in items:
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            continue
        digest = provenance.get("source_content_sha256")
        frame_number = provenance.get("frame_number")
        detection_id = provenance.get("detection_id")
        box = provenance.get("detection_box_normalized")
        if (
            not isinstance(digest, str)
            or type(frame_number) is not int
            or not isinstance(detection_id, str)
            or not isinstance(box, (list, tuple))
            or len(box) != 4
        ):
            continue
        case_id = stable_case_id(
            digest,
            frame_number,
            detection_id,
            tuple(float(coordinate) for coordinate in box),
        )
        provenance["case_id"] = case_id
        item["case_id"] = case_id
    return items


def _candidate_records(run_data: dict[str, object]) -> list[dict[str, object]]:
    values = run_data.get("candidates")
    if isinstance(values, dict):
        values = values.get("candidates", values.get("species"))
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _add_candidate_details(
    run_data: dict[str, object], items: list[dict[str, object]]
) -> None:
    records = {record.get("id"): record for record in _candidate_records(run_data)}
    for item in items:
        decision = item.get("decision")
        if not isinstance(decision, dict):
            continue
        assigned_id = decision.get("assigned_species_id")
        candidate = records.get(assigned_id)
        if candidate is not None:
            kind = candidate.get("kind", "species")
            decision["assigned_candidate_kind"] = kind
            decision["assigned_category"] = candidate.get("category")
            decision["assigned_candidate"] = candidate
        scores = decision.get("candidate_scores")
        if isinstance(scores, list):
            for score in scores:
                if isinstance(score, dict) and (record := records.get(score.get("id"))):
                    score["kind"] = record.get("kind", "species")
                    score["category"] = record.get("category")


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


def extract_frame(
    input_video: str | Path, timestamp: float, output_folder: str | Path
) -> Path:
    """Save the first frame at or after elapsed seconds as PNG; return its path."""
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValidationError("timestamp must be finite and non-negative")
    source = Path(input_video).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValidationError(f"input video is not a file: {source}")
    output_root = canonicalize_output(output_folder)
    validate_destination(source.parent, output_root)
    destination = output_root / f"{source.name}_frame_{timestamp}s.png"
    if destination.exists():
        raise ValidationError(f"output image already exists: {destination}")
    start_time = None
    last_elapsed = -1.0
    with closing(iter_video_frames(source)) as frames:
        for frame_number, pts, time_base, image in frames:
            if pts is None or time_base is None or time_base <= 0:
                raise ProcessingError(
                    f"frame timing is unavailable at frame {frame_number} (PTS)"
                )
            presentation_time = pts * time_base
            if start_time is None:
                start_time = presentation_time
            elapsed = float(presentation_time - start_time)
            if not math.isfinite(elapsed) or elapsed <= last_elapsed:
                raise ProcessingError(
                    f"non-monotonic frame timing at frame {frame_number} (PTS)"
                )
            last_elapsed = elapsed
            if elapsed < timestamp:
                continue
            output_root.mkdir(parents=True, exist_ok=True)
            try:
                output = destination.open("xb")
            except FileExistsError as error:
                raise ValidationError(
                    f"output image already exists: {destination}"
                ) from error
            try:
                with output:
                    image.save(output, format="PNG")
            except Exception as error:
                destination.unlink(missing_ok=True)
                raise ProcessingError(f"failed to save frame: {error}") from error
            return destination
    raise ProcessingError(f"no frame at or after {timestamp} seconds: {source}")


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
        "--crop-context",
        type=float,
        default=None,
        metavar="FRACTION",
        help="proportional context expansion per side, clipped to frame bounds",
    )
    ingest_parser.add_argument(
        "--crop-policy",
        choices=("legacy-tight-v1", "context-v1"),
        default="legacy-tight-v1",
        help="versioned crop geometry policy",
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
    frame_parser = commands.add_parser(
        "extract-frame",
        help="save a full-resolution video frame as PNG",
        description=(
            "Save the first frame at or after the requested seconds from the first "
            "decoded frame. No detector or privacy filtering is applied. Keep "
            "input and output outside Git and in disjoint directories."
        ),
    )
    frame_parser.add_argument(
        "--input", required=True, type=Path, help="input video file"
    )
    frame_parser.add_argument(
        "--timestamp", required=True, type=float, metavar="SECONDS"
    )
    frame_parser.add_argument(
        "--output", required=True, type=Path, help="private output directory"
    )

    database_parser = commands.add_parser(
        "database-init", help="initialize the local embedding database schema"
    )
    database_parser.add_argument(
        "--database-url", help="local PostgreSQL connection URL"
    )
    database_parser.add_argument("--json", action="store_true")

    index_parser = commands.add_parser("index", help="index retained animal crops")
    index_parser.add_argument("--manifest", required=True, type=Path)
    index_parser.add_argument("--crop-root", type=Path)
    index_parser.add_argument(
        "--species-list",
    )
    index_parser.add_argument(
        "--model-dir",
    )
    index_parser.add_argument("--threshold")
    index_parser.add_argument(
        "--input-view",
        choices=("fit-pad-v1", "legacy-center-crop-v1"),
        default="fit-pad-v1",
    )
    index_parser.add_argument("--minimum-crop-width", type=int, default=32)
    index_parser.add_argument("--minimum-crop-height", type=int, default=32)
    index_parser.add_argument(
        "--database-url",
        help="local PostgreSQL connection URL",
    )
    index_parser.add_argument("--json", action="store_true")

    inspect_parser = commands.add_parser(
        "inspect", help="inspect persisted embedding runs and decisions"
    )
    inspect_parser.add_argument(
        "--database-url", help="local PostgreSQL connection URL"
    )
    selection = inspect_parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--run-id", type=str)
    selection.add_argument("--list-runs", action="store_true")
    inspect_parser.add_argument("--crop-id")
    inspect_parser.add_argument("--json", action="store_true")

    evaluation_parser = commands.add_parser(
        "evaluate-species", help="evaluate persisted species decisions against labels"
    )
    evaluation_parser.add_argument("--run-id", required=True)
    evaluation_parser.add_argument("--labels", required=True, type=Path)
    evaluation_parser.add_argument("--output", required=True, type=Path)
    evaluation_parser.add_argument("--database-url")
    evaluation_parser.add_argument("--json", action="store_true")
    comparison_parser = commands.add_parser(
        "compare-species", help="compare persisted species runs against shared labels"
    )
    comparison_parser.add_argument("--run-id", action="append", required=True)
    comparison_parser.add_argument("--labels", required=True, type=Path)
    comparison_parser.add_argument("--output", required=True, type=Path)
    comparison_parser.add_argument("--database-url")
    comparison_parser.add_argument("--json", action="store_true")
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
    if arguments.command in {
        "database-init",
        "index",
        "inspect",
        "evaluate-species",
        "compare-species",
    }:
        if arguments.command == "compare-species" and len(arguments.run_id) < 2:
            parser.error("compare-species requires at least two --run-id values")
        if (
            arguments.command == "inspect"
            and arguments.crop_id
            and not arguments.run_id
        ):
            parser.error("--crop-id requires --run-id")
        return _dispatch_embed_command(arguments)
    try:
        if arguments.command == "extract-frame":
            destination = extract_frame(
                arguments.input, arguments.timestamp, arguments.output
            )
            print(f"Saved frame: {destination}")
            return 0
        input_root = canonicalize_input(arguments.input)
        output_root = canonicalize_output(arguments.output)
        validate_destination(input_root, output_root)
        extensions = _parse_extensions(arguments.extensions)
        settings = IngestSettings(
            interval=arguments.interval,
            animal_threshold=arguments.animal_threshold,
            person_threshold=arguments.person_threshold,
            crop_context=arguments.crop_context,
            crop_policy=arguments.crop_policy,
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
        label = (
            "Frame extraction" if arguments.command == "extract-frame" else "Ingestion"
        )
        print(f"{label} error: {error}", file=sys.stderr)
        return 1


def _dispatch_embed_command(arguments: argparse.Namespace) -> int:
    from uuid import UUID

    from bird_recognition.embed.config import (
        EmbedValidationError,
        resolve_embed_configuration,
        sanitize_error,
    )
    from bird_recognition.embed.models import (
        EmbedError,
        PreflightError,
        RunStatus,
        StorageError,
    )
    from bird_recognition.embed.scoring import (
        RELATIVE_CONFIDENCE_WARNING,
        SINGLE_CANDIDATE_WARNING,
    )
    from bird_recognition.embed.storage import PgVectorStore, initialize_database

    try:
        dotenv_path = find_dotenv(usecwd=True)
        dotenv_environment = dotenv_values(dotenv_path) if dotenv_path else {}
        resolved = resolve_embed_configuration(
            arguments.command,
            explicit={
                "database_url": arguments.database_url,
                "model_dir": getattr(arguments, "model_dir", None),
                "species_list": getattr(arguments, "species_list", None),
                "threshold": getattr(arguments, "threshold", None),
            },
            process_environment=os.environ,
            dotenv_environment=dotenv_environment,
        )
        arguments.database_url = resolved["database_url"]
        if arguments.command == "database-init":
            result = initialize_database(arguments.database_url)
            payload = {
                "schema_version": 1,
                "status": "initialized",
                "database_schema_version": result.schema_version,
                "vector_available": result.vector_available,
                "changes_applied": result.changes_applied,
            }
            run = None
        elif arguments.command == "evaluate-species":
            from bird_recognition.embed.evaluation import (
                build_evaluation_report,
                load_label_file,
                validate_report_destination,
                write_evaluation_report,
            )

            run_id = UUID(arguments.run_id)
            load_label_file(arguments.labels)
            output_path = validate_report_destination(arguments.output)
            with closing(PgVectorStore(arguments.database_url)) as store:
                try:
                    store.preflight(read_only=True)
                except StorageError as error:
                    raise PreflightError(str(error)) from None
                run_data, items = store.inspect_run(run_id)
                _add_case_ids(items)
                report = build_evaluation_report(
                    run_data,
                    items,
                    arguments.labels,
                    expected_run_id=run_id,
                )
                saved_path = write_evaluation_report(report, output_path)
            payload = {
                "schema_version": 1,
                "status": "evaluated",
                "output": str(saved_path),
                "report": report,
            }
            run = None
        elif arguments.command == "compare-species":
            from bird_recognition.embed.evaluation import (
                build_comparison_report,
                load_label_file,
                validate_report_destination,
                write_evaluation_report,
            )

            run_ids = [UUID(value) for value in arguments.run_id]
            load_label_file(arguments.labels)
            output_path = validate_report_destination(arguments.output)
            with closing(PgVectorStore(arguments.database_url)) as store:
                try:
                    store.preflight(read_only=True)
                except StorageError as error:
                    raise PreflightError(str(error)) from None
                run_entries = []
                for run_id in run_ids:
                    run_data, items = store.inspect_run(run_id)
                    run_entries.append((run_data, _add_case_ids(items)))
                report = build_comparison_report(
                    run_entries,
                    arguments.labels,
                    expected_run_ids=run_ids,
                )
                saved_path = write_evaluation_report(report, output_path)
            payload = {
                "schema_version": 1,
                "status": "compared",
                "output": str(saved_path),
                "report": report,
            }
            run = None
        elif arguments.command == "inspect":
            store = PgVectorStore(arguments.database_url)
            try:
                store.preflight(read_only=True)
            except StorageError as error:
                raise PreflightError(str(error)) from None
            if arguments.list_runs:
                payload = {"schema_version": 1, "runs": store.list_runs()}
            else:
                run_data, items = store.inspect_run(
                    UUID(arguments.run_id), arguments.crop_id
                )
                _add_case_ids(items)
                species_data = run_data.get("candidates", {})
                species = (
                    species_data.get("candidates", species_data.get("species", []))
                    if isinstance(species_data, dict)
                    else []
                )
                _add_candidate_details(run_data, items)
                warnings = [RELATIVE_CONFIDENCE_WARNING]
                if len(species) == 1:
                    warnings.append(SINGLE_CANDIDATE_WARNING)
                run_data["warnings"] = warnings
                payload = {"schema_version": 1, "run": run_data, "items": items}
            store.close()
            run = None
        else:
            if arguments.crop_root is None:
                manifest_path = arguments.manifest.expanduser().resolve(strict=True)
                crop_root = manifest_path.parent
            else:
                crop_root = arguments.crop_root
            from bird_recognition.embed.pipeline import index_manifest

            store = PgVectorStore(arguments.database_url)
            run = index_manifest(
                arguments.manifest,
                crop_root=crop_root,
                species_path=Path(resolved["species_list"]),
                model_directory=Path(resolved["model_dir"]),
                threshold=resolved["threshold"],
                store=store,
                input_view=arguments.input_view,
                minimum_crop_width=arguments.minimum_crop_width,
                minimum_crop_height=arguments.minimum_crop_height,
            )
            payload = {
                "schema_version": 1,
                "run_id": str(run.run_id),
                "status": run.status.value,
                "config_fingerprint": run.config_fingerprint,
                "model_fingerprint": run.model_fingerprint,
                "candidate_set_fingerprint": run.candidate_set_fingerprint,
                "candidate_schema_version": getattr(run, "candidate_schema_version", 1),
                "scoring_fingerprint": run.scoring_fingerprint,
                "prompt_template": getattr(
                    run, "prompt_template", "a photo of {name}."
                ),
                "prompt_version": getattr(run, "prompt_version", "species-photo-v1"),
                "threshold": run.threshold,
                "minimum_crop_width": arguments.minimum_crop_width,
                "minimum_crop_height": arguments.minimum_crop_height,
                "input_view": arguments.input_view,
                "counts": {
                    "selected": run.selected_count,
                    "completed": run.completed_count,
                    "skipped": run.skipped_count,
                    "failed": run.failed_count,
                    "assigned": run.assigned_count,
                    "unknown": run.unknown_count,
                    "pending": run.pending_count,
                },
                "failures": [
                    {
                        "crop_id": item.crop_id,
                        "code": item.code,
                        "reason": item.reason,
                    }
                    for item in run.failures
                ],
                "warnings": [RELATIVE_CONFIDENCE_WARNING]
                + ([SINGLE_CANDIDATE_WARNING] if run.candidate_count == 1 else []),
                "durable_status_confirmed": run.durable_status_confirmed,
                "unconfirmed_crop_ids": list(run.unconfirmed_crop_ids),
            }
            store.close()
        if arguments.json:
            print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))
        elif arguments.command == "evaluate-species":
            print(f"Evaluation report: {payload['output']}")
            report = payload["report"]
            if report.get("schema_version") == 2:
                report = report["run"]
            for lighting, metrics in report["groups"].items():
                precision = metrics.get("precision", metrics.get("species_precision"))
                precision_label = "unavailable" if precision is None else str(precision)
                sample_count = metrics.get(
                    "sample_count", metrics.get("labeled_count", 0)
                )
                print(
                    f"{lighting}: samples={sample_count}, "
                    f"completed={metrics['completed_count']}, "
                    f"precision={precision_label}"
                )
            print(f"Publication ready: {report['publication_ready']}")
        elif arguments.command == "compare-species":
            print(f"Comparison report: {payload['output']}")
            print(f"Paired cases: {payload['report']['paired_case_count']}")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        if run is not None and (
            run.status
            in {RunStatus.PARTIAL_FAILURE, RunStatus.FAILED, RunStatus.INTERRUPTED}
            or not run.durable_status_confirmed
            or run.unconfirmed_crop_ids
        ):
            return 1
        return 0
    except (EmbedValidationError, ValueError, OSError) as error:
        if arguments.json:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "preflight_failure",
                        "code": _preflight_code(error),
                        "message": sanitize_error(str(error)),
                        "run_id": None,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"Preflight error: {sanitize_error(str(error))}", file=sys.stderr)
        return 2
    except EmbedError as error:
        is_preflight = (
            isinstance(error, PreflightError) or arguments.command == "database-init"
        )
        if arguments.json:
            result: dict[str, object] = {
                "schema_version": 1,
                "status": "preflight_failure"
                if is_preflight
                else "operational_failure",
                "message": sanitize_error(str(error)),
            }
            if is_preflight:
                result.update({"code": _preflight_code(error), "run_id": None})
            print(json.dumps(result, sort_keys=True))
        else:
            label = "Preflight error" if is_preflight else "Embedding operation failed"
            print(f"{label}: {sanitize_error(str(error))}", file=sys.stderr)
        return 2 if is_preflight else 1
    except Exception as error:
        sanitized = sanitize_error(str(error))
        if arguments.json:
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "operational_failure",
                        "message": sanitized,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"Embedding operation failed: {sanitized}", file=sys.stderr)
        return 1


def _preflight_code(error: Exception) -> str:
    message = str(error).casefold()
    if "writer_busy" in message or "writer busy" in message:
        return "writer_busy"
    if "vector" in message:
        return "vector_unavailable"
    if "schema" in message:
        return "schema_mismatch"
    if "database" in message or "postgres" in message:
        return "database_unavailable"
    if "threshold" in message:
        return "invalid_threshold"
    if "model" in message or "bioclip" in message:
        return "invalid_model"
    if "species" in message or "candidate" in message:
        return "invalid_species"
    if "manifest" in message:
        return "invalid_manifest"
    return "invalid_selection"


class _NoInferenceDetector:
    def detect(self, image: object) -> list[object]:
        raise RuntimeError("no detector configured")


if __name__ == "__main__":
    raise SystemExit(main())
