"""Create a blind review CSV from `inspect --json` output, or convert it to labels JSON.

uv run python tools/review_csv.py create --inspect run.json `
    --crop-root D:\\trail-camera\\ingested --output review.csv `
    [--limit 100] [--seed 1]
uv run python tools/review_csv.py to-labels --csv review.csv --output labels.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import sys
from datetime import date, datetime
from pathlib import Path, PureWindowsPath

FIELDS = [
    "run_id",
    "crop_id",
    "lighting",
    "animal_type",
    "image_path",
    "expected_species_id",
    "truth_kind",
    "notes",
    "case_id",
    "source_id",
    "source_content_sha256",
    "frame_number",
    "detection_id",
    "detection_box_normalized",
    "recording_day",
    "expected_category",
]

_LIGHTING_GROUPS = ("day", "night", "unknown")
_SHA256_LENGTH = 64
_TRUTH_KIND_ALIASES = {
    "species": "species",
    "out_of_list": "out_of_list",
    "not-in-list": "out_of_list",
    "unidentifiable": "unidentifiable",
    "unknown": "unidentifiable",
    "unusable": "unusable",
}


def create(args: argparse.Namespace) -> None:
    document = json.loads(args.inspect.read_text(encoding="utf-8"))
    run_id = document["run"]["run_id"]
    selected_sources = {
        value.strip() for value in (getattr(args, "source_id", None) or [])
    }
    if "" in selected_sources:
        raise SystemExit("--source-id must not be blank")
    rows: list[dict[str, str]] = []
    for item in document["items"]:
        provenance = item.get("provenance")
        if not provenance:  # failed or pending items have no crop to review
            continue
        source_id = _required_text(provenance, "source_id")
        if selected_sources and source_id not in selected_sources:
            continue
        case_id = _case_id(provenance)
        lighting = item.get("lighting") or provenance.get("lighting") or "unknown"
        if lighting not in _LIGHTING_GROUPS:
            raise SystemExit(f"invalid lighting value for crop {item['crop_id']}")
        relative = PureWindowsPath(provenance["crop_original_image_path"])
        capture_time = provenance.get("capture_time") or provenance.get(
            "source_capture_start"
        )
        rows.append(
            {
                "run_id": run_id,
                "crop_id": item["crop_id"],
                "lighting": lighting,
                "animal_type": "",
                "image_path": str(args.crop_root.joinpath(*relative.parts)),
                "expected_species_id": "",
                "truth_kind": "",
                "notes": "",
                "case_id": case_id,
                "source_id": source_id,
                "source_content_sha256": _required_text(
                    provenance, "source_content_sha256"
                ),
                "frame_number": str(
                    _required_nonnegative_integer(provenance, "frame_number")
                ),
                "detection_id": _required_text(provenance, "detection_id"),
                "detection_box_normalized": json.dumps(
                    _normalized_detection_box(provenance), separators=(",", ":")
                ),
                "recording_day": _recording_day(capture_time),
                "expected_category": "",
            }
        )
    _reject_duplicate_values(rows, "case_id", "ambiguous case_id")

    limit = getattr(args, "limit", None)
    per_lighting = getattr(args, "per_lighting", None)
    if limit is not None and per_lighting is not None:
        raise SystemExit("--limit and --per-lighting are mutually exclusive")
    if limit is not None and limit < 0:
        raise SystemExit("--limit must be non-negative")
    if per_lighting is not None and not 1 <= per_lighting <= 500:
        raise SystemExit("--per-lighting must be between 1 and 500")

    rows.sort(key=lambda row: (row["lighting"], row["case_id"], row["crop_id"]))
    if per_lighting is not None:
        sampled: list[dict[str, str]] = []
        for lighting in _LIGHTING_GROUPS:
            group = [row for row in rows if row["lighting"] == lighting]
            random.Random(f"{args.seed}:{lighting}").shuffle(group)
            sampled.extend(group[:per_lighting])
            if len(group) < per_lighting:
                print(
                    f"shortfall for {lighting}: requested {per_lighting}, "
                    f"found {len(group)}",
                    file=sys.stderr,
                )
        rows = sampled
    else:
        random.Random(args.seed).shuffle(rows)
        if limit:
            rows = rows[:limit]
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.output}")


def to_labels(args: argparse.Namespace) -> None:
    with args.csv.open(newline="", encoding="utf-8-sig") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("truth_kind")]
    label_role = getattr(args, "label_role", None)
    split_mode = getattr(args, "split_mode", None)
    if (label_role is None) != (split_mode is None):
        raise SystemExit("--label-role and --split-mode must be provided together")
    if label_role is not None:
        labels = _shared_labels(rows, label_role, split_mode or "")
    else:
        labels = _legacy_labels(rows)
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    args.output.write_text(
        json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {len(labels['examples'])} labeled examples to {args.output}")


def _legacy_labels(rows: list[dict[str, str]]) -> dict[str, object]:
    run_ids = {row["run_id"] for row in rows}
    if len(run_ids) != 1:
        raise SystemExit(
            f"expected labels for exactly one run, found {sorted(run_ids)}"
        )
    return {
        "schema_version": 1,
        "run_id": run_ids.pop(),
        "examples": [
            {
                "crop_id": row["crop_id"],
                "expected_species_id": row["expected_species_id"] or None,
                "truth_kind": row["truth_kind"],
                "notes": row.get("notes", ""),
            }
            for row in rows
        ],
    }


def _shared_labels(
    rows: list[dict[str, str]], label_role: str, split_mode: str
) -> dict[str, object]:
    if label_role not in {"tuning", "held_out_evaluation"}:
        raise SystemExit("--label-role must be tuning or held_out_evaluation")
    if split_mode not in {"source_video", "recording_day"}:
        raise SystemExit("--split-mode must be source_video or recording_day")
    if not rows:
        raise SystemExit("shared labels require at least one labeled row")

    _reject_duplicate_values(rows, "case_id", "duplicate or missing case_id")
    _reject_duplicate_values(
        rows, "crop_id", "ambiguous reviewed crop maps to multiple cases"
    )
    split_keys: set[str] = set()
    examples: list[dict[str, object]] = []
    for row in rows:
        case_id = _row_required_text(row, "case_id")
        crop_id = _row_required_text(row, "crop_id")
        if split_mode == "source_video":
            split_key = _row_required_text(row, "source_id")
        else:
            split_key = (row.get("recording_day") or "").strip()
            if not _is_iso_date(split_key):
                raise SystemExit(
                    "recording day is unknown or invalid for a labeled row"
                )
        split_keys.add(split_key)
        truth_kind = _TRUTH_KIND_ALIASES.get(row.get("truth_kind", ""))
        if truth_kind is None:
            raise SystemExit(f"unsupported truth_kind: {row.get('truth_kind', '')}")
        taxon_id = (row.get("expected_species_id") or "").strip() or None
        if truth_kind == "species" and taxon_id is None:
            raise SystemExit("species labels require expected_species_id")
        if truth_kind in {"unidentifiable", "unusable"} and taxon_id is not None:
            raise SystemExit(
                f"{truth_kind} labels must not include expected_species_id"
            )
        expected_category = (row.get("expected_category") or "").strip() or None
        if expected_category not in {None, "bird", "mammal"}:
            raise SystemExit("expected_category must be bird, mammal, or blank")
        example: dict[str, object] = {
            "case_id": case_id,
            "reviewed_crop_id": crop_id,
            "truth_kind": truth_kind,
            "expected_taxon_id": taxon_id,
            "expected_category": expected_category,
            "notes": row.get("notes", ""),
        }
        examples.append(example)

    sorted_keys = sorted(split_keys)
    canonical_keys = json.dumps(
        sorted_keys, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return {
        "schema_version": 2,
        "label_role": label_role,
        "split_mode": split_mode,
        "source_split_keys": sorted_keys,
        "source_split_sha256": hashlib.sha256(
            canonical_keys.encode("utf-8")
        ).hexdigest(),
        "examples": examples,
    }


def _case_id(provenance: dict[str, object]) -> str:
    content_digest = _required_text(provenance, "source_content_sha256")
    if len(content_digest) != _SHA256_LENGTH or any(
        character not in "0123456789abcdef" for character in content_digest
    ):
        raise SystemExit("inspection provenance has invalid source_content_sha256")
    identity = {
        "source_content_sha256": content_digest,
        "frame_number": _required_nonnegative_integer(provenance, "frame_number"),
        "detection_id": _required_text(provenance, "detection_id"),
        "detection_box_normalized": _normalized_detection_box(provenance),
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalized_detection_box(provenance: dict[str, object]) -> list[float]:
    value = provenance.get("detection_box_normalized")
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise SystemExit("detection box provenance is invalid")
    try:
        box = [float(coordinate) for coordinate in value]
    except TypeError, ValueError:
        raise SystemExit("detection box provenance is invalid") from None
    if (
        any(
            not math.isfinite(coordinate) or not 0 <= coordinate <= 1
            for coordinate in box
        )
        or box[2] <= box[0]
        or box[3] <= box[1]
    ):
        raise SystemExit("detection box provenance is invalid")
    return box


def _recording_day(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        try:
            return (
                datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
            )
        except ValueError:
            return ""


def _is_iso_date(value: str) -> bool:
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _required_text(document: dict[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"inspection provenance is missing {key}")
    return value.strip()


def _row_required_text(row: dict[str, str], key: str) -> str:
    value = (row.get(key) or "").strip()
    if not value:
        raise SystemExit(f"review CSV is missing {key}")
    return value


def _required_nonnegative_integer(document: dict[str, object], key: str) -> int:
    value = document.get(key)
    if type(value) is not int or value < 0:
        raise SystemExit(f"inspection provenance has invalid {key}")
    return value


def _reject_duplicate_values(
    rows: list[dict[str, str]], key: str, message: str
) -> None:
    values = [row.get(key, "").strip() for row in rows]
    if any(not value for value in values) or len(set(values)) != len(values):
        raise SystemExit(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("create")
    make.add_argument("--inspect", type=Path, required=True)
    make.add_argument(
        "--crop-root",
        type=Path,
        required=True,
        help="ingest output directory (the folder that contains the manifest)",
    )
    make.add_argument("--output", type=Path, required=True)
    sampling = make.add_mutually_exclusive_group()
    sampling.add_argument("--limit", type=int)
    sampling.add_argument("--per-lighting", type=int)
    make.add_argument("--seed", type=int, default=1)
    make.add_argument("--source-id", action="append", default=[])
    make.set_defaults(func=create)
    convert = commands.add_parser("to-labels")
    convert.add_argument("--csv", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    convert.add_argument("--label-role", choices=("tuning", "held_out_evaluation"))
    convert.add_argument("--split-mode", choices=("source_video", "recording_day"))
    convert.set_defaults(func=to_labels)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
