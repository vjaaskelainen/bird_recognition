"""Managed ingest/index job endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from bird_recognition.api.errors import APIError, ProblemDetails
from bird_recognition.api.jobs import JobConflictError
from bird_recognition.api.schemas import (
    IndexJobRequest,
    IngestJobRequest,
    Job,
    JobStartResponse,
    PageEnvelope,
)
from bird_recognition.api.security import require_api_key
from bird_recognition.paths import (
    canonicalize_input,
    canonicalize_output,
    validate_destination,
)

router = APIRouter(
    tags=["jobs"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "/ingest",
    response_model=JobStartResponse,
    status_code=202,
    summary="Start an ingestion job",
    responses={
        202: {"description": "Job accepted."},
        401: {"model": ProblemDetails},
        403: {"model": ProblemDetails},
        409: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def start_ingest(
    body: IngestJobRequest, request: Request, response: Response
) -> dict[str, object]:
    """Validate path policy and queue one CLI ingestion process."""
    settings, manager = _job_resources(request)
    try:
        input_dir = canonicalize_input(body.input_dir)
        output_dir = canonicalize_output(body.output_dir)
        _require_allowed(input_dir, settings.allowed_roots)
        _require_allowed(output_dir, settings.allowed_roots, strict=False)
        validate_destination(input_dir, output_dir)
    except Exception:
        raise APIError(
            403, "path_not_permitted", "An input or output path is not permitted."
        ) from None
    command = [
        sys.executable,
        "-m",
        "bird_recognition",
        "ingest",
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
    ]
    for option, value in (
        ("--interval", body.interval),
        ("--animal-threshold", body.animal_threshold),
        ("--person-threshold", body.person_threshold),
        ("--extensions", body.extensions),
    ):
        if value is not None:
            command.extend((option, str(value)))
    record = _start(
        manager,
        "ingest",
        {
            "input_dir": input_dir.name,
            "output_dir": output_dir.name,
            "interval": body.interval,
            "animal_threshold": body.animal_threshold,
            "person_threshold": body.person_threshold,
            "extensions": body.extensions,
        },
        command,
    )
    response.headers["Location"] = f"/v1/jobs/{record['job_id']}"
    return {"job_id": record["job_id"], "status": record["status"]}


@router.post(
    "/index",
    response_model=JobStartResponse,
    status_code=202,
    summary="Start an indexing job",
    responses={
        202: {"description": "Job accepted."},
        401: {"model": ProblemDetails},
        403: {"model": ProblemDetails},
        409: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def start_index(
    body: IndexJobRequest, request: Request, response: Response
) -> dict[str, object]:
    """Validate indexing inputs and queue one CLI indexing process."""
    settings, manager = _job_resources(request)
    try:
        manifest = Path(body.manifest).expanduser().resolve(strict=True)
        if not manifest.is_file():
            raise ValueError
        crop_root = (
            Path(body.crop_root).expanduser().resolve(strict=True)
            if body.crop_root
            else manifest.parent
        )
        if not crop_root.is_dir():
            raise ValueError
        _require_allowed(manifest, settings.allowed_roots)
        _require_allowed(crop_root, settings.allowed_roots)
        species_list = (
            Path(body.species_list).expanduser().resolve(strict=True)
            if body.species_list
            else None
        )
        if species_list is not None:
            _require_allowed(species_list, settings.allowed_roots)
    except Exception:
        raise APIError(
            403, "path_not_permitted", "An indexing path is not permitted."
        ) from None
    command = [
        sys.executable,
        "-m",
        "bird_recognition",
        "index",
        "--manifest",
        str(manifest),
        "--crop-root",
        str(crop_root),
        "--json",
    ]
    if species_list is not None:
        command.extend(("--species-list", str(species_list)))
    if body.threshold is not None:
        command.extend(("--threshold", str(body.threshold)))
    record = _start(
        manager,
        "index",
        {
            "manifest": manifest.name,
            "crop_root": crop_root.name,
            "species_list": species_list.name if species_list else None,
            "threshold": body.threshold,
        },
        command,
    )
    response.headers["Location"] = f"/v1/jobs/{record['job_id']}"
    return {"job_id": record["job_id"], "status": record["status"]}


@router.get(
    "/jobs",
    response_model=PageEnvelope,
    summary="List jobs",
    responses={401: {"model": ProblemDetails}, 503: {"model": ProblemDetails}},
)
def list_jobs(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, object]:
    """Return one page of persisted jobs."""
    _, manager = _job_resources(request)
    try:
        records = manager.list()
    except Exception:
        raise APIError(503, "internal_error", "Job records are unavailable.") from None
    return {
        "items": records[offset : offset + limit],
        "limit": limit,
        "offset": offset,
        "total": len(records),
    }


@router.get(
    "/jobs/{job_id}",
    response_model=Job,
    summary="Get job status",
    responses={
        401: {"model": ProblemDetails},
        404: {"model": ProblemDetails},
        503: {"model": ProblemDetails},
    },
)
def get_job(job_id: UUID, request: Request) -> dict[str, Any]:
    """Return a persisted job state and sanitized report."""
    _, manager = _job_resources(request)
    try:
        record = manager.get(job_id)
    except Exception:
        raise APIError(503, "internal_error", "Job records are unavailable.") from None
    if record is None:
        raise APIError(404, "not_found", "The job was not found.")
    return record


def _job_resources(request: Request) -> tuple[Any, Any]:
    settings = request.app.state.settings
    manager = request.app.state.resources.job_manager
    if settings.jobs_dir is None or not settings.allowed_roots or manager is None:
        raise APIError(
            503, "jobs_not_configured", "Job storage and allowed roots are required."
        )
    return settings, manager


def _require_allowed(
    path: Path, roots: tuple[Path, ...], *, strict: bool = True
) -> None:
    resolved = path.resolve(strict=strict)
    for root in roots:
        try:
            resolved.relative_to(root.resolve(strict=False))
            return
        except OSError, ValueError:
            continue
    raise ValueError("path is outside configured allowed roots")


def _start(
    manager: Any, kind: str, request: dict[str, Any], command: list[str]
) -> dict[str, Any]:
    try:
        return manager.start(kind, request, command)
    except JobConflictError:
        raise APIError(
            409, "job_conflict", "Another ingest or index job is active."
        ) from None
