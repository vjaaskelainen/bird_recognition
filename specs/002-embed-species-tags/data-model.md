# Data Model: Crop Embeddings and Zero-Shot Species Tags

**Date**: 2026-10-19 | **Related**: [research.md](research.md), [contracts/cli.md](contracts/cli.md)

## Identity and representation conventions

- UUIDs identify runs, representations, decisions and evaluations. SHA-256 digests
  identify canonical versioned content. Persist canonical JSON as well as hashes.
- Canonical JSON is UTF-8, sorted object keys, compact separators, no NaN/Infinity;
  sort candidate arrays by stable trimmed ID. Decimal threshold is canonicalized
  from its validated numeric value so `0.50` and `0.5` select the same config.
- PostgreSQL `timestamptz` is used for processing times in UTC. Preserve ingestion
  capture time/timezone as their original nullable text fields as well, rather
  than guessing/normalizing away source information. Unknown lighting is `unknown`.
- All score/vector inputs are finite. Validate in Python and enforce finite
  ranges/dimensions/nonzero norms in database constraints where applicable;
  PostgreSQL NaN must be explicitly rejected, not only checked against a lower bound.
- Database schema lives in `bird_embed`, with an explicit schema-version record.
  Application schema version mismatch is preflight failure, not auto-migration.

## 1. IngestedCropSnapshot (`crop_snapshot`)

Immutable read-only import of existing ingestion evidence, not a recreated crop.

| Field | Type / rule |
|-------|-------------|
| snapshot_id | SHA-256 of crop_id plus provenance digest; PK |
| crop_id | Existing `animal_crop.crop_id`; required |
| provenance_sha256 | Digest of complete semantic provenance below |
| crop_sha256 | Expected ingestion crop-byte SHA-256 |
| source_id, source_content_sha256 | Existing source identity and bytes digest |
| source_original_path, source_basename | Original source locator, not uploaded |
| ingest_settings_fingerprint, ingestion_run_id | Existing ingestion context |
| frame_number, elapsed_seconds | Nonnegative frame/time |
| detection_id, detection_category | Original ID; qualified `animal` only |
| detection_confidence | Finite [0,1], distinct from species confidence |
| detection_box_normalized | Original four finite normalized detection coordinates |
| crop_box_pixels, frame_width, frame_height | Original crop bounds and positive frame dimensions |
| crop_original_image_path | Original manifest-relative image location |
| capture_time, capture_timezone | Nullable original values; never fabricated |
| source_capture_start, source_capture_timezone | Nullable source-level values |
| lighting | `day`, `night`, `unknown`; copied, not inferred |
| imported_at | First successful import time |

Unique `(crop_id, provenance_sha256)`. Semantic provenance includes every source,
frame, detection, capture, lighting and original path field above, including crop
hash/settings identity, but excludes processing times and resolved manifest/crop
root locators. Snapshots survive manifest relocation and distinguish changed
metadata. A missing capture value remains null even when processing time is known.

Manifest adapter joins all four actual ingestion tables using composite frame and
detection keys. Validate retained frame, qualifying animal detection, bounds and
identity consistency before writes. Only structural manifest failures are
preflight errors; individual crop path/read/hash/decode failures are run-item
failures. Source manifest/crops are never written by this feature.

## 2. EmbeddingModel (`embedding_model`)

| Field | Type / rule |
|-------|-------------|
| model_fingerprint | SHA-256 canonical model contract; PK |
| upstream_name, upstream_revision | `imageomics/bioclip` and immutable revision |
| checkpoint_sha256, config_sha256, tokenizer_sha256 | Asset identity |
| architecture, dimension | `ViT-B-16`, 512 for this schema |
| preprocessing_json | Image size, normalization, RGB/transform policy and version |
| tokenizer_json, adapter_version | Prompt tokenization/runtime contract |
| runtime_json | Relevant library versions, CPU float32/eval/inference policy |
| logit_scale | Finite positive effective scale from checkpoint |
| canonical_json | Complete hashed model identity |

Fingerprint changes for any embedding-affecting setting. Paths are run locators,
not version identifiers. A different checkpoint/model requires new vectors even
if its dimension is 512. Other dimensions fail preflight under schema v1.

## 3. SpeciesCandidateSet (`candidate_set`)

