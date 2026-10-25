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
`.ckpt` weights and `config_v9s.yaml` locally, outside Git. Ingestion requires
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
  --model-config "D:\models\config_v9s.yaml"
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

Start the local Postgres + pgvector service and wait for database migrations to
finish with Podman Compose:

```powershell
podman compose up -d --build --wait
```

Compose waits for PostgreSQL, then a lightweight migration service applies any
pending numbered SQL migrations and stays healthy only while the database is at
the packaged migration head. Existing migrations are skipped, including on
stop/start; future migrations are applied on the next `up`. The persistent volume
preserves the database across `podman compose down` and restarts. Do not use
`podman compose down -v` unless intentionally deleting the database.

Compose reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_PORT` from `.env` (with defaults in `.env.example`). The migration
service also creates the pgvector extension when needed. Set the private
`BIRD_RECOGNITION_DATABASE_URL` in `.env` to connect the application to this local
database; it must match your local Compose settings. The application does not
derive a URL from `POSTGRES_*` or supply a built-in credential default. For
explicit/manual setup, run `bird-recognition database-init` after the database is
ready; indexing never installs extensions or migrates the schema.

## Crop embeddings and species tags

Indexing is an optional local workflow layered on ingestion. It reads the existing
SQLite manifest and retained crops without changing them; ingestion and
`extract-frame` remain usable without BioCLIP assets or the embedding database.
Keep videos, manifests, crops, model assets, candidate lists, evaluation labels,
and reports outside Git.

Dependencies are declared in `pyproject.toml` and provisioned with the project
environment. Obtain the original pretrained `imageomics/bioclip` ViT-B-16 bundle
separately from a trusted immutable upstream revision. The local model directory
must contain `open_clip_config.json`, `open_clip_pytorch_model.bin`, and a valid
`asset-manifest.json` with the revision and file SHA-256 values. The adapter uses
the tokenizer vocabulary packaged with OpenCLIP and never downloads weights or
falls back to random weights. Model paths and assets are private and must remain
outside the repository.

Start the local PostgreSQL/pgvector service as described above, then initialize
its schema explicitly:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition database-init
```

The species list is required; there is no implicit vocabulary. Copy
[`species.json.example`](species.json.example) to a private location and edit it
for the intended candidates. It is an illustrative format example, not a regional
checklist. IDs must be stable and names unique. Configure
`BIRD_RECOGNITION_BIOCLIP_MODEL_DIR`, `BIRD_RECOGNITION_SPECIES_LIST`, and the
required private `BIRD_RECOGNITION_DATABASE_URL` in ignored `.env`, or supply the
supported command options. `BIRD_RECOGNITION_SPECIES_THRESHOLD` defaults to `0.5`;
explicit CLI options override process environment, which overrides `.env`.

Use one explicit manifest and inspect the resulting run by its returned ID:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition index --manifest "D:\trail-camera\ingested\manifest.sqlite3" --json
.\.venv\Scripts\uv.exe run bird-recognition inspect --run-id "<run-id-from-index>" --json
```

Repeat the index command to retry/resume and skip compatible completed work. To
retag with a new threshold or candidate file, index the same manifest with the new
selection; the command creates a versioned decision while reusing compatible
stored image vectors:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition index --manifest "D:\trail-camera\ingested\manifest.sqlite3" --threshold 0.7 --json
.\.venv\Scripts\uv.exe run bird-recognition index --manifest "D:\trail-camera\ingested\manifest.sqlite3" --species-list "D:\bird-config\alternate-species.json" --json
```

Inspecting an explicit run reads persisted data
and does not require current model files, species files, crops, or inference.
Species confidence is candidate-relative, not a calibrated probability of
biological correctness; candidate-set scores are not comparable, and an
out-of-list animal may score highly. Treat tags as suggestions and review
measured errors before relying on them.

Evaluate reviewed labels against one persisted run. Keep both labels and report in
private external paths; evaluation reads stored decisions and does not load model
assets or images:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition evaluate-species --run-id "<run-id>" --labels "D:\bird-eval\labels.json" --output "D:\bird-eval\reports\species-quality.json" --json
```

The day/night sample-count gate is not an accuracy guarantee. Review the measured
precision, coverage, and failure examples; see the [crop-embedding quickstart](specs/002-embed-species-tags/quickstart.md)
for model provisioning, retry/retag scenarios, validation steps, and the current
measured evaluation evidence. Do not publish claims beyond the reviewed results.

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
smoke test requires all three `BIRD_RECOGNITION_SMOKE_MODEL`,
`BIRD_RECOGNITION_SMOKE_CONFIG`, and `BIRD_RECOGNITION_SMOKE_IMAGE` values are
set (for example in `.env`); the paths must point to locally available files.
The default `python -m pytest` runs only `tests/unit`. Run smoke and integration
tests separately with `python -m pytest tests/smoke` and
`python -m pytest tests/integration`. Smoke tests need the listed local model/image
settings; integration tests need `BIRD_RECOGNITION_TEST_DATABASE_URL` set to an
approved disposable local database. To run one unit test file, pass its path, such
as `python -m pytest tests/unit/ingest/test_detection.py`.

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
