# Research: Improve Wildlife Species Classification

**Date**: 2026-10-25 | **Branch**: `004-improve-species-classification`

## Existing project findings

- The default classifier is local CPU BioCLIP ViT-B/16. `embed/bioclip.py` strictly validates externally provisioned assets and exposes image/text encoding; `embed/pipeline.py` indexes manifest crops, persists image vectors and full candidate score maps, and reuses compatible results. There is no network/model download fallback.
- `embed/config.py` currently accepts candidate `{id, name}` entries and constructs the fixed prompt `a photo of {name}.`; canonical content and SHA-256 fingerprints already version model, candidate, scoring/prompt and threshold settings. Candidate arrays and labels are currently constrained to the exact candidate list selected for one run.
- `embed/scoring.py` applies a candidate-relative softmax and threshold, preserves exact ties/competing scores, and warns that scores are not calibrated probabilities. It has no minimum top-two margin. Existing persistence uses immutable `bird_embed` records and forward-only packaged SQL migrations.
- `embed/evaluation.py` reads persisted results only, groups day/night/unknown from ingestion provenance, and emits an external atomic report. Existing label schema is bound to one run and selected candidate IDs; current truth kinds are species, out-of-list, and unidentifiable. Its publication sample gate requires ten completed day and ten completed night examples.
- `ingest/crops.py` clips detector boxes to the source frame and saves the tight, unpadded rectangle. `ingest/pipeline.py` uses the crop as both published input and classification input. `IngestSettings` and `settings_identity()` fingerprint ingestion settings, so a crop policy change can naturally create a distinct set of files and manifest identities. Existing crops are not overwritten.
- CLI is the supported interface. The review-crops and CSV conversion utilities already exist and are prerequisites; this plan consumes their exported labels and does not recreate their UI or conversion behavior. SQLite manifests preserve source, frame, detection, crop, lighting, and settings provenance.

## Decisions

### D1. Reusable label cohort and paired comparisons

**Decision**: Introduce a versioned label-set format whose identity is independent of a classification run and candidate set. Extend the existing blind review CSV converter (not its UI/workflow) to export stable species/taxon IDs and explicit label kinds (`species`, `out_of_list`, `unidentifiable`, `unusable`). Separate discovery/tuning labels from the locked held-out comparison labels by source video (or known recording day); never use the held-out set to choose or tune either compared setup. Pair crop-policy versions by a deterministic `case_id` based on source content, frame, detection ID, and original detector box, while retaining each setup's actual crop ID. Lighting remains copied from source metadata and is not inferred. Reports state paired, unmatched, ambiguous, and failed items per setup, with per-lighting species-level correctness, coarse-category outcomes, coverage, and paired outcome changes. Keep existing single-run evaluation compatible or version it without discarding old reports.

**Rationale**: Current labels bind to one run and validate species truth against that run's candidates, preventing fair comparisons when a candidate list changes. Candidate-independent labels are necessary for paired baseline/change measurement and allow a known local species to be out-of-list for an earlier setup.

**Alternatives considered**: Re-export labels separately per run (risks label drift and leaks candidate identities into the blind review); mutate old labels to fit each setup (destroys reproducibility); replace existing review tooling (duplicates a working prerequisite). Rejected.

### D2. Candidate taxonomy and prompt versioning

**Decision**: Evolve the species file to a strict versioned candidate schema with `id`, `kind` (`species` or `category`), `common_name`, and `taxonomic_description`; require both descriptive fields for species candidates and reserve stable broad IDs for bird/mammal categories. Schema-2 prompt is exactly `a photo of {common_name} ({taxonomic_description}).`; preserve schema-1's existing prompt exactly for historical baselines. Include type, descriptions, prompt version/template, and all candidate content in canonical candidate/scoring fingerprints. Category outputs are labeled separately and never count as species-level correct.

**Rationale**: Current schema does not distinguish common names from taxonomic names or category choices, and the current prompt only uses one name. Stable content fingerprints already provide safe historical comparison.

**Alternatives considered**: Append taxonomy ad hoc to `name`, or treat broad categories as pseudo-species. Rejected because reports could not reliably distinguish category-level from species-level decisions and validation would remain ambiguous.

### D3. Crop fidelity, context, quality, and immutability

**Decision**: Add a configurable detector-box expansion/context fraction, clipped to frame bounds, without forcing an expanded crop to square. Add a classification image preparation policy that fits the whole rectangular crop into the model's square input with padding rather than center-cropping away elongated edges. Fingerprint both policies in ingestion/crop identity and embedding configuration; retain current tight-crop behavior as an explicit historical/default baseline until measured. Add minimum pixel width/height/area quality checks and record low-quality decisions separately from classifier uncertainty. New settings produce new immutable crop outputs/manifest rows, never in-place replacement.

**Rationale**: Existing crop geometry clips correctly but saves exactly the detector box; OpenCLIP evaluation preprocessing uses a resized center crop, which can discard the ends of elongated images. Ingestion settings are already canonicalized into output identities.

**Alternatives considered**: Square-expand by cropping source context (still clips elongated details); resize non-uniformly (distorts anatomy); overwrite old crop paths (breaks checksums and comparisons). Rejected.