| Field | Type / rule |
|-------|-------------|
| candidate_set_fingerprint | SHA-256 of validated canonical content; PK |
| schema_version | 1 |
| candidates_json | Sorted array of `{id, name}`; nonempty |
| canonical_json | Hash source; retain exact trimmed candidate names |
| created_at | First saved time |

Reject non-string/blank identifiers or names, reserved identifier `unknown`,
duplicate IDs or names after trimming/casefold, unknown fields and duplicate JSON
object keys. IDs remain case-preserving and are matched exactly in labels/output.
No implicit global species. File order/path and insignificant whitespace do not
alter identity; changed candidate names/IDs do. Do not store the threshold here.

## 4. Scoring and decision configuration (`tagging_config`)

| Field | Type / rule |
|-------|-------------|
| config_fingerprint | PK: model + candidates + scoring + threshold digest |
| model_fingerprint | FK embedding_model |
| candidate_set_fingerprint | FK candidate_set |
| scoring_fingerprint | Model/candidates/prompt/scale/normalization/softmax/tie contract digest; excludes threshold |
| prompt_template, prompt_version | `a photo of {name}.`, `species-photo-v1` |
| effective_logit_scale | Finite positive |
| scoring_json | Full versioned formula, precision and normalization/tie policy |
| threshold | Finite double [0,1], default 0.5 |
| canonical_json | Hash source |

No user-adjustable prompt or temperature in v1; still persist their versions.
Changed threshold creates a new decision configuration but may reuse an earlier
score map with the same scoring fingerprint. Changed candidate content needs new
scores, not new compatible image vectors.

## 5. CropRepresentation (`crop_representation`)

| Field | Type / rule |
|-------|-------------|
| representation_id | UUID PK |
| snapshot_id | FK crop_snapshot |
| model_fingerprint | FK embedding_model |
| embedding | `vector(512)`, finite, nonzero, L2-normalized within documented float32 tolerance (1e-5) |
| processed_at | UTC embedding completion time |
| created_run_id | FK processing_run |

Unique `(snapshot_id, model_fingerprint)`. Stored rows are complete, not pending
representations. Insert a new row only in the transaction containing its first
completed decision. Validate dimension/norm before writing. Do not overwrite an
embedding with a different model or silently truncate/pad vectors.

## 6. SpeciesDecision (`species_decision`)

| Field | Type / rule |
|-------|-------------|
| decision_id | UUID PK |
| representation_id | FK crop_representation |
| config_fingerprint | FK tagging_config |
| assigned_species_id | Candidate ID or null; CLI exposes null as `unknown` |
| best_candidate_id | Unique best ID or null on exact tie |
| confidence | Maximum candidate-relative softmax score, finite [0,1] |
| tied_candidate_ids | Empty for unique best, otherwise >=2 candidate IDs |
| candidate_scores_json | Ordered `{id, logit, score}` entries for every candidate |
| reason | `assigned`, `below_threshold`, `exact_tie` |
| warnings_json | Always relative-candidate warning; single-candidate warning when applicable |
| processed_at, created_run_id | UTC decision time, FK run |

Unique `(representation_id, config_fingerprint)`. Representation model must match
config model. All IDs must belong to referenced candidate content (validate within
storage boundary as well as pure scorer). Unique best at threshold equality is
assigned; unique best below threshold has null assignment and retained best ID.
Tie takes precedence over threshold: null best/assignment, tied IDs and shared
confidence retained. Reason/assignment/best/tie fields must agree. Score maps sum
to 1 within numeric tolerance. Malformed scores are failures, never unknown tags.
No species decision is marked complete before transaction commit.

## 7. ProcessingRun and RunItem (`processing_run`, `run_item`)

Run fields: `run_id` UUID PK, UTC start/completion, status, config FK, manifest
locator, optional relocated crop root, selection fingerprint (sorted crop ID /
provenance pairs), selected/completed/skipped/failed/assigned/unknown counts,
failure summaries and sanitized settings JSON. Store no database URL or secrets.

Run-item fields: `(run_id, crop_id)` PK, expected snapshot identity/provenance,
resolved input locator, state, nullable decision FK, failure code/reason, timestamps.
Run items can refer to pending/failed inputs without a persisted snapshot; successful
ones reference a decision whose representation points to the expected snapshot.
Snapshot/config/model rows needed for inference results are persisted together
with their successful crop transaction; run/config registration after preflight
may create immutable metadata records but never fabricated crop results.

