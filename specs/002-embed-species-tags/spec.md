# Feature Specification: Crop Embeddings and Zero-Shot Species Tags

**Feature Branch**: `main` (existing branch; no branch-creation hook configured)

**Created**: 2026-10-19

**Status**: Draft

**Input**: User description: "Embed crops with BioCLIP, store vectors in pgvector, assign zero-shot species tags with confidence scores from a configurable species list."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Index and identify ingested crops (Priority: P1)

As the local footage owner, I want to process retained animal crops into stored visual representations and suggested species tags, so that my footage is ready for later search and I can inspect what animal each crop may show without manually labeling every image.

**Why this priority**: This delivers the requested end-to-end workflow: crop in, durable vector and scored species suggestion out.

**Independent Test**: Process a fixture ingestion manifest and readable crops using a controlled model substitute and a configured species list. Inspect the saved results and run summary to confirm that every successful crop has a vector, a species decision, and its original provenance. Verify the persistence boundary separately against the local database.

**Acceptance Scenarios**:

1. **Given** retained crops with ingestion provenance, available model assets and storage, and a valid species list, **When** the owner runs indexing from the CLI, **Then** each successful crop has a persisted vector and a scored species decision linked to its original crop, source video, frame, and capture metadata.
2. **Given** a crop whose highest-scoring candidate meets the configured confidence threshold and has no exact tie, **When** tagging completes, **Then** its assigned tag is that candidate and the result includes its confidence score and the configuration used.
3. **Given** a crop whose best candidate falls below the threshold, **When** tagging completes, **Then** its decision is `unknown`, its best candidate and score remain inspectable, and it is not presented as a confirmed species identification.
4. **Given** saved results and a completed run, **When** the owner inspects them after restarting the application, **Then** vectors, species decisions, scores, and original provenance remain available without repeating inference.

---

### User Story 2 - Control the candidate species (Priority: P2)

As the local footage owner, I want to supply the species that may occur at my cameras and adjust the acceptance threshold, so that suggestions reflect my local wildlife rather than an implicit fixed vocabulary.

**Why this priority**: A configurable vocabulary is essential to useful zero-shot classification, and confidence must be interpreted in the context of that vocabulary.

**Independent Test**: Use an existing stored crop representation with two different valid candidate lists and controlled scores. Confirm that each result uses only the selected list, identifies that list, and applies threshold changes without requiring ingestion again.

**Acceptance Scenarios**:

1. **Given** a valid local species configuration, **When** the owner selects it for a run, **Then** every assigned species belongs to that configuration and each decision identifies the exact candidate set used.
2. **Given** an already indexed crop and a changed species list or threshold, **When** the owner reruns tagging, **Then** the new decision reflects the selected settings, reuses a compatible stored crop representation, and cannot be mistaken for a result from the earlier settings.
3. **Given** a missing, unreadable, empty, malformed, or duplicate-containing species configuration, **When** the owner starts processing, **Then** validation reports the offending input before writing any crop results.
4. **Given** explicit command options and conflicting environment or local configuration defaults, **When** the owner starts the run, **Then** explicit options take precedence over process environment, local `.env`, and built-in defaults, in that order.

---

### User Story 3 - Resume processing and inspect quality (Priority: P3)

As the local footage owner, I want interrupted or partially failed work to be safely repeatable and species quality to be measured on labeled examples, so that I can trust both indexing completeness and the limitations of the tags.

**Why this priority**: Reliable recovery avoids wasted inference, while measured daylight and night results prevent misleading accuracy claims.

**Independent Test**: Interrupt a fixture batch, rerun it with unchanged settings, and compare complete result counts and provenance. Separately evaluate labeled daytime and nighttime fixtures and compare the report with hand-calculated outcomes.

**Acceptance Scenarios**:

1. **Given** a completed run, **When** the owner repeats it with unchanged inputs and settings, **Then** complete results are skipped, no duplicate active results are created, and the summary distinguishes newly processed and skipped crops.
2. **Given** a batch containing one missing or corrupt crop among readable crops, **When** processing runs, **Then** independent readable crops still complete, the failed crop is identified with a reason, and the run reports partial failure rather than full success.
3. **Given** an interruption or storage failure, **When** processing is retried, **Then** no incomplete result is treated as successful, previously committed results remain usable, and unfinished crops can complete without re-ingesting video.
4. **Given** labeled examples containing daylight and night crops, **When** species quality is evaluated, **Then** the report separately states sample counts, correct and incorrect assigned tags, unknown decisions, and known failure cases for each lighting group; unknown-lighting examples are reported separately.

### Edge Cases

