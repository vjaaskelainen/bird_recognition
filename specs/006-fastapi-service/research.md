# Research: HTTP Service for Bird Recognition

All spec/exploration open questions are resolved below.

## 1. Scope and shared logic

- **Decision**: v1 = reads, `ask`, ingest/index jobs. Move `_search_payload`, `_ask_payload`,
  `_search_failure_code`, `_preflight_code`, `_sanitize_ask_error` into
  `bird_recognition/payloads.py`, and `canonicalize_*`/`validate_destination` into
  `paths.py`; `cli.py` re-imports them.
- **Rationale**: FR-003 forbids duplicated rules; existing CLI tests guard behaviour.
- **Alternatives**: calling the CLI for everything (slow, loses model reuse); copying logic (drift).

## 2. In-process vs subprocess

- **Decision**: in-process for search, ask, crops, runs, visits (sync `def` endpoints run in
  Starlette's threadpool because psycopg access is blocking). Subprocess of the CLI
  (`sys.executable -m bird_recognition ...`, adding `__main__.py` if absent) for `ingest`
  and `index`, with `--json` reports.
- **Rationale**: model-heavy jobs get process isolation, exact CLI exit codes (0 success,
  2 partial, 1 failure per CLI contracts) and no memory growth in the server.
- **Alternatives**: in-process threads (GIL/GPU contention, crash takes down server).

## 3. Job persistence

- **Decision**: one JSON record per job in `BIRD_RECOGNITION_API_JOBS_DIR` (required to
  enable job endpoints; must be outside the repo). Written atomically (temp + rename). On
  startup, records still `running`/`queued` become `interrupted`.
- **Rationale**: no DB schema change; satisfies "interrupted or final report".
- **Alternatives**: DB table (migration + writer coupling); in-memory (loses state).

## 4. Concurrency

- **Decision**: one active job at a time; a second request returns `409` problem
  `job_conflict`. Existing `writer_busy` preflight remains a second line of defence.
- **Alternatives**: queue (more state, not required: "rejected or queued").

## 5. Authentication and binding

- **Decision**: default host `127.0.0.1`. If host is not loopback, startup fails unless
  `BIRD_RECOGNITION_API_KEY` is set; then all routes except `GET /v1/health` require the
  `X-API-Key` header, compared with `secrets.compare_digest`. On loopback the key is
  optional (enforced if set).
- **Rationale**: FR-008 minimal guard; needs constitution amendment (see plan).
- **Alternatives**: OAuth/JWT (out of scope), reverse proxy only (not enforceable by app).

## 6. Path restrictions

- **Decision**: job inputs/outputs are canonicalised with the shared helpers, must lie
  under `BIRD_RECOGNITION_API_ALLOWED_ROOTS` (path-separator list, required for job
  endpoints), and pass `validate_destination`. Reject symlink escapes via resolved paths.
  Responses never echo absolute paths from errors (sanitised).
- **Alternatives**: free paths like the CLI (unsafe for remote callers).

## 7. Ask opt-in

- **Decision**: request body requires `allow_external_transmission: true`; otherwise `403`
  problem `opt_in_required` before any retrieval is sent. The response includes the
  transmission notice text produced by a shared helper (same wording as CLI).
- **Rationale**: FR-007 / spec 005 semantics.

## 8. Crop images and privacy

- **Decision**: `GET /v1/crops/{id}/image` serves only the stored privacy-screened crop
  file resolved from the DB record, verified to lie under a configured crop root; no
  frame endpoints exist. Content type from file extension allow-list (jpeg/png).

## 9. Errors

- **Decision**: RFC 9457 `application/problem+json` with `type` URN
  `urn:bird-recognition:error:<code>`, `title`, `status`, `detail` (sanitised), `code`
  and, for validation, `errors[]` with field names. Codes reuse the existing CLI codes;
  422 from FastAPI validation and unhandled exceptions are remapped (`internal_error`,
  generic detail).

## 10. OpenAPI

- **Decision**: FastAPI generates OpenAPI 3.1; `bird-recognition-api export-openapi`
  writes deterministic JSON (sorted keys, fixed `info.version`) to `docs/api/openapi.json`;
  `--check` exits non-zero if different; a pytest contract test validates with
  `openapi-spec-validator` and compares with the committed file; CI already runs pytest,
  so no new CI job is required (`ci.yml` stays aligned).
- **Caveats** (FR-014) go into `info.description` and relevant operation descriptions.

## 11. Pagination and versioning

- **Decision**: `/v1` prefix; list endpoints take `limit` (default 20, max 100) and
  `offset`, return `{items, limit, offset, total}`.

## 12. Configuration

- **Decision**: precedence request > env > default, for settings that a request can
  override (search limit etc.). New env vars added to `.env.example`:
  `BIRD_RECOGNITION_API_HOST`, `_API_PORT`, `_API_KEY`, `_API_JOBS_DIR`,
  `_API_ALLOWED_ROOTS`. Server CLI flags override env.

## 13. Models and workers

- **Decision**: BioCLIP/query embedder and DB pool created lazily once in the app
  lifespan and stored on `app.state`; `uvicorn` run with `workers=1`; `--workers` is not
  exposed.

## 14. Dependencies

- **Decision**: add `fastapi`, `uvicorn` (runtime), `httpx`, `openapi-spec-validator`
  (dev). Per AGENTS.md these need scoped approval; pin ranges like existing entries and
  let uv generate `uv.lock`.
