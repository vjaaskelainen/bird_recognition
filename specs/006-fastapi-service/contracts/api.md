# HTTP API Contract (v1)

The authoritative machine-readable description is the generated OpenAPI 3.1 document,
committed at `docs/api/openapi.json`. This file records intent and behaviour that the
document must reflect.

Base path: `/v1`. Media type: `application/json`; errors: `application/problem+json`.
Auth: `X-API-Key` header, required when `BIRD_RECOGNITION_API_KEY` is set (mandatory for
non-loopback binding); `GET /v1/health` is exempt.

| Method & path | Purpose | Success | Equivalent CLI |
|---|---|---|---|
| `GET /v1/health` | readiness of service and database | 200 `{status, database}` / 503 problem | — |
| `POST /v1/search` | similarity search | 200 `SearchResponse` | `search --json` |
| `GET /v1/crops/{crop_id}` | crop metadata | 200 / 404 | `inspect` |
| `GET /v1/crops/{crop_id}/image` | privacy-screened crop image | 200 `image/jpeg\|png` / 404 | — |
| `GET /v1/runs` | list runs (paginated) | 200 page | `inspect` |
| `GET /v1/runs/{run_id}` | run detail/report | 200 / 404 | `inspect --json` |
| `GET /v1/visits?run_id=&groups=` | visit aggregation from reviewed groups manifest | 200 | `aggregate-visits --json` |
| `POST /v1/ask` | grounded answer (opt-in) | 200 `AskResponse` / 403 `opt_in_required` | `ask --json` |
| `POST /v1/ingest` | start ingestion job | 202 `{job_id, status}` | `ingest` |
| `POST /v1/index` | start indexing job | 202 `{job_id, status}` | `index` |
| `GET /v1/jobs` | list jobs (paginated) | 200 page | — |
| `GET /v1/jobs/{job_id}` | status and report | 200 / 404 | — |

## Behavioural rules

- Search/ask/visits results equal the CLI JSON payloads (same ordering, caveats).
- No endpoint returns full or unfiltered frames.
- `POST /v1/ask` without `allow_external_transmission: true` → 403, nothing is sent.
- Job start while another is active → 409 `job_conflict`; paths outside allowed roots →
  403 `path_not_permitted`; job endpoints disabled (503 `jobs_not_configured`) when jobs
  dir or allowed roots are unset.
- Job outcome mapping: exit 0 `succeeded`, 2 `partial`, otherwise `failed`.
- Lists: `limit` default 20, max 100; envelope `{items, limit, offset, total}`.
- Every error is problem+json with a stable `code`; no database URLs, keys or filesystem
  paths in `detail`.
- Visit requests require a reviewed group manifest path in `groups`; the manifest is
  validated by the same loader used by `aggregate-visits`.
- Operation descriptions state: species confidence and search similarity are not
  biological probabilities; visits require owner-reviewed groups.

## Server entry point

`bird-recognition-api serve [--host 127.0.0.1] [--port 8000]` and
`bird-recognition-api export-openapi [--check] [--output docs/api/openapi.json]`.
Single worker; refuses a non-loopback host without an API key.
