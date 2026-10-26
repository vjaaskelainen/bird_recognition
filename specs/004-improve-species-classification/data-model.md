# Data Model: Improve Wildlife Species Classification

**Date**: 2026-10-25 | **Related**: [spec.md](spec.md), [research.md](research.md), [contracts/cli.md](contracts/cli.md)

## Identity and lifecycle

- Preserve the existing `bird_embed` schema and add forward-only migrations. Never rewrite or delete old decisions, runs, or ingestion crop files.
- Canonical JSON uses UTF-8, sorted keys, compact separators, finite numbers only, and SHA-256 identity. Store canonical content beside its digest when it is needed to explain a result.
- Each decision-affecting input contributes to an immutable setup identity: model/checkpoint/runtime, candidate content and types, prompt version, crop-generation and model-input preparation, quality minimums, threshold, score margin, optional reference set/match criteria, and optional aggregation rule.
- Crop/vector/decision records retain crop ID, source/video ID, frame/time, lighting, content/provenance digests, and relevant setup fingerprints. Run and report time is not capture time.
- Private source paths, labels, references, embeddings, and report files remain on local storage. Reports are written outside Git; no image, label, or report upload is allowed.

## 1. Candidate and candidate set

Candidate entry fields:

| Field | Type / rule |
|---|---|
| `id` | For a species, stable canonical taxon ID used by labels; for a broad category, stable owner-defined ID. Unique after trim/casefold; never `unknown`. |
| `kind` | `species` or `category`. |
| `common_name` | Required nonblank display name. |
| `taxonomic_description` | Required nonblank classification description; for species includes accepted taxon/scientific name and optional owner-verified synonyms; for category identifies broad bird/mammal scope. |
| `category` | Required for `kind=category`; `bird` or `mammal`; prohibited for species. |

The species-file document has an explicit schema version and a nonempty candidate array. Reject unknown fields, duplicate JSON keys, duplicate IDs/names and unsupported kinds. Schema 2 requires exactly one broad `bird` and one broad `mammal` category candidate; category candidates are not species IDs. No external taxonomy service resolves or validates owner-provided taxonomy.

Candidate-set fingerprint includes every normalized candidate field and stable ordering. Schema-2 prompt text is exactly `a photo of {common_name} ({taxonomic_description}).`; prompt template/version and candidate fingerprint are included in scoring/setup identity. Legacy schema-1 `{id, name}` remains the exact historical `a photo of {name}.` path and fingerprint. Changing candidate text or prompt creates a distinct setup and new score map, while compatible image representations may be reused.

When a minimum margin is enabled, require at least two candidates; reject a one-candidate setup rather than treating its always-1.0 score as a clear lead. For `n >= 2`, margin is `top_score - second_score` on the persisted candidate-relative softmax map.

## 2. Crop input and image preparation

### Ingestion crop identity

Ingestion settings add a finite context/expansion fraction and a crop-policy version. Convert detector coordinates to an integer pixel box, expand proportionally on each axis, clip to `[0, frame_width] × [0, frame_height]`, and preserve the expanded rectangle's aspect ratio. The detector box remains separately recorded in detection provenance; the crop bounds identify the actual published image region. New settings alter the existing canonical settings fingerprint and therefore produce distinct output directories, crop IDs, and manifest rows. Old crop files and rows are immutable.

Compute a separate `case_id` from the source-content digest, frame number, detection ID, and original normalized detector box in canonical form; exclude crop settings, crop bytes/path, and run IDs. The case ID permits paired evaluation of crop-policy variants for the same unchanged detection, but changed content or detection geometry necessarily creates a different case ID. Preserve the case ID on every snapshot, run item, review export, label and report mapping.

Minimum usable crop width, height, and/or area are explicit versioned quality settings. A crop that fails any configured minimum yields `low_quality` rather than a reliable species/category assignment. Keep the raw candidate score map when computed for inspection, but do not count a low-quality input as an assigned class. The report separately counts low-quality outcomes from model uncertainty and processing failure.

### Model input view

