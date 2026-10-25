"""Blind review tool for species labels: shows one crop at a time in the browser.

Usage:
    uv run python tools/review_crops.py `
        --csv D:\\bird-eval\\review.csv `
        --species D:\\bird-config\\species.json

Reads and updates the review CSV in place (autosaves after every label).
Stdlib only. Serves on 127.0.0.1 and only the images listed in the CSV.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import mimetypes
import os
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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
NOT_IN_LIST = "not-in-list"
UNKNOWN = "unknown"
LIGHTING = ("day", "night", "unknown")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = {"run_id", "crop_id", "image_path"} - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"CSV is missing columns: {sorted(missing)}")
        return [{field: row.get(field) or "" for field in FIELDS} for row in reader]


def save_rows(path: Path, rows: list[dict[str, str]]) -> None:
    """Write atomically so a crash never leaves a half-written CSV."""
    fd, temp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_name, path)


def derive_truth(animal_type: str) -> tuple[str, str]:
    """Map the reviewer's choice to (expected_species_id, truth_kind)."""
    if animal_type == NOT_IN_LIST:
        return "", "out_of_list"
    if animal_type == UNKNOWN:
        return "", "unidentifiable"
    return animal_type, "species"


def make_handler(csv_path: Path, rows: list[dict[str, str]], species: list[dict]):
    choices = [(item["id"], item["name"]) for item in species]
    choices += [(NOT_IN_LIST, "Not in list"), (UNKNOWN, "Unknown / unidentifiable")]
    valid_choices = {choice_id for choice_id, _ in choices}

    def first_unlabeled() -> int:
        return next(
            (i for i, row in enumerate(rows) if not row["animal_type"]), len(rows) - 1
        )

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:  # keep the console quiet
            pass

        def _index(self, query: dict) -> int:
            try:
                index = int(query.get("i", [first_unlabeled()])[0])
            except ValueError:
                index = 0
            return max(0, min(index, len(rows) - 1))

        def do_GET(self) -> None:
            url = urlparse(self.path)
            query = parse_qs(url.query)
            if url.path == "/image":
                self._send_image(self._index(query))
            elif url.path == "/":
                self._send_page(self._index(query))
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode("utf-8"))
            index = self._index(form)
            animal_type = form.get("animal_type", [""])[0]
            lighting = form.get("lighting", [""])[0]
            if animal_type not in valid_choices or lighting not in LIGHTING:
                self.send_error(400, "invalid choice")
                return
            expected, truth_kind = derive_truth(animal_type)
            rows[index].update(
                animal_type=animal_type,
                lighting=lighting,
                expected_species_id=expected,
                truth_kind=truth_kind,
                notes=form.get("notes", [""])[0].strip(),
            )
            save_rows(csv_path, rows)
            step = -1 if form.get("action", [""])[0] == "back" else 1
            next_index = max(0, min(index + step, len(rows) - 1))
            self.send_response(303)
            self.send_header("Location", f"/?i={next_index}")
            self.end_headers()

        def _send_image(self, index: int) -> None:
            path = Path(rows[index]["image_path"])
            if not path.is_file():
                self.send_error(404, "image not found")
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type", mimetypes.guess_type(path.name)[0] or "image/jpeg"
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_page(self, index: int) -> None:
            row = rows[index]
            done = sum(1 for r in rows if r["animal_type"])
            current = row["animal_type"]
            lighting = row["lighting"] or "unknown"
            options = "".join(
                f'<option value="{html.escape(cid)}"'
                f"{' selected' if cid == current else ''}>{html.escape(name)}</option>"
                for cid, name in choices
            )
            light_options = "".join(
                f'<label><input type="radio" name="lighting" value="{value}"'
                f"{' checked' if value == lighting else ''}> {value}</label> "
                for value in LIGHTING
            )
            page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Crop review {index + 1}/{len(rows)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; }}
img {{ max-width: 90vw; max-height: 60vh; image-rendering: auto;
       border: 1px solid #888; background: #eee; }}
select, input[type=text] {{ font-size: 1.1rem; padding: .3rem; min-width: 22rem; }}
.meta {{ color: #666; font-size: .85rem; word-break: break-all; }}
button {{ font-size: 1.1rem; padding: .4rem 1.2rem; }}
</style></head><body>
<p><b>{index + 1} / {len(rows)}</b> &nbsp; labeled: {done}</p>
<img src="/image?i={index}" alt="crop">
<p class="meta">{html.escape(row["image_path"])}</p>
<form method="post">
<input type="hidden" name="i" value="{index}">
<p><select name="animal_type" autofocus required>
<option value="">-- choose species --</option>{options}</select></p>
<p>Lighting: {light_options}</p>
<p><input type="text" name="notes" placeholder="notes (optional)"
   value="{html.escape(row["notes"])}"></p>
<p><button name="action" value="back">&larr; Save &amp; back</button>
<button id="next" name="action" value="next">Save &amp; next &rarr;</button></p>
</form>
<p><a href="/?i={max(index - 1, 0)}">previous</a> |
<a href="/?i={min(index + 1, len(rows) - 1)}">next</a> (without saving)</p>
<script>
document.querySelector("select").addEventListener("keydown", (event) => {{
  if (event.key === "Enter") {{
    event.preventDefault();
    document.getElementById("next").click();
  }}
}});
</script>
</body></html>"""
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True, help="review CSV to update")
    parser.add_argument("--species", type=Path, required=True, help="species.json")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    rows = load_rows(args.csv)
    if not rows:
        raise SystemExit("CSV has no rows to review")
    species = json.loads(args.species.read_text(encoding="utf-8"))["species"]
    server = ThreadingHTTPServer(
        ("127.0.0.1", args.port), make_handler(args.csv, rows, species)
    )
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Reviewing {len(rows)} crops at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
