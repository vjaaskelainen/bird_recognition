# Data Model: Ingest Trail-Camera Videos

This model is the persistent, local provenance contract for [spec.md](spec.md). Private source videos, full frames, and crops are never committed to Git. SQLite stores the manifest; image bytes live under the selected output root.

## Entities

### IngestionRun

One CLI invocation with immutable effective settings and aggregate results.

| Field | Type | Rules |
|---|---|---|
| `run_id` | string | Stable UUID; primary key. |
| `started_at` | ISO-8601 timestamp | Operational run time, explicitly not a capture time. |
| `completed_at` | ISO-8601 timestamp or null | Set when run reaches a terminal state. |
| `status` | enum | `running`, `complete`, `no_input`, `partial_failure`, `failed`. |
| `input_root` | absolute path string | Canonical root supplied by owner. |
| `output_root` | absolute path string | Must be outside Git-tracked content and disjoint from the input tree. |
| `settings_json` | JSON object | Canonical effective config, including sampling, thresholds, supported extensions, detector package/version, exact MegaDetector V6 variant, local checkpoint and config digests, and lighting rule/version. |
| `settings_fingerprint` | hex digest | SHA-256 of canonical settings serialization. |
| `summary_json` | JSON object | Counts and failures; frame outcome totals reconcile exactly. |

### SourceVideo

A discovered video and its content-specific work identity. Its key is independent of basename.

| Field | Type | Rules |
|---|---|---|
| `source_id` | string | Stable digest/UUID derived from normalized absolute path and content SHA-256. |
| `original_path` | absolute path string | Preserve location for provenance; do not relocate or modify source. |
| `basename` | string | Informational only; not unique. |
| `content_sha256` | hex digest | Full content digest captured before processing. |
| `capture_start` | ISO-8601 local/offset time or null | Only from recognized reliable capture metadata; null means unknown. |
| `capture_timezone` | string or null | Explicit IANA/offset zone when known; null means unknown and MUST NOT be interpreted as UTC. |

A same-basename source at a different path has a distinct ID. A changed file at the same path has a distinct content/source fingerprint and is never silently substituted for existing output. `SourceVideo` describes media identity only; run-specific outcomes belong to `RunSource` below.

### RunSource

The result of evaluating one SourceVideo with one IngestionRun's settings.

| Field | Type | Rules |
|---|---|---|
| `run_id` | string | Foreign key to IngestionRun. |
| `source_id` | string | Foreign key to SourceVideo. |
| `settings_fingerprint` | hex digest | Effective settings used for this attempt. |
| `status` | enum | `processed`, `already_processed`, `failed`. |
| `failure_reason` | string or null | Actionable error for failed source. |
| `sampled_count`, `person_excluded_count`, `no_animal_count`, `retained_count`, `failed_frame_count`, `crop_count` | integer | Non-negative; frame outcomes reconcile to sampled_count. |

Logical key: `(run_id, source_id, settings_fingerprint)`. Rerun lookup uses `(destination, source_fingerprint, settings_fingerprint)` across completed records. A skipped source points to the prior completed output and does not duplicate crop records.

### SampledFrame

A sampled source frame and one mutually exclusive processing outcome. Rejection records do not require image retention.

| Field | Type | Rules |
|---|---|---|
| `source_id` | string | SourceVideo identity. |
| `settings_fingerprint` | hex digest | Effective settings used. |
| `frame_number` | integer | Zero-based decoded/original frame ordinal; non-negative. |
| `elapsed_seconds` | number | Non-negative PTS-derived time from first valid stream presentation time. |
| `frame_width`, `frame_height` | integer | Positive decoded image dimensions. |
| `capture_time` | ISO-8601 offset time or null | Reliable start time plus elapsed seconds; null if unavailable/ambiguous. |
| `capture_timezone` | string or null | Preserved timezone or explicit unknown. |
| `lighting` | enum | `day`, `night`, `unknown`; common to all crops from frame. |
| `outcome` | enum | Exactly one of `person_excluded`, `no_animal`, `retained`, `failed`. |
| `failure_reason` | string or null | Required for `failed`; not set for ordinary exclusions. |

Logical key: `(source_id, settings_fingerprint, frame_number)`. Failed decode/inference/storage outcomes are failures, never empty or safe. Only the frame outcome and necessary diagnostic metadata persist for rejected frames; no rejected still is retained.

### Detection

An inference result for a sampled frame. Detections may be retained in the manifest for both qualifying people and animals to make the exclusion outcome auditable; raw full-frame pixels are not retained.

| Field | Type | Rules |
|---|---|---|
| `detection_id` | string | Stable within source/settings/frame; distinguishes multiple boxes. |
| `source_id`, `settings_fingerprint`, `frame_number` | composite FK | References SampledFrame. |
| `category` | enum | Normalized `animal`, `person`, or `other`. |
| `confidence` | number | Finite value in `[0,1]`; category-specific threshold qualification is inclusive. |
| `box_normalized` | four numbers | Detector coordinates normalized to frame dimensions; validate before pixel conversion. |
| `qualifies` | boolean | Confidence `>=` category threshold for animal/person; `other` never creates crop. |

Malformed detections are rejected and reported as processing errors. Person qualification takes precedence over all animal detections for that frame.

### AnimalCrop

One complete crop and provenance record for one qualifying animal detection in a retained frame.

| Field | Type | Rules |
|---|---|---|
| `crop_id` | string | Stable digest from source/settings/frame/detection identity. |
| `source_id`, `settings_fingerprint`, `frame_number` | composite FK | References source and retained frame. |
| `detection_id` | string | Exactly one qualifying animal detection. |
| `image_path` | relative path | Must resolve under output root to an existing complete image. |
| `crop_sha256` | hex digest | Content digest of persisted crop bytes. |
| `box_left`, `box_top`, `box_right`, `box_bottom` | integer | Clipped source-frame pixel coordinates, non-empty; right/bottom exclusive. |
| `frame_width`, `frame_height` | integer | Positive original dimensions; crop region equals the stored box. |
| `confidence` | number | Animal confidence, finite in `[0,1]`, at/above animal threshold. |
| `elapsed_seconds`, `capture_time`, `capture_timezone` | number/time/nullable zone | Copied from frame/source timing; never inferred from file timestamps. |
| `lighting` | enum | Copied from the retained frame. |
| `run_id` | string | Run that produced this crop; links settings and batch context. |

## Relationships and invariants

- An IngestionRun has many RunSource records; SourceVideo media identities may appear in multiple runs. Each RunSource has one SourceVideo and one IngestionRun. A processed source/settings pair may produce many SampledFrame records.
- Each SampledFrame has zero or more Detection records and zero or more AnimalCrop records. Crops are allowed only when `outcome=retained`; a retained frame has at least one complete crop.
- `person_excluded`, `no_animal`, `retained`, and `failed` are mutually exclusive and sum to sampled-frame count. Crop count is independent and may exceed retained-frame count.
- A frame with any qualifying person has outcome `person_excluded` and zero crop rows/files, even when qualifying animals are also detected.
- `no_animal` means detection completed successfully and no qualifying animal exists (including vehicle-only); failed/incomplete detection is `failed`.
- A crop is published only if its image and all metadata are complete. File staging, rename, and manifest commit must not expose a subset of that frame's crops as success.
- Output paths are destination-relative and must remain within the selected root. Raw video and temporary frame content are not copied into output.
- A completed identical source/settings fingerprint is skipped on rerun. Changed content or effective settings creates a new identity; no previous output is overwritten.
