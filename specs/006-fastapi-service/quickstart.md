# Quickstart: Validating the HTTP Service

Run from the repository root. Contracts: [api.md](contracts/api.md); entities:
[data-model.md](data-model.md). Footage, models, jobs and reports stay outside the repo.

## Prerequisites

- Dependencies declared (`fastapi`, `uvicorn`, dev `httpx`, `openapi-spec-validator`).
- Constitution 1.1.0 ratified.
- For read scenarios: a database indexed per the [search quickstart](../003-search-crops/quickstart.md),
  `BIRD_RECOGNITION_DATABASE_URL` set privately.

## 1. Automated checks (offline)

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\api
.\.venv\Scripts\python.exe -m pytest
```

Expected: pass with no network or LLM key; includes OpenAPI validity/currency test and
problem-details/no-sensitive-text tests.

## 2. OpenAPI description

```powershell
.\.venv\Scripts\uv.exe run bird-recognition-api export-openapi --check
```

Expected: exit 0 when `docs/api/openapi.json` is current and valid; non-zero after any
endpoint change without re-export (SC-007).

## 3. Start locally and read (US1, US2)

```powershell
.\.venv\Scripts\uv.exe run bird-recognition-api serve
curl http://127.0.0.1:8000/v1/health
curl -X POST http://127.0.0.1:8000/v1/search -H "Content-Type: application/json" -d '{"run_id":"<run>","query":"blue tit on feeder"}'
.\.venv\Scripts\uv.exe run bird-recognition search --run-id <run> --json "blue tit on feeder"
```

Expected: health `ready`; HTTP search matches CLI JSON (matches, order, caveats);
unknown crop id returns a 404 problem+json.

## 4. Ask opt-in (US3)

POST `/v1/ask` with `run_id`, `question`, and no
`allow_external_transmission: true` → 403 `opt_in_required`, nothing sent. With it
(and `BIRD_RECOGNITION_ASK_API_KEY` configured) → answer plus transmission notice.
Automated tests cover this with a mocked LLM.

## 5. Reviewed visits (US1)

Pass the reviewed groups manifest explicitly:

```powershell
curl "http://127.0.0.1:8000/v1/visits?run_id=<run>&groups=<private-manifest-path>"
```

No visit group is inferred from shared video membership.

## 6. Jobs (US4)

Set `BIRD_RECOGNITION_API_JOBS_DIR` and `BIRD_RECOGNITION_API_ALLOWED_ROOTS`, start a job
via `POST /v1/ingest`, confirm an immediate 202 with `job_id`, poll `GET /v1/jobs/{id}`
until terminal, and compare its report/category with the CLI. A second start returns 409;
paths outside allowed roots return 403; restarting during a run reports `interrupted`.

## 7. Network exposure

`serve --host 0.0.0.0` without `BIRD_RECOGNITION_API_KEY` must refuse to start. With a
key, requests lacking a valid `X-API-Key` return 401 problem+json (health excepted).
