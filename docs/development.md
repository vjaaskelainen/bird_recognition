# Developer setup and checks

This document contains contributor setup and validation workflows. The
[README](../README.md) is the project overview; operational application workflows
are in [Usage](usage.md).

## Environment setup

Use Python 3.14+ and the repository's existing `.venv`, which must contain
[uv](https://docs.astral.sh/uv/). If the environment is absent, ask the developer
to provision it before continuing; the commands below cannot bootstrap it.
From the repository root, synchronize and install the pre-commit hook:

```powershell
.\.venv\Scripts\uv.exe sync
.\.venv\Scripts\uv.exe run pre-commit install
```

Synchronization updates the environment and generates `uv.lock` from
`pyproject.toml`. Agents may synchronize for an approved task; changes to declared
dependencies require scoped approval under [`AGENTS.md`](../AGENTS.md). Do not
edit the generated lockfile manually.
On first setup, create `.env` from [`.env.example`](../.env.example) if it does not
already exist; keep local values in `.env` and never commit it:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

The project requires Python 3.14 or newer; pytest is included in the development
dependency group. Run commands from the repository root using the project's
`.venv` executables. Do not activate the environment or use bare tool commands.
Verify the interpreter version and that it belongs to this repository's `.venv`:

```powershell
.\.venv\Scripts\python.exe -c "import pathlib, sys; assert sys.version_info >= (3, 14); assert pathlib.Path(sys.prefix).resolve() == pathlib.Path('.venv').resolve(), sys.executable; print(sys.executable)"
```

## Tests

The default test command runs only `tests/unit`:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Tests use local fixtures and temporary directories; they do not require `.env`,
PostgreSQL, Ollama, network access, or MegaDetector weights. Run smoke and
integration tests separately:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\smoke
.\.venv\Scripts\python.exe -m pytest tests\integration
```

The real MegaDetector smoke test requires all three
`BIRD_RECOGNITION_SMOKE_MODEL`, `BIRD_RECOGNITION_SMOKE_CONFIG`, and
`BIRD_RECOGNITION_SMOKE_IMAGE` values (for example in `.env`); all paths must
refer to locally available files. The separate BioCLIP smoke test requires
`BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR` and
`BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE`; it verifies local inference, not biological
quality. See [`.env.example`](../.env.example) for the full variable inventory.
Integration tests require
`BIRD_RECOGNITION_TEST_DATABASE_URL` to point to an approved disposable local
database. Smoke and integration tests are opt-in and are not part of the default
unit-test discovery.

Run one test file or a single test by appending the corresponding path/node ID:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\ingest\test_detection.py
.\.venv\Scripts\python.exe -m pytest tests\unit\ingest\test_detection.py::test_adapter_loads_pinned_mit_api_without_downloads
```

See the feature [ingestion quickstart](../specs/001-ingest-videos/quickstart.md)
and [embedding quickstart](../specs/002-embed-species-tags/quickstart.md) for
feature-specific fixture expectations, integration prerequisites, and acceptance
evidence. The [classification quickstart](../specs/004-improve-species-classification/quickstart.md)
covers shared-label review, comparisons, references, and visit/benchmark checks.

## Lint, format, and pre-commit

Run Ruff and the configured pre-commit hooks through the project environment:

```powershell
.\.venv\Scripts\uv.exe run ruff check .
.\.venv\Scripts\uv.exe run ruff check --fix .
.\.venv\Scripts\uv.exe run ruff format .
.\.venv\Scripts\uv.exe run ruff format --check .
.\.venv\Scripts\uv.exe run pre-commit run --all-files
```

The installed pre-commit hook runs Ruff lint fixes and formatting on staged
Python files before each commit. Review and stage any changes it makes.

GitHub Actions runs Ruff linting, formatting checks, and pytest on every push and
pull request. Use the commands above for local CI-equivalent validation.

## AI-assisted development

Repository-wide coding-agent guidance is in [`AGENTS.md`](../AGENTS.md). The
repository uses the `nlsfi/agent-instructions-template` and spec-kit with the
Copilot integration. Skills for Python conventions, instruction maintenance, and
the spec-kit feature workflow are in [nls-python](../.agents/skills/nls-python/SKILL.md),
[nls-ai-housekeeping](../.agents/skills/nls-ai-housekeeping/SKILL.md), and
[the spec-kit skills](../.agents/skills/speckit-specify/SKILL.md).
For feature work, the workflow is specify → plan → tasks → implement → converge;
review each artifact before moving to the next step. The agent-instructions
template source and configuration are recorded in
[`.copier-answers.agent-instructions.yml`](../.copier-answers.agent-instructions.yml).



