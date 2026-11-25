# Data Model: Web Frontend for Video Triage and Review

Source of truth: ingestion SQLite manifest (read-only) for videos, frames, detections and
crops; PostgreSQL `bird_embed` (migration `005_video_review.sql`) for reviews and
corrections. Identifiers are the existing manifest `source_id` and `crop_id`.

## Video (derived, not stored)

| Field | Source | Rules |
|---|---|---|
| `source_id` | `source_video` | null for `not_ingested` (use `path_id`, an opaque hash of the allowed-root-relative path) |
| `path`, `basename`, `folder` | `source_video` / scan | shown relative to the allowed root only |
| `capture_start` | `source_video` | optional |
| `status` | derived | `not_ingested` (no `run_source`), `failed` (latest `run_source.status = failed`, with `failure_reason`), `no_animals` (processed, crop_count = 0), `animals` (crop_count > 0) |
| `crop_count`, `top_label` | `run_source`, decisions | `top_label` = species if indexed else `animal` |
| `run_id`, `ingested_at` | latest `run_source` | latest run wins |
| `settings` | `ingestion_run.settings_json` | `interval`, `animal_threshold` effective values |
| `settings_differ` | derived | true if either differs from current configuration |
| `review_state` | `video_review` | `unreviewed`, `confirmed`, `corrected` |
| `playback_status` | cache probe | `ready`, `converting`, `failed`, `unavailable`, `source_missing`, `not_started` |
| `source_available` | filesystem | false if file missing/outside allowed roots |

## Review (`video_review`, append-only)

| Column | Type | Rules |
|---|---|---|
| `review_id` | uuid PK | server generated |
| `source_id` | text NOT NULL | manifest identity (content-hash based) |
| `outcome` | text | `confirmed` or `corrected` |
| `correction_kind` | text NULL | `no_animal`, `animal_missed`, `species_present`; NOT NULL iff `outcome = 'corrected'` |
| `species` | jsonb | array of species/category ids; non-empty iff `correction_kind = 'species_present'` |
| `missed_times` | jsonb | array of seconds ≥ 0 and ≤ video duration (if known); non-empty iff `animal_missed` |
| `note` | text NULL | ≤ 2000 chars |
| `auto_result` | jsonb NOT NULL | snapshot: status, crop_count, top_label, run_id, settings |
| `created_at` | timestamptz | default now() |
| `bulk_id` | uuid NULL | set for bulk confirmations |

`video_review_undo(review_id PK/FK, undone_at)`: marks a review as undone. **Current review**
= latest `video_review` row for the `source_id` without an undo row. If none, the video is
unreviewed. History = all rows for the `source_id`, newest first. Rows are never updated or
deleted. Bulk confirmation is allowed only when the automatic status is `no_animals`.

State transitions: `unreviewed → confirmed | corrected`; a new review supersedes the
current one; undo removes the current one so the previous review (if any) becomes current
again, otherwise the video is `unreviewed`. *Skip* has no stored state.

## Crop correction (`crop_correction`, append-only)

| Column | Type | Rules |
|---|---|---|
| `correction_id` | uuid PK | |
| `crop_id` | text NOT NULL | manifest crop id; no FK (exists before indexing) |
| `source_id` | text NOT NULL | owning video |
| `truth_kind` | text | `species`, `out_of_list`, `unidentifiable` (same kinds as evaluation labels) |
| `species_id` | text NULL | NOT NULL iff `truth_kind = 'species'` |
| `created_at` | timestamptz | |

`crop_correction_undo(correction_id PK/FK, undone_at)`. Current correction per `crop_id` =
latest without undo. Independent of video reviews (spec FR-009).

## Contact sheet (derived, cached file)

Cache file `<cache>/sheets/<content_sha256>-<settings_fingerprint>-12-v1.jpg`. Layout
(returned as JSON): `columns`, `tile_width`, `tile_height`, `tiles[]` of
`{index, frame_number, elapsed_seconds, boxes[{left, top, right, bottom, confidence,
category, qualifies}]}` with normalized box coordinates. At most 12 tiles, evenly spaced over
the video's sampled frames.

## Playback copy (derived, cached file)

`<cache>/playback/<content_sha256>-v1.mp4` (H.264, no audio, `+faststart`). Status is derived
from file presence, a `.failed` marker with a short reason, and the worker queue. Directly
playable sources are streamed without a copy.

## Session (in memory)

| Field | Rules |
|---|---|
| token | 256-bit random, only the SHA-256 digest is held in memory |
| `created_at`, `last_seen` | idle expiry 12 h; cleared on restart or `DELETE /v1/session` |

No user, role or account entity exists.

## Frontend state model

`processing status` (video status), `playback status`, `review status` (`unreviewed |
confirmed | corrected`) are carried per video so later phases only add fields. Filters live in
URL search params: `status`, `review`, `folder`, `from`, `to`, `sort`, `order`, `page`.