### D4. Optional reference assistance and split safety

**Decision**: Keep zero-shot as the default and baseline. Define an external, versioned reference-set manifest of reviewed crop IDs, source IDs/recording-day provenance, labels, model/crop-policy fingerprints, and embedding identities. Require the selected evaluation crop set to be disjoint from references by source video, or by capture day when source identity is unavailable, and validate this before inference. Use existing compatible embeddings where possible. Reference acceptance must require configurable similarity and same-species neighbor-consistency criteria; when those criteria fail, use the general zero-shot result and record `reference` versus `zero_shot_fallback` decision path. Do not present similarity as a probability.

**Rationale**: Existing model embeddings provide local, offline image representations without training. Explicit split validation prevents leakage and the fallback avoids forcing a nearest neighbor.

**Alternatives considered**: Fine-tune/train a model (prohibited by constitution); always use nearest reference (can force an unrelated class); share examples by crop-only split (leaks adjacent frames from one recording). Rejected.

### D5. Score-margin and decision provenance

**Decision**: Add an optional minimum difference between the top and second candidate's relative scores, independently of the existing threshold. An exact tie or best score below threshold remains unassigned as today; a unique best below the configured margin becomes unassigned with a distinct reason and keeps the ordered score map. Fingerprint threshold and margin separately from scoring math, preserving reusable embeddings and candidate score maps where compatible.

**Rationale**: Existing threshold behavior is stable and tests already exercise ties and thresholds; adding a second independent gate avoids conflating acceptance criteria.

**Alternatives considered**: Replace threshold with margin or combine both into an opaque confidence threshold. Rejected because each represents a different rejection case and reports need the reason.

### D6. Visit grouping and aggregation

**Decision**: Do not build animal tracking. Require an explicit local visit-group manifest that identifies a video, crop IDs, and a reviewed/confident grouping record; reject groups mixing source videos, configurations, candidate sets, or incompatible crop policies. For compatible group members, combine candidate logits using a deterministic arithmetic mean, then apply the same threshold and margin. Persist/report the visit decision separately with every member crop/decision linked; retain all crop-level decisions unchanged. Uncertain or absent grouping means no aggregation.

**Rationale**: Ingestion samples sequential video frames but does not track individuals; video membership alone does not prove the same animal/visit. A caller-supplied, auditable grouping is the smallest safe boundary.

**Alternatives considered**: Automatically group all nearby timestamps in a video (may merge different animals); install a general animal tracker (outside scope and larger dependency). Rejected.

### D7. Bounded model benchmarks and local operation

**Decision**: Make benchmark runs explicit and bounded, retain the selected/default model unchanged, and record exact model/config fingerprints, sample identity, quality outcomes, and elapsed time. The existing BioCLIP adapter is the built-in implementation; other model configurations require a supported local adapter and validated assets. No new runtime dependency, training, service, upload, or automatic model switch is planned.

**Rationale**: Current adapter supports only one fixed model architecture and is intentionally strict/offline. Benchmark results must be attributable and optional.

**Alternatives considered**: Automatically choose the highest-scoring model or add a network model registry. Rejected due to selection bias, privacy, and irreproducible model identity.

## Alternatives and non-goals

- Do not rebuild the blind crop-review workflow; make only the schema/converter adaptations needed for reusable labels.
- Do not equate relative softmax/similarity with biological probability; do not claim universal accuracy or a fixed gain.
- Do not train/fine-tune, upload private data, add cloud services, or automatically re-ingest footage.
- Do not reclassify missing lighting, invent taxonomic identity, or combine uncertain frames into visits.
- Keep crop labels, references, full images, and generated reports external to version control.

## Resolved questions

No technical-context clarification remains. Initial implementation defaults are: legacy tight crop generation unless `context-v1` is selected (then 10% expansion per side); 32-pixel minimum crop width and height for new setups; legacy center-crop input view for historical setup reproduction and `fit-pad-v1` by default for new setups; minimum margin disabled unless explicitly configured; and `per-lighting=40` in the validation guide. These are reproducibility/quality-control settings, not empirically calibrated biological thresholds.

Reference decision rule is fixed: compare normalized embeddings by cosine similarity, inspect the top five references, retain only examples meeting the configured minimum similarity, require at least three retained references and a most-common species fraction meeting the configured minimum agreement, otherwise use zero-shot fallback. The reference path requires both thresholds explicitly; neither is presented as probability. Visit grouping is externally supplied and confident/owner-reviewed only; aggregate at least two compatible crop logits by arithmetic mean before applying threshold and margin. Benchmark commands require an explicit positive crop cap no greater than 500. Review sampling is deterministic and capped at 500 crops per lighting stratum. These fixed bounds can be changed only through a new versioned setup/algorithm, not silently.

The legacy zero-shot setup remains available as a reproducible baseline. Reference assistance, crop-context expansion, margin rejection, visit aggregation, and alternative-model benchmarks are explicit opt-ins; new setups use the improved fit/pad input and minimum crop-size policy by default. All setup/quality-relevant values are validated and fingerprinted.