States:

```text
run:  running -> complete | no_input | partial_failure | failed | interrupted
item: pending -> completed | skipped | failed
```

Only the lock owner may finalize/recover runs. `complete` includes all-skipped;
`no_input` means selected=0. Isolated failures yield `partial_failure` if any item
completed/skipped, otherwise `failed`. Fatal shared model/storage errors yield
`failed` even with earlier successful crops. On process death/finalization failure,
next writer marks stale running rows `interrupted`, preserving pending items.
Retries use a new run; history is immutable except recovery/finalization fields.

Summary invariants:

- `assigned + unknown = completed` (new decisions only, not skipped).
- At successful/ordinary per-crop-failure completion,
  `selected = completed + skipped + failed`.
- While running, interrupted, or fatally stopped,
  `selected = completed + skipped + failed + pending`.
- Counts and completed/skipped decision references update in the same transaction.
- Skipped means an existing complete decision for this snapshot/config, with no
  repeated inference. A cached vector without that decision is not skipped.

## 8. QualityEvaluation (versioned JSON report)

Evaluation labels are external UTF-8 JSON with schema version, selected run ID and
unique crop IDs. Each entry has `expected_species_id` (nonblank string or null),
`truth_kind` (`species`, `out_of_list`, `unidentifiable`) and optional notes.
Species truth requires a known candidate ID; out-of-list may carry an external
truth ID or null, but must not name a candidate; unidentifiable requires null.
Reject duplicate IDs and labels not selected by the run. No inferred truth or
lighting; lighting comes from the input snapshot/run-item provenance.

Report: schema version, evaluation UUID/time, run ID, label-content SHA-256,
model/candidate/scoring/config fingerprints, threshold and candidate warnings.
For each of `day`, `night`, `unknown`: labeled sample count, completed count,
correct assignments, incorrect assignments, unknown decisions, failed/pending
counts, assigned-tag precision, assignment coverage, processing coverage and
per-example failure cases. Also report total run items without labels; evaluation
may cover a subset but must disclose it.

- Assigned = correct + incorrect. All assignments to out-of-list/unidentifiable
  examples are incorrect. Unknowns are not counted as correct assignments.
- Precision = correct / assigned; null if assigned=0.
- Assignment coverage = assigned / completed labeled decisions; null if completed=0.
- Processing coverage = completed / labeled samples; null if labeled samples=0.
- Completed includes decisions referenced by skipped run items. Failures/pending
  are not unknown decisions. Report their counts separately.
- Publication readiness requires >=10 completed labeled day and >=10 completed
  labeled night examples, but never asserts an accuracy target was met.

Report generation reads persisted rows only, not images/model/current species
files. Reports go outside version control; no separate evaluation DB table is
required for this bounded feature.

## Transaction and recovery contract

1. Read/validate manifest snapshot, species, threshold, local model assets and
   model loading, database schema/extension/permissions; acquire writer lock.
   Any failure exits preflight with zero crop-result writes.
2. Recover stale runs and create the new run/config/pending item records only
   after preflight. Zero input records a no-input run, no vectors/decisions.
3. Verify crop file hash, look up complete decision first. If present, transactionally
   mark skipped; do no inference. Otherwise load compatible persisted image vector
   or compute one. Reuse compatible score maps when only threshold changed.
4. Compute/validate decision outside the write transaction. In one transaction,
   insert immutable provenance/references, vector if needed, decision, successful
   run item and counters. Unique conflicts load existing compatible rows, never
   overwrite them. The advisory writer lock prevents concurrent duplicate inference.
5. Isolated errors record failed item/reason and counter transactionally. Stop on
   any storage failure; preserve earlier committed rows and pending remainder.
6. Finalize run and release session lock on close. If commit acknowledgement was
   lost, report unconfirmed work; next run checks durable completion before reuse.
   Never claim an unconfirmed transaction as a locally confirmed successful crop.

Use real PostgreSQL tests for extension/schema failures, constraints, rollback
between each insert, lost acknowledgement/restart, and lock release on connection
death. In-memory substitutes alone cannot prove this contract.
