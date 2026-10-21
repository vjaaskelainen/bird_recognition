# CLI Contract: Species Indexing, Inspection, and Evaluation

**Status**: `database-init`, `index`, `inspect`, and `evaluate-species` are implemented; opt-in real PostgreSQL acceptance remains pending.
Existing `ingest` and `extract-frame` behavior stays unchanged.

## Invocation and common behavior

From repository root, Windows PowerShell 5.1:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition <command> <options>
```

Use local `.venv`; never activate it or invoke a bare Python tool. If it is absent,
stop for developer setup. Runtime requires no network and never fetches assets.
Indexing is sequential and uses one database-wide advisory writer lock; inspection
and evaluation are read-only and may run independently.

Exit statuses: `0` complete/no-input/read success; `1` partial/fatal processing or
operational failure; `2` usage/preflight/invalid selection. A failed evaluation
read is an operational error; an honestly low-quality report is not a command
failure. JSON stdout has no progress/log text; diagnostics go to stderr. All output
is sanitized; never expose credentials, connection URLs or raw psycopg errors
containing connection strings. Human output is readable but not a parsing API.

## Configuration precedence and environment inventory

Explicit options > process environment > discovered local `.env` > built-in
defaults, matching the existing CLI. Invalid explicit values fail rather than
fall back. Empty required path/URL values are errors, not an implicit candidate
list or connection. Explicit file/run selections have no environment aliases.

| Option | Environment variable | Built-in default |
|--------|----------------------|------------------|
| `--database-url` | `BIRD_RECOGNITION_DATABASE_URL` | none; required for all new commands |
| `--model-dir` | `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR` | none; required for index only |
| `--species-list` | `BIRD_RECOGNITION_SPECIES_LIST` | none; required for index only |
| `--threshold` | `BIRD_RECOGNITION_SPECIES_THRESHOLD` | 0.5 |

The connection must target the owner's local PostgreSQL service; reject remote
hosts in this local-only feature (accept localhost/loopback or local Unix socket
where supported). Do not derive a competing connection URL from `POSTGRES_*`;
those existing settings configure Compose. URL values/passwords are private. A
CLI URL is allowed for precedence consistency, but recommend environment/ignored
`.env` to avoid shell history/process-list exposure.

Additional opt-in test variables, inventoried during implementation:

- `BIRD_RECOGNITION_TEST_DATABASE_URL`: dedicated disposable local test database.
- `BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR`: provisioned local smoke-test assets.
- `BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE`: external privacy-checked smoke image.

No implicit access to a test database. Tests only use the explicitly named test
URL, with a disposable schema and cleanup, never the production URL. Standard
tests skip external-boundary tests when opt-ins are absent.

## `database-init`

Options: `--database-url URL`, optional `--json`.

Connect to the local existing database, create `vector` extension if permitted,
and apply bundled versioned schema migrations transactionally. Never create the
database/server itself, silently drop data, or proceed past an unknown schema
version. Idempotent when the expected schema already exists. Return schema/vector
versions and whether changes were applied. Setup/permission/migration failure
exits 2 with a sanitized explanation. This explicit administrative command is
the only command authorized to install vector support or migrate schema.

## `index`

| Option | Required / meaning |
|--------|--------------------|
| `--manifest PATH` | Required existing ingestion `manifest.sqlite3` |
| `--crop-root PATH` | Optional relocated crop root; default manifest's parent directory |
| `--species-list PATH` | Required via selected option/environment configuration |
| `--model-dir PATH` | Required external local BioCLIP asset bundle |
| `--threshold NUMBER` | Finite inclusive [0,1], default 0.5 |
| `--database-url URL` | Required local database |
| `--json` | Versioned summary JSON; otherwise human summary |

Select all durable retained animal crops in the manifest, ordered by crop ID.
Require ingestion to be idle while snapshotting. Open SQLite read-only/query-only,
validate schema/joins/provenance, then release the snapshot after capturing the
selected metadata. Do not call ingestion recovery or modify files. Reject invalid
manifest/model/species/threshold/database/vector/schema before writing any crop
results. Preflight is still required for a zero-crop input; create no fabricated
representations/decisions. Existing compatible vectors can be retagged through the
same command without video ingestion or image embedding inference.

For each selected crop, resolve its relative path beneath the effective crop root,
reject traversal/escape, verify bytes against the manifest hash, and query exact
snapshot/model/config completion before inference. An unreadable/hash-mismatched
crop is an isolated failure even if an earlier result exists. Complete unchanged
decisions require no image decoding/text/image inference. Changed threshold may
reuse compatible score maps; changed species list reuses only the image vector.
Changed model identity requires a new representation. Keep previous decisions.

Partial isolated failures continue while model/storage are healthy. Storage loss
or a broken shared model stops work immediately; report only confirmed commits,
pending remainder, and any unconfirmed transaction. If the DB is unavailable,
final status may remain running until recovery; never claim it was saved.

### Species file, schema version 1

```json
{
  "schema_version": 1,
  "species": [
    {"id": "cyanistes_caeruleus", "name": "Cyanistes caeruleus"},
    {"id": "parus_major", "name": "Parus major"}
  ]
}
```

At least one entry. Strict UTF-8 JSON with no duplicate keys/unknown fields.
Trim strings; reject blanks, non-string values and duplicate IDs/names under
casefold. `unknown` is reserved case-insensitively. Taxonomy and synonyms are not
resolved. Candidate IDs are stable owner-assigned strings. Candidate names become
`a photo of {name}.` prompts. No default species file is generated/selected.

### Asset bundle, schema version 1

External directory contains `open_clip_config.json`,
`open_clip_pytorch_model.bin`, `asset-manifest.json`. Asset manifest fields:
`schema_version` (1), `upstream_name` (`imageomics/bioclip`), `upstream_revision`
(immutable full upstream revision), `files` (mapping of the two exact file names
to SHA-256 digests). Model/tokenizer/runtime identity is derived and persisted by
the adapter as defined in [data-model.md](../data-model.md). The packaged BPE asset
must also be locally available. Missing/mismatched assets and unsupported model
architecture/dimensions are preflight failures. No download fallback.

### Index summary JSON, schema version 1

Required keys: `schema_version`, `run_id`, `status`, `config_fingerprint`,
`model_fingerprint`, `candidate_set_fingerprint`, `scoring_fingerprint`,
`threshold`, `counts`, `failures`, `warnings`, `durable_status_confirmed`,
`unconfirmed_crop_ids`.

`counts`: nonnegative `selected`, `completed`, `skipped`, `failed`, `assigned`,
`unknown`, `pending`. `assigned + unknown = completed`. On normal completion,
pending=0 and selected=completed+skipped+failed. Fatal/interrupted runs may retain
pending>0. A lost commit acknowledgement leaves the affected crop unconfirmed
and not counted as locally confirmed completed; explicitly flag that the durable
summary may differ until recovery. Normal output must not imply pending work
failed or completed. Skipped decisions do not inflate assigned/unknown counts.

`failures`: crop ID (when known), stable code, sanitized reason. Codes include
`crop_read_error`, `crop_hash_mismatch`, `crop_decode_error`, `invalid_vector`,
`invalid_scores`, `inference_error`, `model_unavailable`, `storage_error`.
Preflight error JSON instead has `schema_version`, `status: preflight_failure`,
`code`, `message`, `run_id: null`; no crop writes. Stable preflight codes include
`invalid_manifest`, `invalid_species`, `invalid_threshold`, `invalid_model`,
`database_unavailable`, `vector_unavailable`, `schema_mismatch`, `writer_busy`.

## `inspect`

| Option | Meaning |
|--------|---------|
| `--database-url URL` | Required local database |
| `--run-id UUID` | Select one saved run; mutually exclusive with `--list-runs` |
| `--list-runs` | List persisted run summaries, newest first |
| `--crop-id ID` | Optional run-item filter; requires `--run-id` |
| `--json` | Versioned JSON; default human text |

Require exactly one of run-id/list-runs; never implicitly mix configurations as
"latest". Unknown run/crop selection exits 2. No model/species-file/crop/manifest
access and no inference. Fetch saved run/item/provenance/config/decision records.

Run inspection includes status, durable counts, pending/failed items and reasons,
selected config, processing times and each successful/skipped decision's original
provenance. Decision output includes assigned ID or `unknown`, reason, unique best
candidate or null, confidence, tied candidates/shared score, all candidate scores,
warnings, representation ID, model/version and candidate content/version. A
pending/failed item has no completed decision for that run; never silently attach
an older config's decision. Skipped items reference their actual completed record.

Required explanatory warning: **Confidence is a relative score within the selected
candidate set, not a calibrated probability of biological correctness or the
ingestion detector's confidence. Scores from different candidate sets are not
directly comparable. Out-of-list animals can score highly.** Include the additional
single-candidate limitation when applicable. Preserve `day`/`night`/`unknown` and
null capture metadata in JSON. JSON envelope: `schema_version`, `runs` for a list,
or `schema_version`, `run`, `items` for one selected run.

## `evaluate-species`

Options: required `--run-id UUID`, `--labels PATH`, `--output PATH` and database
configuration; optional `--json` for stdout. Always write the versioned JSON report
to the explicit external output path. With `--json`, stdout is a versioned envelope
containing `status: evaluated`, the saved output path, and the report; otherwise
stdout is a concise human summary. Refuse overwriting an existing file and
reject destinations inside any Git repository. Validate all input/output paths
before writing; use an atomic temporary-file replacement for the final report.

Labels schema:

```json
{
  "schema_version": 1,
  "run_id": "00000000-0000-0000-0000-000000000001",
  "examples": [
    {
      "crop_id": "existing-ingestion-crop-id",
      "expected_species_id": "parus_major",
      "truth_kind": "species",
      "notes": "Owner-verified label"
    }
  ]
}
```

Run ID must match CLI. Each crop ID occurs once and belongs to that run. Species
truth names an exact candidate ID; `out_of_list` names an external ID or null but
not a selected candidate; `unidentifiable` requires null. Empty examples are valid
and yield unavailable metrics, not perfect results. Labels may select a subset;
report unlabeled count. Unknown fields, duplicate keys/IDs and invalid truth
combinations fail validation. Labels and optional notes must be privacy-reviewed.

Read persisted decisions, including skipped items. No inference/current asset
checks. Report per `day`, `night`, `unknown` group: sample/completed counts,
correct/incorrect assigned tags, unknowns, failed/pending, assigned-tag precision,
assignment coverage and processing coverage, plus observed per-example failures.
Use null/unavailable when denominator is zero. Include all evaluated model,
candidate, scoring, threshold and label versions. See exact formulas in
[data-model.md](../data-model.md). `publication_ready` is true only with >=10
completed labeled day and >=10 completed labeled night examples; it is not an
accuracy guarantee. No public quality claim before that gate and review of
measured results/failure cases.
