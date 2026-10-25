# CLI Contract: Text Search over Wildlife Crops

**Status**: Planned local read-only `search` subcommand; existing commands remain
unchanged. See [data model](../data-model.md) for entity and score rules and
[quickstart](../quickstart.md) for validation scenarios.

## Invocation and common behavior

Run from repository root in Windows PowerShell:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition search "squirrel on the feeder" `
  --run-id "<completed-index-run-uuid>" `
  --limit 5 `
  --json
```

The positional query is one nonblank text string. Search requires one explicit
`--run-id`; use `inspect --list-runs` to discover available completed index runs.
The selected run is both the collection and the exact species-tagging context.
Search uses its compatible stored crop vectors and assigned decisions. It does not
re-ingest, rewrite data, recompute crop vectors, invoke answer generation, or
contact a service. It never downloads model assets.

The database and BioCLIP model bundle must be locally available. Runtime uses the
same original pretrained BioCLIP ViT-B-16 assets and adapter identity that produced
the selected run's vectors. A model fingerprint mismatch is an error. The run must
be `complete` or valid `no_input`; partial/failed/interrupted runs and incompatible
representations are not successful empty searches.

Exit codes:

- `0`: successful ranked results or successful zero results.
- `1`: operational failure; no partial result list is represented as complete.
- `2`: usage, invalid input, invalid selection/context, or prerequisite preflight
  failure.

With `--json`, stdout contains only the versioned JSON envelope; diagnostics never
contain database URLs or credentials. Without `--json`, print a readable summary,
filters/context, ranked provenance and score guidance. Argparse syntax errors use
its standard stderr diagnostic and exit 2.

## Options

| Option | Required / meaning |
|---|---|
| `QUERY` | Required positional nonblank query; whitespace-only is invalid |
| `--run-id UUID` | Required complete or valid no-input indexing run; pins crop collection and tagging context |
| `--limit N` | Positive whole-number result maximum; default 5 |
| `--start-date YYYY-MM-DD` | Optional inclusive recorded capture-date lower bound |
| `--end-date YYYY-MM-DD` | Optional inclusive recorded capture-date upper bound |
| `--lighting day\|night` | Optional exact stored lighting filter; unknown lighting does not match either value |
| `--species-id ID` | Optional stable ID in selected run's candidate set, or reserved `unknown` for unassigned decisions |
| `--database-url URL` | Local PostgreSQL URL; required explicitly or through the existing configuration variable |
| `--model-dir PATH` | Local BioCLIP asset directory; required explicitly or through the existing configuration variable |
| `--json` | Optional versioned machine-readable outcome |

All filters combine and are applied over the complete selected collection before
ranking and the limit. Natural language in QUERY never sets or overrides filters.
Dates are strict calendar dates and inclusive; start may equal end but may not be
after end. The stored capture-time date is used without timezone conversion. Missing
or invalid capture times do not match a supplied date bound. Missing timezone is
preserved, not inferred. Species filtering uses only final `assigned_species_id`;
best-candidate suggestions never qualify. A known species with no matching crops
is a successful empty search.

## Configuration precedence and environment inventory

Existing precedence applies: explicit option > process environment > discovered
local `.env` > built-in default. Invalid explicit settings fail; they do not fall
back. Reuse existing variables only:

| Option | Environment variable | Built-in default |
|---|---|---|
| `--database-url` | `BIRD_RECOGNITION_DATABASE_URL` | none; required |
| `--model-dir` | `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR` | none; required |

`--run-id`, query, filters, and limit are explicit per-search values and have no
environment aliases. No new environment setting is planned, so `.env.example` needs
no addition unless implementation introduces a justified setting. Keep real
credentials in ignored `.env`; avoid URLs in shell history when possible. Database
connections must satisfy the project's local PostgreSQL validation.

## Success JSON envelope, schema version 1

```json
{
  "schema_version": 1,
  "status": "searched",
  "query": "squirrel on the feeder",
  "filters": {
    "start_date": null,
    "end_date": null,
    "lighting": null,
    "species_id": null
  },
  "requested_limit": 5,
  "returned_count": 1,
  "context": {
    "run_id": "00000000-0000-0000-0000-000000000001",
    "model_fingerprint": "<sha256>",
    "config_fingerprint": "<sha256>",
    "candidate_set_fingerprint": "<sha256>"
  },
  "score": {
    "name": "cosine_similarity",
    "range": [-1, 1],
    "higher_is_more_similar": true,
    "interpretation": "relative retrieval relevance; not a probability"
  },
  "warnings": [
    "Species confidence is relative to the selected candidate set, not a calibrated probability of biological correctness.",
    "Retrieval similarity, species confidence, and detection confidence are distinct scores; none proves a species or event."
  ],
  "results": [
    {
      "rank": 1,
      "similarity": 0.75,
      "crop_id": "stable-crop-id",
      "snapshot_id": "<sha256>",
      "representation_id": "00000000-0000-0000-0000-000000000002",
      "decision_id": "00000000-0000-0000-0000-000000000003",
      "crop_path": "<selected-run-local-crop-locator>",
      "image_status": "available",
      "source": {
        "source_id": "stable-source-id",
        "video": "camera-video.mp4",
        "original_path": "<recorded-source-path>",
        "frame_number": 10,
        "elapsed_seconds": 5.0
      },
      "capture": {"time": "2026-10-25T12:00:00", "timezone": null},
      "lighting": "unknown",
      "detection": {
        "id": "stable-detection-id",
        "category": "animal",
        "confidence": 0.9,
        "box_normalized": [0.1, 0.2, 0.5, 0.6],
        "crop_box_pixels": [10, 20, 50, 60],
        "frame_width": 100,
        "frame_height": 100
      },
      "species": {
        "assigned_species_id": "unknown",
        "confidence": 0.4,
        "config_fingerprint": "<sha256>"
      }
    }
  ]
}
```

The JSON values above are illustrative only; no IDs, scores, or retrieval quality are
promised by this example. Emit explicit null/`unknown` values for absent metadata.
`image_status` is `available` or `unavailable`; an unavailable file retains its
rank, score and provenance. Each result includes stable crop and representation
identity and the exact selected decision context. `returned_count` is the number of
results actually returned (never greater than requested limit or eligible count).

A valid zero-result search uses the same envelope with `status: "searched"`,
`returned_count: 0`, and an empty `results` array. It does not relax filters or claim
that the described event is absent from all footage.

## Failure JSON envelopes

Preflight/validation/context failure (exit 2):

```json
{"schema_version":1,"status":"preflight_failure","code":"invalid_search","message":"actionable sanitized explanation"}
```

Operational failure (exit 1):

```json
{"schema_version":1,"status":"operational_failure","message":"actionable sanitized explanation"}
```

Stable codes should distinguish invalid query/date/range/lighting/limit/species,
invalid or incomplete run selection, database/schema/model unavailability,
representation incompatibility, and invalid numeric results. Do not include a
successful outcome or partial results on failure. Sanitize database errors and
never disclose credentials.

## Score and interpretation requirements

Similarity is normalized-vector cosine in `[-1, 1]`, sorted descending; ties use
ascending stable crop ID. It is not a calibrated relevance probability and does not
confirm that the query describes the crop. Species confidence is relative within the
selected candidate set and may be high for an out-of-list animal. Detection
confidence measures detector output. Keep all three labels distinct. Consecutive
similar crops may each appear; no threshold, visit grouping, or near-duplicate
suppression is applied.

