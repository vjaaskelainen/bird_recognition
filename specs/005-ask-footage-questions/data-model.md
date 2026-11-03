# Data Model: Ask Questions About Footage

**Date**: 2026-11-03 | **Related**: [spec.md](spec.md), [research.md](research.md)

Ask adds transient request, evidence, generator-response, and outcome records.
Existing PostgreSQL rows and stored representations remain authoritative; no
schema migration, answer history, or durable Ask record is introduced.

## Identity and evidence rules

- One explicit indexed `run_id` selects the collection and its exact model/tagging
  context through the existing search contract.
- Search results are the only evidence candidates. Filters apply before the
  positive evidence limit; the default limit is 5.
- Each supplied evidence index is assigned by the application from the stable,
  deterministic result order. It maps to one retrieved `crop_id`, selected
  `decision_id`, `snapshot_id`, representation, and source/frame provenance.
- An evidence index is valid only for the current request and only when it was
  included in the exact request sent to the answer service.
- Similarity, species decision/confidence, and detection confidence are distinct
  metadata values, not proof of identity or occurrence.
- An unavailable crop retains provenance and is marked unavailable. Its
  metadata may be supplied, but no image bytes are transmitted for it; output
  distinguishes metadata-only evidence from a visually supplied crop.
- Request and response values are transient. Source footage, crops, manifests,
  vectors, and species decisions are never modified.

## 1. AskRequest

One validated, single-turn request.

| Field | Type / rule |
|---|---|
| question | Required nonblank natural-language string |
| run_id | Required UUID selecting one complete or valid empty indexed run |
| start_date, end_date | Optional strict `YYYY-MM-DD` inclusive bounds; start cannot exceed end |
| lighting | Optional exact `day` or `night` value |
| species_id | Optional selected-context candidate ID or reserved `unknown` |
| evidence_limit | Positive whole-number maximum; default 5 |
| database_url, model_dir | Existing required local database and BioCLIP settings for search |
| answer_api_key | Required secret resolved only from `BIRD_RECOGNITION_ASK_API_KEY` in process environment or local `.env`; never displayed |
| answer_model | Configured model; default `gpt-4o-mini`, optionally overridden by `BIRD_RECOGNITION_ASK_MODEL` |
| output_format | Human-readable or versioned JSON; does not change semantics |

Question text does not create metadata filters. Empty retrieval is a successful
insufficient-evidence outcome and does not invoke the answer service.

## 2. EvidenceItem

One request-scoped item derived from an existing `SearchResult`.

| Field | Source / rule |
|---|---|
| evidence_index | Zero-based application-assigned index in deterministic selected order |
| crop_id, snapshot_id, representation_id, decision_id | Stable selected search-result identities |
| source_id, source_video | Search provenance for the source |
| frame_number, elapsed_seconds | Source-frame identity and elapsed media time |
| capture_time, capture_timezone | Recorded values when known; otherwise explicitly unknown/null |
| lighting | Stored day/night/unknown value |
| species_id, species_confidence | Stored assigned decision; nullable/unassigned is unknown, and confidence is not biological probability |
| detection_confidence | Stored detector value, distinct from similarity and species confidence |
| similarity | Search retrieval relevance score, not a probability |
| image_status | `available` or `unavailable`; preserves search result position/provenance |
| image_bytes | Read-only crop bytes only when available; transient and sent only for this selected item |

No full source video or unselected crop is opened or transmitted. Metadata supplied
to the answer service is limited to these selected evidence items.

## 3. GeneratedClaim and Citation

| Field | Type / rule |
|---|---|
| text | Nonblank generated claim text |
| evidence_indices | One or more integer references from the request-local selected evidence set |
| citation | Application-resolved reference to the corresponding `EvidenceItem`; includes crop, source video, frame, and known capture time |

The answer service cannot authoritatively define crop/source identifiers. The
application maps valid indices to retrieved records. An out-of-range index is
invalid; it is never displayed as supporting evidence. A claim with no valid
citation is not presented as supported.

## 4. AskOutcome

One discriminated transient result.

| Outcome | Payload and handling |
|---|---|
| supported | Answer claims with at least one valid evidence citation each, all selected evidence/provenance, applied filters, selected context, and transmission notice |
| insufficient evidence | Clear decline reason; optionally include retrieved evidence labeled as retrieved but not supporting an answer; no fabricated citation |
| input error | Actionable invalid question/filter/limit or missing required setting; no external request |
| operational failure | Actionable sanitized API, storage, model, timeout, incomplete, refusal, or malformed-response error; never presented as an answer or decline |

Supported and insufficient outcomes are successful command outcomes. CLI exit
codes and machine-readable fields are specified in
[contracts/cli.md](contracts/cli.md).
