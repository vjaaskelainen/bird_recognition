# Bird Recognition

A trail-camera bird-footage search and question-answering project. The project
uses Python 3.14, [uv](https://docs.astral.sh/uv/) for dependency and environment
management, [Ruff](https://docs.astral.sh/ruff/) for linting and formatting, and
[pre-commit](https://pre-commit.com/) to run checks before commits.

## Developer setup

Install Python 3.14 and uv, then from the repository root run:

```powershell
uv sync --locked
uv run pre-commit install
```

`uv sync` creates or updates the project environment from `uv.lock`. Run project
tools through `uv run` so they use the locked development dependencies.

## AI-assisted development

This repository uses the `nlsfi/agent-instructions-template` for coding-agent
guidance. Its skills are in [`.agents/skills/`](.agents/skills/): `nls-python`
covers Python conventions and testing, while `nls-ai-housekeeping` describes
the process for maintaining agent instructions and repository documentation.
The template source and configuration are recorded in
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
