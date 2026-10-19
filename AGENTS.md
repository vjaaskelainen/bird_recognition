# Agent instructions

## Approval and autonomy

- Read-only inspection may proceed without approval. Ask before any action that changes files, the environment, dependencies, or external state.
- Record approval by action/tool category and scope: file-editing tools, terminal commands, and external actions. Approval for one category or scope does not authorize another; ask again when scope is unclear or expands.
- For dependency changes, edit only `pyproject.toml`. Do not edit `uv.lock` or run dependency synchronization; ask the user to run `uv sync`.

## Running commands (Python environment)

This repo uses a virtual environment at `.venv`, and `uv` is installed inside it.
Always run commands from the repository root, using these exact forms in PowerShell:

| Task                       | Command                                                         |
|----------------------------|-----------------------------------------------------------------|
| Run all tests              | `.\.venv\Scripts\python.exe -m pytest`                          |
| Run one test file          | `.\.venv\Scripts\python.exe -m pytest tests\test_foo.py`        |
| Run a single test          | `.\.venv\Scripts\python.exe -m pytest tests\test_foo.py::test_bar` |
| Run any other Python tool  | `.\.venv\Scripts\uv.exe run <tool> <args>`                      |
| Lint                       | `.\.venv\Scripts\uv.exe run ruff check .`                       |
| Format                     | `.\.venv\Scripts\uv.exe run ruff format .`                      |
| Install/sync dependencies  | `.\.venv\Scripts\uv.exe sync`                                   |
| Add a dependency           | `.\.venv\Scripts\uv.exe add <package>`                          |
| Add a dev dependency       | `.\.venv\Scripts\uv.exe add --dev <package>`                    |

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

- When a change makes documentation updates appropriate, update the relevant documentation and this file. Keep both brief and avoid duplicating information.
- Do not copy skill contents into this file. Link to [nls-python](.agents/skills/nls-python/SKILL.md) for Python conventions and [nls-ai-housekeeping](.agents/skills/nls-ai-housekeeping/SKILL.md) for instruction and documentation maintenance when relevant.
- For spec-driven feature work, use the installed spec-kit skills in `.agents/skills/`: `speckit-specify` → `speckit-plan` → `speckit-tasks` → `speckit-implement` → `speckit-converge`. Use `speckit-clarify` or `speckit-analyze` when useful; establish the project constitution once.
- Keep ingestion footage and generated outputs outside the repository; keep local model/config provisioning and the safe workflow aligned across the [quickstart](specs/001-ingest-videos/quickstart.md), CLI contract, and README.
- Keep the diagnostic `extract-frame` workflow aligned with [README usage](README.md#extract-a-single-frame); it saves unfiltered full frames, not ingestion crops.
- Keep `.env.example` as the complete environment-variable inventory and `.env` as local ignored configuration; CLI options take precedence over process environment, `.env`, and built-in defaults.
- Refer to [`pyproject.toml`](pyproject.toml) and [`.pre-commit-config.yaml`](.pre-commit-config.yaml) for tooling settings; do not duplicate linter or formatter configuration here.
- A successful pre-commit run executes both configured Ruff hooks (`ruff` and `ruff-format`) and satisfies the Ruff lint/format check; no separate Ruff command or duplicate check record is needed.
- Pin GitHub Actions in workflows to full commit SHAs, with the upstream version in an adjacent comment.
- Keep `.github/workflows/ci.yml` aligned with the documented lint, format, and test checks.
- Run the configured linters as the last step before reporting completion. If fixes are needed, make them and rerun the checks.
