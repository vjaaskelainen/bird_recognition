# Data Model: HTTP Service

The service adds no database tables. Crops, runs and visits are the existing records;
only the Job record is new (file-based).

## Existing entities (read-only via API)

| Entity | Source | Exposed as |
|---|---|---|
| Crop | `embed/storage.py` crop records | `CropDetail` (metadata, species candidates, lighting, provenance: source video, frame/time, detection) + image bytes |
| Run | embedding/index runs | `RunSummary` (list), `RunDetail` (inspect payload) |
| Visit | `embed/visits.py` aggregation | `VisitList` (requires explicit reviewed groups) |
| Search result | `_search_payload` | `SearchResponse` (same fields, `schema_version`, caveats) |
| Answer | `_ask_payload` | `AskResponse` (answer, cited crops, insufficient-evidence flag, transmission notice) |

Payload fields mirror the existing CLI JSON; the API models are derived from those
payloads and tested for parity.

## Job (new)

Stored as `<jobs_dir>/<job_id>.json`.

| Field | Type | Rules |
|---|---|---|
| `job_id` | UUID string | server-generated |
| `kind` | `ingest` \| `index` | |
| `status` | `queued` \| `running` \| `succeeded` \| `partial` \| `failed` \| `interrupted` | see transitions |
| `created_at`, `started_at`, `finished_at` | UTC ISO-8601 | `finished_at` null until terminal |
| `exit_code` | int \| null | 0 → succeeded, 2 → partial, other → failed |
| `request` | object | validated, canonical paths relative-safe; no secrets |
| `report` | object \| null | CLI `--json` report, sanitised |
| `error` | `{code, message}` \| null | sanitised |

**Transitions**: `queued → running → succeeded | partial | failed`; on server start any
`queued`/`running` → `interrupted`. Terminal states are immutable.

**Invariants**: at most one job in `queued`/`running`; records contain no database URL,
API key or unsanitised path text; paths lie under allowed roots.

## Request models

- `SearchRequest`: `run_id`, `query` (1–500 chars), `limit` (1–50, default 5),
  `species_id?`, `start_date?`, `end_date?`, `lighting?`.
- `AskRequest`: `SearchRequest` fields + `allow_external_transmission` (must be true).
- `IngestJobRequest`: `input_dir`, `output_dir`, thresholds/interval/extensions (optional,
  env defaults).
- `IndexJobRequest`: `manifest`/output path, `species_list?`, `threshold?`.
- `Page`: `limit` (1–100, default 20), `offset` ≥ 0.

## Problem details

`{type, title, status, detail, code, errors?[{field, message}]}`; `code` values reuse CLI
codes (e.g. `invalid_query`, `database_unavailable`, `schema_mismatch`, `writer_busy`)
plus API codes: `not_found`, `opt_in_required`, `unauthorized`, `job_conflict`,
`path_not_permitted`, `validation_error`, `internal_error`.
