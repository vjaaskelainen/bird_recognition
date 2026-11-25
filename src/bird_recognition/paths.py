"""Canonical path validation shared by the CLI and HTTP service."""

from __future__ import annotations

import subprocess
from pathlib import Path

from bird_recognition.ingest.models import ValidationError


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
