# CLI Contract: Species Classification Quality and Optional Decision Paths

**Status**: Implemented local CLI extensions for classification quality and optional decision paths. Existing `ingest`, `index`, `inspect`, `evaluate-species`, blind crop-review, and review-CSV conversion remain available for historical runs. Interface implementation does not establish biological quality or completion of private-data acceptance checks; record measured evidence separately.

## Common behavior

- Run locally from repository root in PowerShell using `.\.venv\Scripts\uv.exe run bird-recognition <command> ...`. Use the repository's existing virtual environment; if `.venv` is absent, stop and ask the developer. Do not activate it.
- Commands requiring model inference use only validated, externally provisioned local assets; no download/network fallback. Pure comparison, inspection, score-margin, reference matching, and visit aggregation logic must be testable with fakes and without a live model.
- JSON output uses explicit schema versions and stable IDs. Diagnostics go to stderr; machine-readable JSON output contains no progress logs, secrets, database URLs, or raw private image paths.
- Labels, review exports, reference manifests/embeddings, and generated reports must be outside all Git repositories. Refuse unsafe destinations and accidental overwrite. Source videos/crops are never uploaded or committed.
- Relative candidate scores and reference similarity are not calibrated probabilities of biological correctness. Reports explicitly note out-of-list risk and possible day/night differences.

## Ingestion crop preparation

`ingest` uses versioned crop preparation settings:

| Option | Meaning |
|---|---|
| `--crop-context FRACTION` | Nonnegative finite proportional expansion on each side of the detector box, clipped to frame bounds; defaults to 0.10 with `context-v1` and 0 with `legacy-tight-v1`. |
| `--crop-policy VERSION` | Crop generation policy; defaults to `context-v1`. Use `legacy-tight-v1` for tight crops. |

The effective options are part of canonical ingestion settings identity. Changed settings create distinct crop/run identities and paths; they never overwrite previous crop outputs. Preserve the rectangle (do not force square crops). Existing crop policy remains explicitly selectable as the historical baseline.

## Candidate file schema

Candidate file is strict UTF-8 JSON with no duplicate object keys or unknown fields. Schema version is explicit; entry ordering does not change identity.

```json
{
  "schema_version": 2,
  "candidates": [
    {
      "id": "great_tit",
      "kind": "species",
      "common_name": "Great tit",
      "taxonomic_description": "Parus major; owner-verified local taxon"
    },
    {
      "id": "broad_bird",
      "kind": "category",
      "category": "bird",
      "common_name": "Bird",
      "taxonomic_description": "A bird that cannot be identified to a listed species"
    },
    {
      "id": "broad_mammal",
      "kind": "category",
      "category": "mammal",
      "common_name": "Mammal",
      "taxonomic_description": "A mammal that cannot be identified to a listed species"
    }
  ]
}
```

Species candidates require stable taxon ID, common name, and taxonomic description. Schema 2 requires exactly one typed broad bird and one broad mammal candidate; they are not species. Candidate and prompt versions are retained on every run. Legacy schema-1 species files remain readable as historical baseline inputs; they are not silently rewritten.

## `index`

Existing options remain; add:

| Option | Meaning |
|---|---|
| `--minimum-margin NUMBER` | Optional finite minimum difference between the top two candidate-relative scores in `[0,1]`; applies in addition to the existing `--threshold`. |
| `--minimum-crop-width PIXELS` / `--minimum-crop-height PIXELS` | Positive usable-size minima; default 32 pixels each for new setups. A crop failing either is `low_quality`, not a reliable species/category assignment. Historical baseline runs retain their saved prior behavior. |
| `--input-view VERSION` | Versioned model-input preparation; defaults to `fit-pad-v1` for new setups, retaining elongated crop edges, and is included in representation/setup identity. `legacy-center-crop-v1` is available for controlled historical comparisons. |
| `--reference-set PATH` | Opt-in local reviewed reference manifest; absent means unchanged general-purpose zero-shot path. |
| `--reference-min-similarity NUMBER` | Required with reference set; finite `[0,1]`, setup value, not probability. |
| `--reference-min-agreement FRACTION` | Required with reference set; finite `[0,1]`, minimum consistent same-label neighbor fraction. |
| `--json` | Versioned run summary including setup/candidate/prompt/crop-input identities and decision path counts. |

Threshold remains independent and mandatory/defaulted as today. Ties, below-threshold, and below-margin outcomes remain unassigned with all competing candidates and reason visible. A broad category assignment is explicitly `category`; it is never represented as a species ID. The selected model is never silently replaced.

