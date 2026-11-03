# CLI Contract: Ask Questions About Footage

**Status**: User Story 1 is implemented. The date, lighting, and species filters
in this end-state contract are planned for later stories. The current command
accepts `QUESTION`, `--run-id`, `--limit`, `--database-url`, `--model-dir`, and
`--json`. See
[data model](../data-model.md) for request/outcome semantics and
[quickstart](../quickstart.md) for validation.

## Invocation

```powershell
.\.venv\Scripts\uv.exe run bird-recognition ask `
  "Which birds visited the feeder at night?" `
  --run-id "<completed-index-run-uuid>" `
  --limit 5 `
  --json
```

The question is required and nonblank. The explicit `--run-id` selects one
complete indexed collection and its exact tagging context. Ask uses existing
search behavior and does not ingest footage, recompute stored representations,
or modify database rows, crops, manifests, or species decisions.

## Options

| Option | Required / meaning |
|---|---|
| `QUESTION` | Required nonblank natural-language question |
| `--run-id UUID` | Required complete or valid no-input index run |
| `--limit N` | Positive whole-number maximum evidence items; default 5 |
| `--start-date YYYY-MM-DD` | Optional inclusive recorded capture-date lower bound |
| `--end-date YYYY-MM-DD` | Optional inclusive recorded capture-date upper bound |
| `--lighting day\|night` | Optional exact stored lighting restriction |
| `--species-id ID` | Optional candidate ID in selected run or reserved `unknown` |
| `--database-url URL` | Existing local PostgreSQL URL option/configuration |
| `--model-dir PATH` | Existing local BioCLIP model directory option/configuration |
| `--json` | Optional versioned machine-readable outcome |

All metadata filters apply before the evidence limit, exactly as defined by the
[search contract](../../003-search-crops/contracts/cli.md). Question wording
never silently adds filters. The default evidence limit is 5.

## Answer service and privacy configuration

| Setting | Source | Default |
|---|---|---|
| Answer API key | `BIRD_RECOGNITION_ASK_API_KEY` in process environment or ignored local `.env` only | None; required |
| Answer model | `BIRD_RECOGNITION_ASK_MODEL` in process environment or local `.env` | `gpt-4o-mini` |
| Database URL | Existing `BIRD_RECOGNITION_DATABASE_URL` | None; required |
| BioCLIP model directory | Existing `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR` | None; required |

For regular non-secret settings, explicit CLI options take precedence over
process environment, `.env`, then defaults. The answer key has no CLI option and
must never appear in JSON, logs, prompts, or error messages.

Immediately before sending a nonempty selected evidence set, the command states
that the selected crops (when available) and their selected metadata will be sent
to the configured external answer service. Only selected crops and their
metadata may be transmitted. Full videos, unselected crops, and excluded frames
are never sent. In JSON mode, the transmission notice is written to stderr so
stdout remains one versioned JSON envelope.

## Outcomes and exit codes

- `0`: supported answer or successful insufficient-evidence decline.
- `1`: operational failure such as unavailable storage/model/service, timeout,
  refused/incomplete response, or malformed service output.
- `2`: invalid question, filter, evidence limit, run/context selection, missing
  credentials, or local preflight failure.

Supported answers include the question, applied filters, evidence limit/count,
selected collection and tagging context, each claim and its validated citations,
and per-item provenance. Similarity, species decision/confidence, and detection
confidence are separately labeled. Missing capture time remains unknown.
Unavailable images retain their provenance and are marked unavailable.

## JSON envelope, schema version 1

Supported result:

```json
{
  "schema_version": 1,
  "status": "answered",
  "question": "Which birds visited the feeder at night?",
  "filters": {
    "start_date": null,
    "end_date": null,
    "lighting": null,
    "species_id": null
  },
  "requested_limit": 5,
  "evidence_count": 2,
  "context": {
    "run_id": "00000000-0000-0000-0000-000000000001",
    "model_fingerprint": "<sha256>",
    "config_fingerprint": "<sha256>",
    "candidate_set_fingerprint": "<sha256>"
  },
  "claims": [
    {
      "text": "A bird identified by the selected species decision appears in one night-time crop.",
      "citations": [
        {
          "evidence_index": 0,
          "crop_id": "stable-crop-id",
          "source_video": "camera-video.mp4",
          "frame_number": 10,
          "capture_time": "2026-10-25T22:00:00"
        }
      ]
    }
  ],
  "evidence": [
    {
      "evidence_index": 0,
      "crop_id": "stable-crop-id",
      "image_status": "available",
      "similarity": 0.75,
      "species": {"id": "candidate-id", "confidence": 0.8},
      "detection_confidence": 0.9,
      "source_video": "camera-video.mp4",
      "frame_number": 10,
      "capture_time": "2026-10-25T22:00:00",
      "capture_timezone": null
    }
  ]
}
```

The example is illustrative only. IDs, scores, species outcomes, and semantic
answer quality are not promised. Citation values are resolved locally from the
selected evidence; model-supplied identifiers are not trusted.

An insufficient-evidence response uses `status: "insufficient_evidence"`, a
human-readable `reason`, and selected evidence (if any) labeled as retrieved but
not supporting an answer. Empty retrieval has `evidence_count: 0` and does not
contact the answer service.

## Failure envelopes

Input/preflight failure (exit 2):

```json
{"schema_version":1,"status":"input_error","code":"invalid_question","message":"actionable sanitized explanation"}
```

Operational failure (exit 1):

```json
{"schema_version":1,"status":"operational_failure","message":"actionable sanitized explanation"}
```

No failure envelope contains a supported answer, partial claim list, API key, or
database credential.