The classification input transform is versioned and fingerprinted separately from generated crop identity. For rectangular crops, resize the full image to fit the model's square input and pad unused area without center-cropping, preserving all available crop pixels and edge detail. Do not stretch/distort the image. The current baseline transform remains identifiable and reproducible. Image representation identity must include both model/checkpoint identity and model-input preparation fingerprint; a change cannot reuse an incompatible vector.

## 3. Classification setup and crop-level decision

A setup is immutable canonical JSON with fingerprint and references to:

- Model identity: upstream/model adapter, immutable revision and checkpoint/config/tokenizer digests, runtime and model preprocessing contract.
- Candidate-set and prompt fingerprints.
- Crop-generation identity from the source manifest and model input-view version.
- Score threshold in `[0,1]`, optional minimum top-two score margin in `[0,1]`, and minimum crop-quality dimensions/area.
- Optional reference-set fingerprint and matching criteria.
- Optional visit aggregation algorithm/version.

A crop-level decision stores the full ordered candidate logits/scores when inference ran, assigned candidate (nullable), best unique candidate (nullable on exact tie), tied candidate IDs, threshold, margin, reason, decision path, processing time, warnings, crop/source/frame/lighting provenance, and setup fingerprint. Decision reasons include `assigned`, `below_threshold`, `below_margin`, `exact_tie`, `low_quality`, and existing operational failure states. A `low_quality` decision is completed but has no assignment, no best candidate, null confidence, and an empty score map; it is distinct from inference failure and unidentifiable truth. `below_threshold` and `below_margin` are independent; exact ties remain inspectable and unassigned. A `species` candidate assignment is species-level; a `category` assignment is explicitly coarse and cannot count as exact species correctness. Scores are candidate-relative, never calibrated biological probabilities.

Representations and decisions are append-only. Use a representation key derived from crop snapshot, model fingerprint, and input-view fingerprint. Threshold-only or margin-only redecisions may reuse compatible candidate score maps; changed candidate/prompt content recomputes text scores; changed image/model-input view requires a new image representation.

## 4. Reviewed label set and quality comparison

### Reviewed label set

External versioned label JSON is independent of run/configuration. Its metadata records `label_role` (`tuning` or `held_out_evaluation`), `split_mode` (`source_video` or `recording_day`), sorted nonempty `source_split_keys`, and their canonical SHA-256 digest. Each unique crop entry has an owner-reviewed truth kind:

- `species`: stable known taxon ID and optional common/taxonomic text, regardless of whether a compared setup contains that candidate.
- `out_of_list`: animal cannot be identified within the owner-maintained review taxonomy; preserve an external taxon/category ID when known. Whether a known `species` truth is missing from a particular setup is a per-setup outcome, not a property of the blind label.
- `unidentifiable`: an animal present but not identifiable to species from the crop.
- `unusable`: crop is not an evaluable animal example (e.g. unusable image). Exclude from biological accuracy denominators and report separately.

Entries may include `expected_category` (`bird`, `mammal`, or null) when a reviewer can identify that coarse group. This supports coarse-category evaluation without changing species truth. Unknown category remains null and is excluded from category correctness denominators. Required entry fields are `case_id`, `reviewed_crop_id`, `truth_kind`, and `expected_taxon_id`; `species` requires a stable taxon ID, while `unidentifiable` and `unusable` require null. Notes are optional and privacy-reviewed.

Each reviewed entry carries a stable `case_id` derived from source-content identity, frame number, detection identity, and original detector-box coordinates, plus the actual `reviewed_crop_id`. The case key excludes crop-preparation settings so the same biological event can be paired across crop-policy outputs; it does not equate changed detections or changed source content. If case matching is missing, ambiguous, or maps multiple crops in a setup, exclude it from paired metrics and report the reason. Label-set fingerprint hashes canonical labels and reviewed sample metadata. Tuning and held-out sets must have disjoint source-video/day split keys; held-out labels are never used to select or tune the compared setup. Reports disclose the label role/split hash, paired and unpaired counts, use crop IDs specific to each setup, and compare only one-to-one shared case IDs for paired changes. A `tuning` label set cannot support a publication-quality claim.

### Quality comparison report

