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
3.14 runtime and real-model smoke test remain to be validated; see the feature
[quickstart](specs/001-ingest-videos/quickstart.md) for setup and the compatibility gate.

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

```powershell
# Check for lint issues
uv run ruff check .

# Apply automatic lint fixes
uv run ruff check --fix .

# Format Python files
uv run ruff format .

# Check formatting without changing files
uv run ruff format --check .

# Run all configured pre-commit hooks on tracked files
uv run pre-commit run --all-files
```

The installed pre-commit hook runs Ruff lint fixes and formatting on staged
Python files before each commit. Review and stage any changes it makes.

GitHub Actions runs Ruff linting, formatting checks, and pytest on every push
and pull request. The CI test step installs pytest transiently; local development
dependencies remain defined by `uv.lock`.
