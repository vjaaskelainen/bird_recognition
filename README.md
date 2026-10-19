# Bird Recognition

A trail-camera bird-footage search and question-answering project. The project
uses Python 3.14, [uv](https://docs.astral.sh/uv/) for dependency and environment
management, [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and
[pre-commit](https://pre-commit.com/) to run checks before commits.

## Developer setup

Install Python 3.14 and uv, then from the repository root run:

```powershell
uv sync
uv run pre-commit install
```

`uv sync` synchronizes the project environment and lockfile from `pyproject.toml`.
Run project tools through `uv run` so they use the project environment.
On first setup, create `.env` from `.env.example` if it does not already exist;
keep local values in `.env` and never commit it.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

## Local video ingestion

The `bird-recognition ingest` command scans local video directories recursively
and writes animal crops with a SQLite provenance manifest. The selected detector
is the MIT-licensed MegaDetector V6 variant `MDV6-mit-yolov9-c`. Provision its
`.ckpt` weights and `config_v9c.yaml` locally, outside Git. Ingestion requires
both local files and never downloads model weights or configuration. The Python
3.14 Windows runtime, real-model smoke test, and full pytest suite were validated
on 2026-10-18; locked package versions and remaining model-quality validation are
recorded in the [V6 upgrade plan](specs/001-ingest-videos/megadetector-v6-upgrade-plan.md).
See the feature [quickstart](specs/001-ingest-videos/quickstart.md) for setup.

Keep the input footage and output directory outside the Git repository and make
them disjoint. Supported extensions are `.mp4`, `.mov`, `.m4v`, `.mkv`, `.avi`,
`.mpeg`, and `.mpg`. Sampling defaults to one second; animal and person confidence
thresholds default to `0.2` and qualify inclusively. For example:

```powershell
uv run bird-recognition ingest `
  --input "D:\trail-camera\videos" `
  --output "D:\trail-camera\ingested" `
  --model "D:\models\MDV6-mit-yolov9-c.ckpt" `
  --model-config "D:\models\config_v9c.yaml"
```

The output contains `manifest.sqlite3` and retained crops. The summary separates
processed, skipped, and failed sources from mutually exclusive frame outcomes
and crop count. Exit codes are `0` for complete/no-input, `1` for processing
failures, and `2` for preflight errors. Capture time is unknown when reliable
camera metadata is unavailable; filesystem timestamps are never substituted.
Person detection is not a guarantee of anonymity: review crops manually before
sharing them. See the [feature quickstart](specs/001-ingest-videos/quickstart.md)
for fixture validation and batch recovery notes.

Optional CLI defaults, including model paths, can be set in `.env`; explicit
CLI options override process environment values, which override `.env` values.
See [`.env.example`](.env.example) for the complete variable list.

## Extract a single frame

Extract a full-resolution PNG without loading MegaDetector:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition extract-frame `
  --input "D:\trail-camera\videos\camera.mp4" `
  --timestamp 2.5 `
  --output "D:\trail-camera\frames"
```

The timestamp must be finite and non-negative, in seconds relative to the first
decoded frame. The command saves the first frame at or after that time as
`camera.mp4_frame_2.5s.png` and prints its path. It creates the output directory
when a matching frame is found and refuses to overwrite existing images.
Requests beyond the last frame fail rather than returning an earlier frame.
Exit codes are `0` for success, `1` for decoding/timing failures, and `2` for
invalid inputs or destinations. The reusable `extract_frame` helper in
`bird_recognition.cli` accepts the same three inputs and returns the saved path.

Keep input footage and output outside Git, with the output separate from the
input video's directory tree. Unlike ingestion, extraction performs **no person
filtering**: full frames may contain people or other sensitive content. Keep
them private and review them before sharing.

## Local database

Start the local Postgres + pgvector service with Podman Compose:

```powershell
podman compose up -d
```

The default connection is `postgresql://bird_recognition:bird_recognition@localhost:5432/bird_recognition`.
Compose reads the `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_PORT` values from `.env` (with the same defaults shown in
`.env.example`). Enable the vector extension in the database before using it
with `CREATE EXTENSION IF NOT EXISTS vector;`.

## AI-assisted development

Repository-wide coding-agent guidance is in [`AGENTS.md`](AGENTS.md). The
repository uses the `nlsfi/agent-instructions-template` and spec-kit with the
Copilot integration. Skills for Python conventions, instruction maintenance,
and the spec-kit feature workflow are in [`.agents/skills/`](.agents/skills/).
For feature work, the workflow is specify → plan → tasks → implement → converge;
review each artifact before moving to the next step. The agent-instructions
template source and configuration are recorded in
[`.copier-answers.agent-instructions.yml`](.copier-answers.agent-instructions.yml).

## Development checks

Run tests from the repository root with the project virtual environment active.
The project requires Python 3.14 or newer, and pytest is included in the dev
dependency group. Assuming the existing `.venv` has up-to-date dependencies,
activate it in your shell first:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```cmd
:: Windows Command Prompt
.venv\Scripts\activate.bat
```

```sh
# macOS / Linux (POSIX shells)
source .venv/bin/activate
```

If `.venv` does not exist yet, create it and install the project dependencies
from the repository root with `uv sync` before activating it.

If PowerShell blocks the activation script, allow it for the current session
only, then activate the environment again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Confirm the selected interpreter belongs to `.venv`, then run the complete test
suite:

```text
python -c "import pathlib, sys; assert sys.version_info >= (3, 14); assert pathlib.Path(sys.prefix).resolve() == pathlib.Path('.venv').resolve(), sys.executable; print(sys.executable)"
python -m pytest
```

The first command must print the interpreter path inside this repository's
`.venv`; it fails if Python is older than 3.14 or a different environment is active.

Tests use local fixtures and temporary directories; they do not require `.env`,
PostgreSQL, Ollama, network access, or MegaDetector weights. The real-model
smoke test is skipped unless all three `BIRD_RECOGNITION_SMOKE_MODEL`,
`BIRD_RECOGNITION_SMOKE_CONFIG`, and `BIRD_RECOGNITION_SMOKE_IMAGE` values are
set (for example in `.env`); the paths must point to locally available files.
With those configured, the smoke test runs as part of the full suite. To run a
single test file, pass its path, such as `python -m pytest
tests/ingest/test_detection.py`.

```powershell
# Check for lint issues
ruff check .

# Apply automatic lint fixes
ruff check --fix .

# Format Python files
ruff format .

# Check formatting without changing files
ruff format --check .

# Run all configured pre-commit hooks on tracked files
pre-commit run --all-files
```

The installed pre-commit hook runs Ruff lint fixes and formatting on staged
Python files before each commit. Review and stage any changes it makes.

GitHub Actions runs Ruff linting, formatting checks, and pytest on every push
and pull request. Run these checks with the project virtual environment active
for a local CI-equivalent validation.