External atomic JSON report contains report/version/time, label-set fingerprint, selected run/setup identities, exact paired sample definition, and per-setup counts and outcomes grouped by `day`, `night`, and `unknown`. For each group report labeled/eligible/completed/failed/unusable counts, exact species correct/incorrect, known species absent from the candidate set, coarse category matches (including broad-category handling of those known species), global out-of-list outcomes, unidentifiable outcomes, low-quality decisions, unknown/unassigned reasons, assignment coverage, processing coverage, and observed per-crop errors. Include paired changes in correct species assignment, category outcome, unassigned state, and coverage.

Define `species_assignment_coverage = species-assigned decisions / completed eligible animal decisions` and `any_assignment_coverage = (species-assigned + category-assigned) / completed eligible animal decisions`; processing coverage is completed eligible decisions / eligible reviewed cases. Species precision is exact species-correct / species-assigned and excludes category outcomes from both numerator and denominator. Report category-level matches separately against optional `expected_category`; never count these as species-correct. An assigned species for an out-of-list or unidentifiable truth is a species-level error.

Undefined denominators are `null`, never zero-derived perfection. A group is insufficient for publication-ready sample claims unless it contains at least 10 reviewed day and 10 reviewed night labels and at least 10 completed decisions in each group; report label and completion counts separately. This is a sample-size gate only and makes no accuracy guarantee. State that unfamiliar species may score highly and day/night results may differ. Model benchmarks additionally report wall-clock elapsed time and bounded sample size.

## 5. Reference example set and decision path

An external reference manifest has a schema version, set ID/fingerprint, candidate taxon IDs, crop IDs, source-video IDs and/or known capture-day keys, label-review provenance, compatible model and crop-input fingerprints, and local crop locators. Derive embeddings locally and retain the exact reference-set fingerprint and embedding identity used by a run.

Before evaluation, select and record one split mode: `source_video` (default; reference and evaluation source-video IDs are disjoint) or `recording_day` (all capture-day keys must be known and disjoint). Reject the reference path if the selected split cannot be verified; never silently weaken the split. Matching criteria contain finite configured minimum similarity, minimum same-label agreement/consistency, and version; they are not asserted as calibrated probabilities. A qualifying consistent reference match may suggest its species. Otherwise emit the baseline zero-shot decision with path `zero_shot_fallback`. Every outcome records `reference_match` or `zero_shot_fallback`, split mode, reference-set fingerprint, and matching criteria. The default setup has no references and uses the unchanged zero-shot path.

## 6. Visit grouping and visit-level decision

An external versioned grouping manifest identifies one source video and at least two crop IDs per owner-reviewed/confident visit. A crop occurs at most once in a manifest; all members must be from the declared source and compatible setup/candidate/model/input versions. No grouping is inferred from same-video membership alone. Uncertain groups are rejected or omitted, never aggregated.

A visit decision is a derived, separate record/report with visit ID, source video, aggregation rule/version, contributing crop IDs and decision IDs, candidate score aggregation, result/reason, and setup identity. Use deterministic arithmetic mean of compatible member candidate logits before applying the configured threshold and margin. Keep all crop decisions intact. Visit-level metrics are reported separately and do not inflate crop-level sample counts.

## 7. Persistence and migration considerations

- Add schema migrations for candidate kinds/descriptions, prompt/setup identities, input-view/representation identity, extended reasons and optional reference/decision-path provenance. Preserve existing tables/rows and support reading historical schema-1 runs as legacy setup version 1.
- Add uniqueness and foreign-key constraints to prevent a result from referring to a candidate/configuration incompatible with its score map or representation. Validate finite scores, stable IDs, score normalization, thresholds, margins, and references in both pure logic and storage boundaries.
- Preserve existing run status/count/recovery invariants: `low_quality` is a completed assessment outcome, not an operational failed item, and contributes to the existing `unknown_count`/unassigned total while retaining a distinct decision reason and dedicated report count. New inspection/evaluation separates low-quality from threshold/margin/tie unknowns. Inspection/evaluation must not load current model assets or mutable species files.
- Shared label sets, quality comparisons, reference embeddings, and visit reports may remain external versioned files/derived artifacts; do not persist human labels or private report contents in the database unless a future privacy-reviewed requirement calls for it.














