"""Create a blind review CSV from `inspect --json` output, or convert it to labels JSON.

uv run python tools/review_csv.py create --inspect run.json `
    --crop-root D:\\trail-camera\\ingested --output review.csv `
    [--limit 100] [--seed 1]
uv run python tools/review_csv.py to-labels --csv review.csv --output labels.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
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
]


def create(args: argparse.Namespace) -> None:
    document = json.loads(args.inspect.read_text(encoding="utf-8"))
    run_id = document["run"]["run_id"]
    rows = []
    for item in document["items"]:
        provenance = item.get("provenance")
        if not provenance:  # failed or pending items have no crop to review
            continue
        relative = PureWindowsPath(provenance["crop_original_image_path"])
        rows.append(
            {
                "run_id": run_id,
                "crop_id": item["crop_id"],
                # Prefilled from the run; correct it in the review if it is wrong.
                "lighting": item.get("lighting") or "unknown",
                "animal_type": "",
                "image_path": str(args.crop_root.joinpath(*relative.parts)),
                "expected_species_id": "",
                "truth_kind": "",
                "notes": "",
            }
        )
    # Shuffle so consecutive near-duplicate frames are not reviewed back to back.
    random.Random(args.seed).shuffle(rows)
    if args.limit:
        rows = rows[: args.limit]
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
    run_ids = {row["run_id"] for row in rows}
    if len(run_ids) != 1:
        raise SystemExit(
            f"expected labels for exactly one run, found {sorted(run_ids)}"
        )
    labels = {
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
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    args.output.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    print(f"wrote {len(labels['examples'])} labeled examples to {args.output}")


def main() -> None:
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
    make.add_argument("--limit", type=int, default=0)
    make.add_argument("--seed", type=int, default=1)
    make.set_defaults(func=create)
    convert = commands.add_parser("to-labels")
    convert.add_argument("--csv", type=Path, required=True)
    convert.add_argument("--output", type=Path, required=True)
    convert.set_defaults(func=to_labels)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
