# Agent instructions

## Approval and autonomy

- Read-only inspection may proceed without approval. Ask before any action that changes files, the environment, dependencies, or external state.
- Record approval by action/tool category and scope: file-editing tools, terminal commands, and external actions. Approval for one category or scope does not authorize another; ask again when scope is unclear or expands.
- For dependency changes, edit only `pyproject.toml`. Do not edit `uv.lock` or run dependency synchronization; ask the user to run `uv sync`.

## Repository guidance

- When a change makes documentation updates appropriate, update the relevant documentation and this file. Keep both brief and avoid duplicating information.
- Do not copy skill contents into this file. Link to [nls-python](.agents/skills/nls-python/SKILL.md) for Python conventions and [nls-ai-housekeeping](.agents/skills/nls-ai-housekeeping/SKILL.md) for instruction and documentation maintenance when relevant.
- For spec-driven feature work, use the installed spec-kit skills in `.agents/skills/`: `speckit-specify` → `speckit-plan` → `speckit-tasks` → `speckit-implement` → `speckit-converge`. Use `speckit-clarify` or `speckit-analyze` when useful; establish the project constitution once.
- Refer to [`pyproject.toml`](pyproject.toml) and [`.pre-commit-config.yaml`](.pre-commit-config.yaml) for tooling settings; do not duplicate linter or formatter configuration here.
- Pin GitHub Actions in workflows to full commit SHAs, with the upstream version in an adjacent comment.
- Keep `.github/workflows/ci.yml` aligned with the documented lint, format, and test checks.
- Activate the project virtual environment before running `uv` commands; run the configured linters as the last step before reporting completion. If fixes are needed, make them and rerun the checks.