- No retained crops: finish successfully with a zero-work summary and no fabricated results.
- Missing or unreadable manifest, invalid confidence threshold, unavailable model assets, unreachable database, or unavailable vector support: fail preflight clearly before crop-result writes; never silently switch to another storage backend.
- Animal crops may contain non-birds, multiple animals, poor views, or species absent from the candidate list. Treat the tag as a suggestion, allow `unknown`, and document that an out-of-list animal can still score highly.
- Exact ties for the highest score produce an `unknown` decision with a tie reason; threshold equality qualifies if the highest score is unique.
- A single-candidate list is valid but cannot distinguish that candidate from an out-of-list species; the result still carries the limited-candidate confidence warning.
- Blank identifiers or names, duplicate identifiers, and duplicate candidate names after trimming and case-insensitive comparison are configuration errors. Distinct species require distinct candidate names; taxonomy resolution and synonym merging are not implied.
- Non-finite scores, non-finite or zero-length vectors, and vectors incompatible with the selected model are per-crop failures, not successful results.
- A changed embedding model invalidates reuse of its previous crop vectors; a changed candidate list or threshold invalidates reuse of the species decision, not an otherwise compatible crop vector.
- Missing capture times or unknown lighting remain unknown; processing must not invent timestamps or infer daylight from missing metadata.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a CLI-first batch workflow consuming retained crops and their manifest from the existing ingestion feature. It MUST NOT require video re-ingestion or modify the source crops or manifest.
- **FR-002**: The system MUST generate crop embeddings using pretrained BioCLIP and persist them in the local PostgreSQL database with pgvector, as required by the project constitution and user request. Model training and fine-tuning are excluded.
- **FR-003**: Every stored crop representation and species result MUST retain an unambiguous link to the ingestion crop identity, source video identity, frame number, elapsed time, crop location, detection box and confidence, capture time and timezone when known, and lighting classification. Missing values MUST remain explicitly unknown.
- **FR-004**: The system MUST accept an explicitly selected local species-list configuration containing stable species identifiers and candidate names used for zero-shot comparison. A valid list MUST have at least one entry; invalid entries and duplicates as defined under Edge Cases MUST be rejected before crop-result writes. No fixed global species vocabulary may silently replace the selected list.
- **FR-005**: The system MUST score each crop against the configured candidate names using BioCLIP's image/text comparison, without requiring labeled training examples. Classification MUST NOT depend on nearest labeled crop matches or an LLM service.
- **FR-006**: Each successful tagging result MUST record its unique best candidate and confidence score, when one exists, and a final species identifier or `unknown` decision with a reason. Confidence MUST be finite and in the inclusive range 0 to 1. Documentation and inspection output MUST describe it as a relative score within the selected candidate set, not a calibrated probability of biological correctness or the ingestion detector's confidence.
- **FR-007**: Users MUST be able to configure an acceptance threshold in the inclusive range 0 to 1, defaulting to 0.5. A unique best candidate is assigned only when its score is greater than or equal to that threshold; below-threshold results and exact best-score ties MUST be `unknown`. Tied candidates and their shared score MUST remain inspectable.
- **FR-008**: Results MUST identify the embedding model and version, the candidate-list content version, the scoring configuration, acceptance threshold, and processing time. Changes affecting embeddings or scores MUST be distinguishable from earlier results, and results from different candidate sets MUST NOT be presented as directly comparable confidence estimates.
- **FR-009**: Users MUST be able to inspect persisted crop decisions, scores, processing status, and provenance through the CLI without rerunning model inference. This is result inspection, not a general image/text similarity-search feature.
- **FR-010**: Rerunning unchanged crop inputs with the same model and tagging configuration MUST NOT duplicate complete active results or repeat their inference. Changed candidate lists or thresholds MUST permit retagging compatible stored crop vectors without recomputing those vectors; changed embedding models MUST require compatible new vectors. Older decisions MUST remain distinguishable from the selected configuration's results.
- **FR-011**: Processing MUST persist a crop vector and its associated completed tagging result consistently: a partial or failed write MUST NOT be reported or skipped as complete on retry. Previously completed crops MUST remain usable following interruption or failure.
- **FR-012**: Processing MUST continue past isolated crop read or inference failures when model and storage remain usable, identify failed crops and reasons, and report selected, completed, skipped, failed, assigned, and unknown counts. Assigned plus unknown MUST equal newly completed tagging results. Storage loss MUST stop further processing and report failure rather than claim unsaved work succeeded. The CLI MUST distinguish complete/no-input success, processing failure, and preflight failure in its exit status.
- **FR-013**: Preflight MUST validate the manifest, species configuration, threshold, model availability, database connection, and vector support before writing crop results. A dry input set MUST not cause model or species results to be fabricated.
- **FR-014**: Processing MUST run locally with locally provisioned model assets and MUST NOT upload crops or automatically download model assets during a run. Private footage, crops, derived results, and credentials MUST remain outside version control. Existing ingestion MUST remain usable without BioCLIP assets or a running database.
- **FR-015**: Configuration MUST follow repository precedence: explicit CLI values over process environment, then `.env`, then built-in defaults. Documentation MUST describe model provisioning, species-list selection, threshold semantics, storage prerequisites, run inspection, and retry behavior; any new environment settings MUST be inventoried in `.env.example` without secrets.
- **FR-016**: Species tagging MUST be evaluated on labeled examples with separate daylight, night, and unknown-lighting results. Reports MUST state candidate-list and model versions, threshold, sample counts, correct and incorrect assignments, unknown counts, assigned-tag precision, assignment coverage, and observed failure cases. A group with no examples or no assigned tags MUST report the affected measure as unavailable rather than imply perfect quality.
- **FR-017**: Core indexing, configuration, scoring decisions, provenance, and retry behavior MUST be testable offline with controlled model and storage substitutes. Persistence integration MUST have tests at the real database boundary, and model-quality evaluation MUST be distinguished from substitute-based correctness tests. The standard test suite MUST require neither live model services nor network access.