## Existing blind review and CSV conversion workflow

Use and minimally extend `tools/review_csv.py` and `tools/review_crops.py`; do not recreate or replace their workflow, expose predictions during blind review, or change the local-only/browser-on-loopback behavior. Preserve the existing CSV review fields and autosave behavior. Make displayed lighting read-only source metadata (not a reviewer label). Add repeated `--source-id ID` filtering and deterministic `--per-lighting N` sample selection to the existing CSV creator; the options are mutually exclusive with `--limit`, and `N` is capped at 500 per lighting group. This allows distinct tuning and held-out cohorts to be selected by source video. Report shortfalls when a group contains fewer than N crops. Extend the converter to export a candidate-independent shared label-set version keyed by a stable `case_id` and `reviewed_crop_id`, rather than a single run ID/crop ID. `case_id` is derived from source-content identity, frame, detection identity, and original detector-box coordinates; it is stable across crop-context policies but cannot match changed/ambiguous detections. The converter requires `--label-role` and `--split-mode` to create a shared label set, calculates the split-key digest from hidden source metadata in the review CSV, and rejects an unknown recording day for `recording_day` mode. The review vocabulary is a stable owner-maintained taxonomy list (not the classifier's active candidates), so a reviewed species can be recorded even when it is absent from a compared candidate set. Include distinct `species`, `out_of_list`, `unidentifiable`, and `unusable` choices; retain current `not-in-list` and `unknown` compatibility mappings. Label-set hash and cohort selection are recorded by evaluation.

`review_crops.py --species PATH` accepts the existing candidate file for legacy review and a strict external taxonomy file for shared labels:

```json
{
  "schema_version": 1,
  "taxa": [
    {"id": "parus_major", "common_name": "Great tit", "category": "bird"}
  ]
}
```

The review list is not automatically copied from or restricted to the classifier candidate set. It contains species-level choices only; category truth is captured in a separate optional `expected_category` field. Out-of-list, unidentifiable, and unusable are distinct review options.

Shared label-set schema (UTF-8 JSON; no duplicate keys; external to Git):

```json
{
  "schema_version": 2,
  "label_role": "held_out_evaluation",
  "split_mode": "source_video",
  "source_split_keys": ["source-video-content-id-1"],
  "source_split_sha256": "sha256-of-sorted-source-video-or-day-split-keys",
  "examples": [
    {
      "case_id": "stable-source-frame-detection-digest",
      "reviewed_crop_id": "crop-from-the-blind-review-run",
      "truth_kind": "species",
      "expected_taxon_id": "parus_major",
      "expected_category": "bird",
      "notes": "Owner-reviewed"
    }
  ]
}
```

`label_role` is `tuning` or `held_out_evaluation`; `split_mode` is `source_video` or `recording_day`; `source_split_keys` is a sorted, unique, nonempty list of source IDs or known day keys, and `source_split_sha256` hashes its canonical form. Tuning and held-out roles must use disjoint split keys under the same mode. `case_id` and `reviewed_crop_id` are nonblank; `case_id` is unique. `species` requires a nonblank stable taxon ID; `out_of_list` may carry a known external taxon ID or null; `unidentifiable` and `unusable` require null. `expected_category` is optional `bird`, `mammal`, or null, independent of species truth. No label is constrained by a compared setup's candidate IDs. Lighting is resolved from each run's persisted provenance.

## `evaluate-species`

Keep existing schema-1 labels and reports readable. Extend the command to accept schema-2 shared labels and evaluate exactly one explicit `--run-id` against them using one-to-one `case_id` matching. Output records label-set role/hash, run/setup fingerprints, group counts and metrics, category versus species outcomes, setup-specific matched crop IDs, unmatched/ambiguous cases, low-quality outcomes, and sample limitations. A held-out label role with disjoint source split is required for publication-quality claims. Existing external output-path, atomic-write, privacy, and no-overwrite rules continue to apply.

## `compare-species`

Options: required `--labels PATH`, at least two `--run-id UUID` values, `--output PATH`; database configuration follows existing command precedence. Optional `--json` for stdout. The report is written atomically to an explicit external path and refuses overwrite/Git-contained destinations.

Pair runs by one-to-one `case_id` mappings and use the setup-specific crop ID for each decision. Output records each run/setup fingerprint, label-set hash, paired/eligible/unpaired/ambiguous counts, and per-setup `day`, `night`, `unknown` groups. Report exact species correct/incorrect assignments, broad-category matches, out-of-list and unidentifiable handling, unusable/low-quality/failed/unassigned reasons, species-assignment coverage, any-candidate assignment coverage, processing coverage, and paired changes. Do not count broad-category matches as correct species or in the species-precision denominator. Identify groups below 10 completed reviewed day/night examples as insufficient for publication-ready sample claims; this gate is not an accuracy claim.

## `benchmark-species`

Options: required `--run-id UUID`, `--labels PATH`, `--model-dir PATH`, `--output PATH`, and positive `--max-crops N` no greater than 500. The selected run supplies the candidate/prompt/threshold context; labels must be `held_out_evaluation`. `--model-adapter` currently accepts only `bioclip`; `--input-view` may explicitly select a supported local BioCLIP input view and otherwise reproduces the selected run's view. The deterministic hash-ranked cohort is capped before inference. Never alter the active/default model. Record selected sample/crop IDs, label-set identity, baseline and benchmark model/setup fingerprints, measured quality outcomes, elapsed time, and unsupported/unavailable configurations. No network model lookup or automatic selection.

## `aggregate-visits`

Options: required `--run-id UUID`, external `--groups PATH`, `--output PATH`; optional `--json`. Group manifest is versioned, names source-video IDs and at least two crop IDs per group, and asserts a confident owner-reviewed visit association. No group is inferred merely from video membership. Reject cross-video or incompatible-setup groups and repeated membership. Combine compatible member logits using the specified deterministic aggregation rule, then reapply the setup threshold and minimum margin. Report visit decisions separately and link every contributing crop and crop-level decision. Crop decisions are never overwritten.

The external group file is strict UTF-8 JSON with no duplicate/unknown fields:

```json
{
  "schema_version": 1,
  "groups": [
    {
      "visit_id": "visit-1",
      "source_video_id": "source-video-1",
      "crop_ids": ["crop-1", "crop-2"],
      "association_confident": true
    }
  ]
}
```

Visit IDs must be unique; crop IDs are unique within and across groups. Each source and crop must match completed decisions in the explicitly selected run. The report retains the group-manifest fingerprint, setup identity, mean candidate logits/scores, reason, and all crop/decision links. Grouping and reports remain local and outside Git.

## Reference-set manifest and split validation

Reference manifest is external, version 1, and strict JSON with no duplicate/unknown fields. Its top-level fields are `schema_version`, `set_id`, `model_fingerprint`, `input_view_fingerprint`, `review_provenance`, and nonempty `references`. Each reference row contains `crop_id`, nullable `source_video_id`, nullable ISO `recording_day`, reviewed species ID, local `image_path`, and `image_sha256`. The model/input fingerprints must exactly match the loaded local model; image bytes are checked before encoding. The canonical set hash includes sorted records and image content digests but excludes local paths. Reference species IDs must be species candidates, never category candidates. Evaluation crop IDs and selected split keys must be disjoint; default split mode is `source_video`. If source-video identity is unavailable, the owner must explicitly choose `recording_day` and all days must be known and disjoint; otherwise fail closed. Compare cosine similarity to the top five reference examples, retain references meeting `--reference-min-similarity`, and require at least three retained references plus a most-common species fraction meeting `--reference-min-agreement`; otherwise use the general zero-shot decision and record `zero_shot_fallback`. Accepted reference suggestions record `reference_match`. Every result includes decision path, reference-set fingerprint, split mode, similarity/agreement where measurable, and retained neighbor crop IDs. Reference files and images must be outside Git.

Example manifest shape (values and paths are illustrative):

```json
{
  "schema_version": 1,
  "set_id": "camera-a-reviewed-v1",
  "model_fingerprint": "64-character-model-sha256",
  "input_view_fingerprint": "64-character-input-view-sha256",
  "review_provenance": "owner-reviewed-held-out-references",
  "references": [
    {
      "crop_id": "reference-crop-1",
      "source_video_id": "reference-source-1",
      "recording_day": "2025-03-14",
      "species_id": "parus_major",
      "image_path": "reference-crops/crop-1.png",
      "image_sha256": "64-character-image-sha256"
    }
  ]
}
```

## Report privacy and interpretation

Quality, benchmark, and visit reports are external UTF-8 JSON files with schema version and exact input/setup identities. No report is automatically committed or written within the repository. Empty groups or zero metric denominators are `null`/unavailable; never present them as perfect. Insufficient reviewed counts are explicit. Synthetic tests prove code-path correctness only; biological quality claims require reviewed real examples not used to tune the evaluated setup.


















