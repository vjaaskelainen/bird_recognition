# Agent instructions

## Approval and autonomy

- Read-only inspection may proceed without approval. Ask before any action that changes files, the environment, dependencies, or external state.
- Record approval by action/tool category and scope: file-editing tools, terminal commands, and external actions. Approval for one category or scope does not authorize another; ask again when scope is unclear or expands.
- A task or command example authorizes only its requested scope. Get separate scoped approval before database/service/schema operations or using private model assets, footage, labels, or generated quality reports.
- For dependency changes, edit only `pyproject.toml`. Do not edit `uv.lock` or run dependency synchronization; ask the user to run `uv sync`.

## Running commands (Python environment)

This repo uses a virtual environment at `.venv`, and `uv` is installed inside it.
Always run commands from the repository root, using these exact forms in PowerShell:

| Task                       | Command                                                         |
|----------------------------|-----------------------------------------------------------------|
| Run all unit tests         | `.\.venv\Scripts\python.exe -m pytest`                          |
| Run smoke tests            | `.\.venv\Scripts\python.exe -m pytest tests\smoke`              |
| Run integration tests      | `.\.venv\Scripts\python.exe -m pytest tests\integration`        |
| Run one test file          | `.\.venv\Scripts\python.exe -m pytest tests\test_foo.py`        |
| Run a single test          | `.\.venv\Scripts\python.exe -m pytest tests\test_foo.py::test_bar` |
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

- Prefer pytest fixtures for test setup. When setup is shared by multiple test modules, define it as a fixture in `conftest.py`, placed at the narrowest directory level covering all tests that use it (for example, `tests/unit/conftest.py` for unit tests).
- When a change makes documentation updates appropriate, update the relevant documentation and this file. Keep both brief and avoid duplicating information.
- Do not copy skill contents into this file. Link to [nls-python](.agents/skills/nls-python/SKILL.md) for Python conventions and [nls-ai-housekeeping](.agents/skills/nls-ai-housekeeping/SKILL.md) for instruction and documentation maintenance when relevant.
- For spec-driven feature work, use the installed spec-kit skills in `.agents/skills/`: `speckit-specify` → `speckit-plan` → `speckit-tasks` → `speckit-implement` → `speckit-converge`. Use `speckit-clarify` or `speckit-analyze` when useful; establish the project constitution once.
- Keep ingestion footage, model assets, labels and generated reports outside the repository. For embedding workflow and approval boundaries, use the [embedding quickstart](specs/002-embed-species-tags/quickstart.md) and its [CLI contract](specs/002-embed-species-tags/contracts/cli.md); keep ingestion/extract-frame instructions in the [README](README.md).
- Keep the diagnostic `extract-frame` workflow aligned with [README usage](README.md#extract-a-single-frame); it saves unfiltered full frames, not ingestion crops.
- Keep `.env.example` as the complete environment-variable inventory and `.env` as local ignored configuration; CLI options take precedence over process environment, `.env`, and built-in defaults.
- Refer to [`pyproject.toml`](pyproject.toml) and [`.pre-commit-config.yaml`](.pre-commit-config.yaml) for tooling settings; do not duplicate linter or formatter configuration here.
- A successful pre-commit run executes both configured Ruff hooks (`ruff` and `ruff-format`) and satisfies the Ruff lint/format check; no separate Ruff command or duplicate check record is needed.
- Pin GitHub Actions in workflows to full commit SHAs, with the upstream version in an adjacent comment.
- Keep `.github/workflows/ci.yml` aligned with the documented lint, format, and test checks.
- Run the configured linters as the last step before reporting completion. If fixes are needed, make them and rerun the checks.