### Key Entities *(include if feature involves data)*

- **Ingested Crop**: An existing retained animal image with stable crop identity, its location, and source-frame, detection, capture-time, and lighting provenance. It is an input, not recreated by this feature.
- **Crop Representation**: A persistent visual vector associated with one crop and an identified embedding model/version, with completion status and processing time.
- **Species Candidate Set**: A validated, versioned collection of stable species identifiers and candidate names selected by the owner for a tagging run.
- **Species Decision**: A crop's assigned species or `unknown`, best candidate and confidence or tied candidates, decision reason, candidate-set version, and model/scoring/threshold context. It references the crop representation used.
- **Processing Run**: The selected input collection and configuration, progress and outcome counts, and failures needed to inspect and resume work.
- **Quality Evaluation**: Labeled crop examples and a measured report grouped by lighting, identifying the configuration evaluated and its limitations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a controlled batch of 100 readable retained crops, 100% receive a durable visual representation and either an assigned species with confidence or an explicit unknown decision; all 100 can be inspected after restart without repeated processing.
- **SC-002**: In the acceptance fixtures, 100% of assigned species belong to the selected candidate list, 100% of recorded scores are finite and within 0 to 1, and all below-threshold and exact-tie cases are reported as unknown.
- **SC-003**: Every successful result in the acceptance batch can be traced to its original crop and source frame, with no loss or invention of available capture-time or lighting metadata.
- **SC-004**: Repeating the completed 100-crop acceptance batch with unchanged settings creates zero duplicate active results and skips all 100 complete crops. After interruption at a known completion count, retry reaches exactly 100 complete crops without repeating already completed inference.
- **SC-005**: With one unreadable crop in an otherwise valid 100-crop acceptance batch, 99 complete successfully, one is identified as failed, and the run is not reported as fully successful.
- **SC-006**: The owner can change the species list and threshold and inspect corresponding new decisions for every previously completed compatible crop without re-ingesting footage or recomputing its visual representation.
- **SC-007**: Before species-quality claims are published, an evaluation report covers at least 10 labeled daylight and 10 labeled night crops, states assignment coverage and assigned-tag precision for each group, and documents observed failure cases. Acceptance requires transparent measured results, not an unmeasured accuracy promise.

## Assumptions

- The user is the single local owner operating the existing CLI. The existing ingestion manifest is the source of crop identities and provenance; its privacy filtering is not repeated here and does not guarantee anonymity.
- BioCLIP, PostgreSQL, and pgvector are explicit user and constitution constraints, not additional design choices. Exact model variant, vector dimensions, score calculation, storage layout, and command names belong in implementation planning.
- Each crop receives at most one assigned species per configuration. Ranked top-k output, multi-species detection within a crop, taxonomy services, and automatic synonym resolution are outside this feature.
- Candidate names supplied by the owner are intended as species-level names suitable for text comparison. The system validates configuration structure and uniqueness, not biological taxonomy. Evaluation examples can include out-of-list or unidentifiable animals to expose false confident suggestions.
- The default 0.5 threshold is an operational starting point, not a validated accuracy claim. Relative candidate scores cannot guarantee rejection of unfamiliar animals; quality reports must make that limitation clear.
- Local model assets and an available local database with vector support are prerequisites for processing. Setup may provision those assets separately; indexing itself does not perform automatic downloads.
- General similarity search, grounded Q&A, UI, authentication, multi-user support, cloud deployment, real-time streaming, and changes to video ingestion are excluded. Stored vectors and provenance prepare for later retrieval features without implementing them here.
- Evaluation labels and any committed sample crops must be explicitly privacy-checked. Private inputs and generated outputs stay outside the repository.
