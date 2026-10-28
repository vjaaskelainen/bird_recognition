# Agent instructions

## Approval and autonomy

- Read-only inspection may proceed without approval. Ask before actions that change files, the environment, dependencies, or external state, except dependency synchronization permitted below.
- Record approval by action/tool category and scope: file-editing tools, terminal commands, and external actions. Approval for one category or scope does not authorize another; ask again when scope is unclear or expands.
- A task or command example authorizes only its requested scope. Get separate scoped approval before database/service/schema operations or using private model assets, footage, labels, or generated quality reports.
- Agents may run `.\.venv\Scripts\uv.exe sync` when needed for an approved task. Adding, removing, or changing declared dependencies requires scoped approval; use the commands below or edit `pyproject.toml`, then synchronize. Let uv generate `uv.lock`; never edit it manually. Review and report dependency/lockfile changes.

## Running commands (Python environment)

This repo uses a virtual environment at `.venv`, and `uv` is installed inside it.
Always run commands from the repository root, using these exact forms in PowerShell:

| Task                       | Command                                                         |
|----------------------------|-----------------------------------------------------------------|
| Run all unit tests         | `.\.venv\Scripts\python.exe -m pytest`                          |
| Run smoke tests            | `.\.venv\Scripts\python.exe -m pytest tests\smoke`              |
| Run integration tests      | `.\.venv\Scripts\python.exe -m pytest tests\integration`        |
| Run one test file          | `.\.venv\Scripts\python.exe -m pytest tests\unit\ingest\test_detection.py` |
| Run a single test          | `.\.venv\Scripts\python.exe -m pytest tests\unit\ingest\test_detection.py::test_adapter_loads_pinned_mit_api_without_downloads` |
| Run any other Python tool  | `.\.venv\Scripts\uv.exe run <tool> <args>`                      |
| Lint                       | `.\.venv\Scripts\uv.exe run ruff check .`                       |
| Format                     | `.\.venv\Scripts\uv.exe run ruff format .`                      |
| Install/sync dependencies  | `.\.venv\Scripts\uv.exe sync`                                   |
| Add a dependency           | `.\.venv\Scripts\uv.exe add <package>`                          |
| Add a dev dependency       | `.\.venv\Scripts\uv.exe add --dev <package>`                    |

Pytest defaults to `tests/unit`; smoke tests require local assets, and integration
tests require `BIRD_RECOGNITION_TEST_DATABASE_URL` for a disposable local database.

Rules:
- Never run bare `pytest`, `python`, `pip`, `uv` or any other tool name. They are not
  on PATH and will fail. Always use the full `.\.venv\Scripts\...` path shown above.
- Never activate the venv (`Activate.ps1`, `source .venv/bin/activate`). It is not
  needed, and activation does not persist between your commands.
- Never use `pip install` to fix a missing package or command. If a package is
  missing, run `.\.venv\Scripts\uv.exe sync`. If it is genuinely a new dependency,
  use `uv.exe add` as shown above.
- If a command fails with "not recognized" or "not found", the cause is a missing
  `.\.venv\Scripts\` prefix. Fix the command; do not install anything.
- If `.venv` does not exist, stop and ask the developer instead of creating it.

## Repository guidance

- Update relevant documentation when behavior changes; update this file only when repository-wide guidance or routing changes. Avoid duplicating information.
- Do not copy skill contents into this file. Link to [nls-python](.agents/skills/nls-python/SKILL.md) for Python conventions and [nls-ai-housekeeping](.agents/skills/nls-ai-housekeeping/SKILL.md) for instruction and documentation maintenance when relevant.
- For spec-driven feature work, use [specify](.agents/skills/speckit-specify/SKILL.md) → [plan](.agents/skills/speckit-plan/SKILL.md) → [tasks](.agents/skills/speckit-tasks/SKILL.md) → [implement](.agents/skills/speckit-implement/SKILL.md) → [converge](.agents/skills/speckit-converge/SKILL.md). Use [clarify](.agents/skills/speckit-clarify/SKILL.md), [analyze](.agents/skills/speckit-analyze/SKILL.md), or [checklist](.agents/skills/speckit-checklist/SKILL.md) when useful; maintain governance with [constitution](.agents/skills/speckit-constitution/SKILL.md).
- Keep the root [README](README.md) to a system description, high-level component diagram, key defaults/privacy caveats, and links. Put operational commands and configuration in [docs/usage.md](docs/usage.md), and contributor setup/checks in [docs/development.md](docs/development.md). Keep feature implementation, contracts, and acceptance evidence in the relevant `specs/*` artifacts; link to them rather than duplicating their detail.
- Keep ingestion footage, model assets, labels and generated reports outside the repository. Keep feature-specific validation details in the [ingestion](specs/001-ingest-videos/quickstart.md), [embedding](specs/002-embed-species-tags/quickstart.md), [search](specs/003-search-crops/quickstart.md), and [classification](specs/004-improve-species-classification/quickstart.md) quickstarts.
- Keep `.env.example` as the complete environment-variable inventory and `.env` as local ignored configuration; CLI options take precedence over process environment, `.env`, and built-in defaults.
- Refer to [`pyproject.toml`](pyproject.toml) and [`.pre-commit-config.yaml`](.pre-commit-config.yaml) for tooling settings; do not duplicate linter or formatter configuration here.
- A successful pre-commit run executes both configured Ruff hooks (`ruff` and `ruff-format`) and satisfies the Ruff lint/format check; no separate Ruff command or duplicate check record is needed.
- Pin GitHub Actions in workflows to full commit SHAs, with the upstream version in an adjacent comment.
- Keep `.github/workflows/ci.yml` aligned with the documented lint, format, and test checks.
- Run the configured linters as the last step before reporting completion. If fixes are needed, make them and rerun the checks.

## Known pitfalls

- Diagnostic [frame extraction](docs/usage.md#extract-a-single-frame) saves unfiltered full frames, not privacy-screened ingestion crops.
- Species confidence and search similarity are not biological probabilities; visits require explicit owner-reviewed groups, not just shared video membership. See [Usage](docs/usage.md#classification-quality-and-optional-decision-paths).
