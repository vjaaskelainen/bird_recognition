# Data Model: Text Search over Wildlife Crops

**Date**: 2026-10-25 | **Related**: [spec.md](spec.md), [research.md](research.md), [CLI contract](contracts/cli.md)

Search introduces transient request/context/result records only. Existing PostgreSQL
rows remain authoritative; no database migration or durable search history is required.

## Identity and score conventions

- A selected `processing_run.run_id` identifies the search collection. Its run items
  define the selected crop IDs and its config fingerprint identifies the tagging
  context. Search does not combine rows from separate runs.
- `snapshot_id` identifies the immutable crop/provenance record; `crop_id` is the
  stable ingestion identity; `representation_id` identifies the compatible stored
  image vector; `decision_id` and `config_fingerprint` identify the selected species
  decision and tagging context.
- Query and image vectors must each be 512-dimensional, finite, nonzero, and
  L2-normalized within `1e-5`. Compute cosine using float64-accumulated dot product
  divided by both measured norms; clamp only floating-point drift to `[-1, 1]`.
  Similarity must be finite, and higher is more similar. It is a relative retrieval
  score, not a probability.
- Sort by score descending and `crop_id` ascending for equal scores. Validate the
  query vector and every eligible score before applying the requested top-N limit;
  malformed numeric data fails the search instead of returning a misleadingly
  shorter list.

## 1. SearchRequest

One validated, transient user request.

| Field | Type / rule |
|---|---|
| query | Required string; trimmed only for blank validation; the supplied text is embedded as one query and does not imply metadata filters |
| run_id | Required UUID selecting one indexed collection and its context |
| start_date, end_date | Optional calendar dates parsed strictly as `YYYY-MM-DD`; each is inclusive, independently optional; start must not exceed end |
| lighting | Optional enum `day` or `night`; omitted means no lighting restriction; `unknown` is not a selectable lighting filter |
| species_id | Optional stable ID in selected candidate set or reserved lowercase `unknown`; null assignment matches `unknown`, best candidate does not |
| limit | Positive whole-number maximum, default 5; booleans/fractions/zero/negative values invalid |
| database_url, model_dir | Required local DB/model configuration resolved through explicit CLI > process environment > discovered `.env`; no built-in credential or asset path |
| json | Output format flag; no effect on search semantics |

A date predicate compares the date portion of the recorded ISO-8601 capture value.
Timezone text is preserved and never used to convert the value to another date or
an absolute instant. A date filter rejects missing/malformed capture times. With no
date filter, unknown capture time remains eligible and is reported as unknown.

## 2. SearchContext / SearchCollection

Resolved from persisted rows before ranking; one context is mandatory.

| Field | Source / rule |
|---|---|
| run_id | Selected `processing_run`; must exist and have `complete` or `no_input` status |
| model_fingerprint | `tagging_config.model_fingerprint`; must equal the fingerprint from the locally loaded BioCLIP assets/runtime |
| config_fingerprint | The run's exact `tagging_config`; never select a newer config or attach another config's decision |
| candidate_set_fingerprint | `tagging_config.candidate_set_fingerprint`; defines valid species IDs; `unknown` is reserved and is not in candidates |
| candidate IDs/names | Persisted `candidate_set.candidates_json`, used for filter validation and display |
| selected crop IDs | `run_item` rows in this run that are completed/skipped and reference the decision/config and compatible representation/snapshot; failed/pending items are not indexed matches |

A failed, interrupted, partial-failure, missing, or representation-incompatible run
is an operational/selection error, not a successful empty collection. A valid
`no_input` run is an empty collection and returns zero results after prerequisites
and context compatibility are checked.

## 3. SearchResult

One candidate crop match after full filtering and exact scoring.

| Field | Source / rule |
|---|---|
| rank | One-based position after deterministic sorting and limit |
| similarity | Finite cosine similarity in `[-1, 1]`; distinct from other confidences |
| crop_id, snapshot_id | Stable ingestion and immutable snapshot identities |
| representation_id | UUID of the exact model-compatible stored crop representation |
| decision_id, assigned_species_id, species_confidence | Decision under selected config; null assignment is emitted as `unknown`; species confidence retains candidate-relative caveat |
| crop_path, image_status | Selected run item's local input locator and explicit `available`/`unavailable` status; check is read-only and does not affect ranking |
| source_id, source_video | Stable source identity, basename and original source reference |
| frame_number, elapsed_seconds | Source frame index and elapsed video seconds |
| capture_time, capture_timezone | Recorded ISO-8601 local capture timestamp and original timezone, or explicit unknown/null |
| lighting | Stored `day`, `night`, or `unknown` value |
| detection_id, detection_category | Persisted animal-detection provenance |
| detection_confidence | Persisted detector confidence, distinct from similarity and species confidence |
| detection_box_normalized, crop_box_pixels | Stored normalized detection box and crop pixel rectangle |
| frame_width, frame_height | Original frame dimensions, supporting box inspection |

The row is returned even if its local crop file has moved or is unreadable. Search
must not decode or re-embed the image and must not substitute another image. Missing
metadata remains explicit null/unknown; identity and provenance come from storage.

## 4. SearchOutcome and failure categories

A successful outcome includes query, applied filters (including omitted/null values),
requested limit, returned count, selected run/model/config/candidate-set identities,
ordered results, and score/interpretation guidance. A valid empty collection or
zero-match filter is a successful outcome with count zero.

Failures are distinguishable from empty success:

- **Input/selection failure**: blank query; invalid date/range/lighting/limit/species
  ID; unknown, incomplete, ambiguous, or incompatible selected context. No results.
- **Operational failure**: database/schema/model assets unavailable; incompatible
  representation collection; invalid/non-finite query or stored numeric value;
  scoring/storage failure. Do not emit partial matches or imply success.
- **Success**: nonempty ordered results or an explicit zero-result outcome.

CLI exit codes and JSON envelopes are defined in [contracts/cli.md](contracts/cli.md).


