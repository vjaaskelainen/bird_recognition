---

description: "Task list for HTTP Service for Bird Recognition"
---

# Tasks: HTTP Service for Bird Recognition

**Input**: Design documents from `/specs/006-fastapi-service/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: Included (plan.md: pytest with `TestClient` and fakes; constitution principle IV requires offline, testable core). No network or LLM key in tests.

**Organization**: Grouped by user story. Story order follows spec priorities: US1 (P1) → US2 (P1) → US3 (P2) → US4 (P3).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4, maps to spec.md user stories

## Phase 1: Setup

**Purpose**: Dependencies, package skeleton, entry point

- [x] T001 Confirm runtime/dev dependencies were already declared; run `.\.venv\Scripts\uv.exe sync --locked` (no dependency or lockfile diff required)
- [x] T002 Create package skeleton `src/bird_recognition/api/__init__.py`, `src/bird_recognition/api/routers/__init__.py` and `tests/unit/api/__init__.py` (match existing test package conventions)
- [x] T003 Register console script `bird-recognition-api = bird_recognition.api.server:main` in `pyproject.toml`
- [x] T004 [P] Add new env vars `BIRD_RECOGNITION_API_HOST`, `BIRD_RECOGNITION_API_PORT`, `BIRD_RECOGNITION_API_KEY`, `BIRD_RECOGNITION_API_JOBS_DIR`, `BIRD_RECOGNITION_API_ALLOWED_ROOTS` (with comments, no real secrets) to `.env.example`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared extraction (FR-003), settings, security, errors, app factory. Blocks all stories.

- [x] T005 Extract `_search_payload`, `_ask_payload`, `_search_failure_code`, `_preflight_code`, `_sanitize_ask_error` and the transmission-notice text helper from `src/bird_recognition/cli.py` into new `src/bird_recognition/payloads.py`; re-import in `cli.py` with behaviour unchanged
- [x] T006 [P] Extract `canonicalize_input`, `canonicalize_output`, `validate_destination` from `src/bird_recognition/cli.py` into new `src/bird_recognition/paths.py`; re-export/import in `cli.py`
- [x] T007 Run existing CLI tests (`.\.venv\Scripts\python.exe -m pytest tests\unit`) to confirm the extraction in T005/T006 changed no behaviour
- [x] T008 [P] Implement settings (host default `127.0.0.1`, port, API key, jobs dir, allowed roots; precedence request > env > default; `.env` support consistent with the CLI) in `src/bird_recognition/api/settings.py`
- [x] T009 [P] Implement problem+json models, exception handlers (validation → `validation_error` with `errors[{field,message}]`, unhandled → `internal_error` generic detail), stable codes from data-model.md, `type` URN `urn:bird-recognition:error:<code>`, and detail sanitising (no DB URLs, keys, filesystem paths) in `src/bird_recognition/api/errors.py`
- [x] T010 [P] Implement `X-API-Key` dependency using `secrets.compare_digest` (enforced when key set; `GET /v1/health` exempt) and loopback host check in `src/bird_recognition/api/security.py`
- [x] T011 Implement `create_app()` with `/v1` router mounting, lifespan holding lazily created DB pool and query embedder on `app.state` (loaded once, FR-016), error handlers and security wiring in `src/bird_recognition/api/app.py` (depends on T008–T010)
- [x] T012 [P] Implement shared Pydantic models `Page`/list envelope `{items, limit, offset, total}` (limit 1–100 default 20, offset ≥ 0) and `ProblemDetails` in `src/bird_recognition/api/schemas.py`
- [x] T013 [P] Implement `bird-recognition-api serve` (uvicorn, `workers=1`, refuse non-loopback host without API key) in `src/bird_recognition/api/server.py`
- [x] T014 [P] Unit tests for settings precedence in `tests/unit/api/test_settings.py`
- [x] T015 [P] Unit tests for API-key enforcement, health exemption and non-loopback refusal in `tests/unit/api/test_security.py`
- [x] T016 [P] Unit tests for problem+json shape, stable codes and sanitising (SC-003) in `tests/unit/api/test_errors.py`

**Checkpoint**: App factory runs with no routers; CLI behaviour unchanged.

---

## Phase 3: User Story 1 - Search and browse crops over HTTP (Priority: P1) 🎯 MVP

**Goal**: Health, search, crop details/image, runs, visits with CLI-equivalent results.

**Independent Test**: Against fake services (and optionally a disposable indexed DB), request search, crop, runs, visits; compare with CLI payloads.

### Tests for User Story 1

- [x] T017 [P] [US1] Tests for `GET /v1/health` (ready, DB unreachable → 503 problem) in `tests/unit/api/test_health.py`
- [x] T018 [P] [US1] Tests for `POST /v1/search` parity with `_search_payload`, validation (`query` 1–500 chars, `limit` 1–50 default 5), failure-code mapping in `tests/unit/api/test_search.py`
- [x] T019 [P] [US1] Tests for `GET /v1/crops/{crop_id}` and `/image` (404 not found, only stored screened crop under crop root, jpeg/png allow-list, no frame endpoint) in `tests/unit/api/test_crops.py`
- [x] T020 [P] [US1] Tests for `GET /v1/runs`, `/v1/runs/{run_id}` pagination and 404 in `tests/unit/api/test_runs.py`
- [x] T021 [P] [US1] Tests for `GET /v1/visits?run_id=` parity with `aggregate-visits --json` and reviewed-groups requirement in `tests/unit/api/test_visits.py`

### Implementation for User Story 1

- [x] T022 [P] [US1] Add `SearchRequest`/`SearchResponse`, `CropDetail`, `RunSummary`, `RunDetail`, `VisitList` models derived from CLI payloads (quote constraints from data-model.md) in `src/bird_recognition/api/schemas.py`
- [x] T023 [P] [US1] Implement `GET /v1/health` in `src/bird_recognition/api/routers/health.py`
- [x] T024 [US1] Implement `POST /v1/search` as sync `def` calling shared payload builders, including caveats text, in `src/bird_recognition/api/routers/search.py`
- [x] T025 [US1] Implement crop details and image endpoints (path resolved from DB record, verified under configured crop root, extension allow-list) in `src/bird_recognition/api/routers/crops.py`
- [x] T026 [P] [US1] Implement run list/detail endpoints reusing `inspect` logic in `src/bird_recognition/api/routers/runs.py`
- [x] T027 [P] [US1] Implement `GET /v1/visits` reusing `embed/visits.py` aggregation in `src/bird_recognition/api/routers/visits.py`
- [x] T028 [US1] Mount US1 routers in `src/bird_recognition/api/app.py` and run `tests/unit/api`
- [x] T029 [P] [US1] Add the opt-in integration parity test (≥10 search/inspect/visit inputs, SC-001); it was collected but not run because it requires private assets and an initialized disposable database

**Checkpoint**: US1 independently functional (MVP).

---

## Phase 4: User Story 2 - Discoverable, validated API description (Priority: P1)

**Goal**: Generated OpenAPI 3.1, committed, validated and drift-checked.

**Independent Test**: `export-openapi --check` passes; stale file fails.

- [x] T030 [P] [US2] Contract test: validate generated document with `openapi-spec-validator` and compare with `docs/api/openapi.json`; include a stale-file failure case (SC-007) in `tests/unit/api/test_openapi.py`
- [x] T031 [US2] Implement deterministic export (sorted keys, fixed `info.version`) and `--check` in `src/bird_recognition/api/openapi.py`
- [x] T032 [US2] Add `export-openapi [--check] [--output docs/api/openapi.json]` subcommand to `src/bird_recognition/api/server.py`
- [x] T033 [US2] Put FR-014 caveats (confidence/similarity not biological probabilities; visits need owner-reviewed groups) in `info.description` and relevant operation descriptions in `src/bird_recognition/api/app.py` and routers; document problem+json responses for all operations
- [x] T034 [US2] Generate and commit `docs/api/openapi.json` via `bird-recognition-api export-openapi`

**Checkpoint**: Contract test passes with committed file.

---

## Phase 5: User Story 3 - Ask questions about footage (Priority: P2)

**Goal**: `POST /v1/ask` with required opt-in and transmission notice.

**Independent Test**: Without opt-in → 403, fake LLM never called; with opt-in → answer + notice matching CLI.

- [x] T035 [P] [US3] Tests: missing/false `allow_external_transmission` → 403 `opt_in_required` and zero calls to fake LLM/retrieval (SC-004); opt-in response parity with `_ask_payload`; sanitised LLM errors in `tests/unit/api/test_ask.py`
- [x] T036 [P] [US3] Add `AskRequest` (`SearchRequest` fields + `allow_external_transmission`, must be true) and `AskResponse` models in `src/bird_recognition/api/schemas.py`
- [x] T037 [US3] Implement `POST /v1/ask` reusing `src/bird_recognition/ask.py` and `payloads.py`; opt-in checked before any retrieval; LLM key from env only; in `src/bird_recognition/api/routers/ask.py`
- [x] T038 [US3] Mount ask router in `src/bird_recognition/api/app.py`; regenerate `docs/api/openapi.json`

**Checkpoint**: US3 works independently; OpenAPI check passes.

---

## Phase 6: User Story 4 - Run long jobs and track them (Priority: P3)

**Goal**: Ingest/index background jobs as CLI subprocesses with file-based records.

**Independent Test**: Start job with fake runner; immediate 202; poll to terminal state; conflict, path and restart cases.

- [x] T039 [P] [US4] Tests for JobManager: transitions `queued → running → succeeded|partial|failed`, exit code mapping (0/2/other), atomic writes, startup recovery to `interrupted`, one-active-job conflict, terminal immutability, no secrets/paths in records in `tests/unit/api/test_jobs.py`
- [x] T040 [P] [US4] Tests for job endpoints: 202 ack, 409 `job_conflict`, 403 `path_not_permitted` (incl. symlink escape), 503 `jobs_not_configured`, 404, pagination in `tests/unit/api/test_jobs_router.py`
- [x] T041 [P] [US4] Add `src/bird_recognition/__main__.py` if absent so `python -m bird_recognition` works
- [x] T042 [US4] Implement `JobManager` (subprocess `sys.executable -m bird_recognition ... --json`, records `<jobs_dir>/<job_id>.json` per data-model.md, sanitised report/error, startup interruption recovery) in `src/bird_recognition/api/jobs.py`
- [x] T043 [P] [US4] Add `IngestJobRequest`, `IndexJobRequest`, `Job` models in `src/bird_recognition/api/schemas.py`
- [x] T044 [US4] Implement `POST /v1/ingest`, `POST /v1/index`, `GET /v1/jobs`, `GET /v1/jobs/{job_id}`; paths via `paths.py` helpers, must be under allowed roots and pass `validate_destination`; in `src/bird_recognition/api/routers/jobs.py`
- [x] T045 [US4] Mount jobs router and run `JobManager` recovery in app lifespan in `src/bird_recognition/api/app.py`; regenerate `docs/api/openapi.json`

**Checkpoint**: All stories functional.

---

## Phase 7: Polish & Cross-Cutting

- [x] T046 [P] Add HTTP service section (start, auth, jobs, errors, caveats) to `docs/usage.md`
- [x] T047 [P] Add OpenAPI export/check and API test notes to `docs/development.md`; link the service from root `README.md` (brief)
- [x] T048 Verify `.github/workflows/ci.yml` runs the OpenAPI contract test and remains aligned with documented checks (pytest already covers it; adjust only if needed)
- [x] T049 [P] Add a test asserting no route returns full frames and every error response is problem+json (SC-003/SC-004) in `tests/unit/api/test_privacy.py`
- [x] T050 Walk through `specs/006-fastapi-service/quickstart.md` and fix discrepancies
- [x] T051 Run full unit suite `.\.venv\Scripts\python.exe -m pytest`, then pre-commit/Ruff as the last step

---

## Dependencies & Execution Order

- Setup (P1) → Foundational (P2) → stories. T005→T007; T011 needs T008–T010.
- US1 needs Phase 2. US2 needs US1 routers to exist (document content) but its export tooling (T031–T032) can start after Phase 2. US3 and US4 need Phase 2 only; each regenerates `openapi.json` last (T038, T045).
- Within a story: tests → schemas → routers → mounting.
- Tasks editing `schemas.py`, `app.py`, `server.py` are sequential across stories.

## Parallel Examples

- Phase 2: T006, T008, T009, T010, T012, T013 together.
- US1 tests T017–T021 together; then T023, T026, T027 together.
- US3 (T035–T037) and US4 (T039–T043) can proceed in parallel after US1, coordinating on shared files.

## Implementation Strategy

- **MVP**: Phases 1–3 (US1), then US2 to lock the contract.
- Incrementally add US3 (opt-in ask), then US4 (jobs); regenerate and commit OpenAPI at each step.
- Do not edit completed specs (001–005); AGENTS.md rules apply (full `.\.venv\Scripts\` command paths, scoped approval for dependencies).
