# Feature Specification: Improve Wildlife Species Classification

**Feature Branch**: `main` (existing branch; no branch-creation hook configured)

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "Improve species classification using the attached species-classification-improvements guidance. Blind crop-review and CSV conversion tools already exist."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Measure classification quality before and after changes (Priority: P1)

As the local footage owner, I want to label a representative sample and compare each classification setup against the same examples, so that I can tell whether a change improves useful identifications rather than relying on plausible-looking predictions.

**Why this priority**: No classification adjustment can be judged reliably without a blind, measured baseline that includes night images and animals outside the candidate list.

**Independent Test**: Use the existing blind crop-review workflow to label a fixed sample, record baseline results, and compare a second version against the same labels. Confirm that counts and quality measures are reported separately for day, night, and unknown lighting and that the report identifies the exact setup evaluated.

**Acceptance Scenarios**:

1. **Given** an indexed collection and a representative set of reviewed crops, **When** the owner evaluates the current setup, **Then** the report records a reproducible baseline, sample counts, and results grouped by day, night, and unknown lighting.
2. **Given** a later setup and the same eligible labels, **When** the owner compares it with the baseline, **Then** the report makes changes in correct species assignments, unassigned decisions, coverage, and handling of out-of-list animals visible without presenting a relative score as a probability.
3. **Given** fewer than 10 labeled day or 10 labeled night examples, **When** the owner reviews the report, **Then** the relevant quality conclusion is marked insufficient for publication-ready claims rather than treated as established.
4. **Given** a review sample that includes animals not represented by a species candidate, **When** the owner evaluates it, **Then** those examples remain separately measurable and are not counted as correct species-level identifications merely because a broad animal category was selected.

---

### User Story 2 - Improve the local candidate vocabulary (Priority: P1)

As the local footage owner, I want classification candidates to reflect the animals actually seen around my cameras and to include broad bird and mammal choices, so that unfamiliar local species are less likely to be forced into an unrelated species label.

**Why this priority**: A classifier cannot name a missing species, and a closed candidate list can produce confident but misleading assignments for animals it does not contain.

**Independent Test**: Evaluate labeled examples against the existing candidate set and an expanded set that includes only supported local species plus broad bird and mammal choices. Confirm that species-level and broad-category outcomes are distinguishable and the setup version is retained in the results.

**Acceptance Scenarios**:

1. **Given** review labels show a species absent from the current candidate list, **When** the owner adds that locally relevant species, **Then** a subsequent evaluation can identify it as a species-level candidate and distinguish the result from earlier configurations.
2. **Given** an animal belongs to a supported broad category but has no matching species candidate, **When** classification selects the broad bird or mammal choice, **Then** the result is reported as a coarse category and not as a confirmed species.
3. **Given** a labeled example is unknown or unidentifiable, **When** it is evaluated, **Then** the report distinguishes uncertainty from an out-of-list animal and from a species-level error.
4. **Given** a species candidate has a common name and a taxonomic description, **When** it is compared with an image, **Then** both pieces of information contribute to the candidate description and the prompt version is identifiable in the result.

---

### User Story 3 - Preserve useful animal detail in reviewed crops (Priority: P2)

As the local footage owner, I want classification images to retain the full animal and enough surrounding visual context, so that important features near the edge of a detection are not discarded before identification.

**Why this priority**: Tight or elongated crops can omit distinguishing detail, while tiny or degraded crops may not contain enough evidence for a responsible species decision.

**Independent Test**: Process representative detections near frame edges and detections with elongated shapes, then inspect the resulting images and decisions. Verify that the animal is not clipped by crop preparation, small unusable crops are identified as low quality, and previous runs remain unchanged.

**Acceptance Scenarios**:

1. **Given** a detected animal close to a frame boundary, **When** its crop is prepared, **Then** the crop retains all available animal pixels and does not extend beyond the source frame.
2. **Given** an elongated animal crop with useful details near its edges, **When** it is prepared for classification, **Then** those details remain visible rather than being removed by a later square viewing area.
3. **Given** a crop below the minimum usable size or otherwise unsuitable for identification, **When** it is processed, **Then** it is identified as low quality or unidentifiable and is not presented as a reliable species assignment.
4. **Given** crop preparation settings change, **When** a new run is produced, **Then** the new images and decisions are distinguishable from historical results and historical crop data is not silently overwritten.

---

### User Story 4 - Adapt classification to reviewed local examples (Priority: P2)

As the local footage owner, I want an optional classification setup that can use trusted examples from my own cameras, so that it can account for local backgrounds, lighting, and viewpoints while preserving the current general-purpose setup as a comparison.

**Why this priority**: A small, representative set of reviewed local examples may improve results for a particular camera without requiring a model to be trained on all footage.

**Independent Test**: Select reference examples and a disjoint evaluation sample, separated by source video or recording day. Compare the optional reference-assisted results with the existing baseline, including cases where reference examples are too dissimilar to support a decision.

**Acceptance Scenarios**:

1. **Given** reviewed reference crops for a species and separate evaluation crops, **When** the owner evaluates the optional reference-assisted setup, **Then** evaluation examples are not also used as references and reported outcomes identify both sets.
2. **Given** an evaluation crop has sufficiently close, consistent reference examples, **When** classification completes, **Then** the optional setup may use those examples to produce its species suggestion.
3. **Given** an evaluation crop has no sufficiently close or consistent reference examples, **When** classification completes, **Then** it falls back to the retained general-purpose classification path rather than forcing a reference match.
4. **Given** an alternative model configuration is evaluated, **When** the owner compares it on a bounded sample, **Then** the report includes classification quality and processing time, and it does not silently replace the selected model.

---

### User Story 5 - Withhold uncertain decisions and use repeated frames (Priority: P3)

As the local footage owner, I want ambiguous individual results to remain unassigned and repeated views of the same visit to contribute to a steadier conclusion, so that a narrow score lead or one poor frame does not look like a confident identification.

**Why this priority**: Similar candidate scores and variable frame quality make a single-frame decision fragile, especially in night footage.

**Independent Test**: Use controlled examples with close top candidates, clear top candidates, and multiple consecutive frames from one visit. Verify the uncertainty rule and compare individual-frame results with the visit-level result without losing crop provenance.

**Acceptance Scenarios**:

1. **Given** the best candidate's score is acceptable but its lead over the next candidate is below the configured minimum margin, **When** classification completes, **Then** the result is unassigned with an uncertainty reason and the competing candidates remain inspectable.
2. **Given** the best candidate clears both the existing score threshold and the configured margin, **When** classification completes, **Then** the unique candidate may be assigned with its score and configuration recorded.
3. **Given** multiple consecutive frames belong to one identified visit, **When** visit-level classification is requested, **Then** the combined result is reported separately from each crop-level result and links back to all contributing crops.
4. **Given** frames cannot be confidently grouped into the same visit, **When** results are produced, **Then** they are not combined merely because they came from the same video.

---

### Edge Cases

- A species absent from the candidate list may still receive a high relative score; broad bird and mammal choices reduce but do not eliminate this limitation.
- A broad category can be correct while the species remains unknown. Reports must not conflate category-level handling with correct species identification.
- Taxonomy or common-name information may be missing or inconsistent for a candidate; the owner must be able to identify and correct the candidate entry before relying on comparisons.
- Labels may include species, out-of-list animals, unidentifiable animals, and non-animal or unusable crops. Each label type must remain distinct in evaluation.
- Day, night, and unknown lighting groups can have very different sample sizes and results. Empty or undersized groups must be reported as unavailable or insufficient, not as perfect.
- A margin rule can increase the number of unassigned crops while improving the precision of assigned results; both coverage and assignment quality must be visible.
- A reference-assisted method may have no suitable example for a crop. The general-purpose fallback remains available and must be identified in the result.
- Similar consecutive frames may show different animals or visits. Aggregation must not combine uncertain groups or erase per-crop decisions.
- A changed candidate list, crop preparation, prompt description, model, uncertainty setting, reference set, or aggregation rule creates a distinguishable setup; results from different setups must not be silently mixed.
- Private crops, review labels, reference sets, and generated quality reports remain outside version control.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support a blind, labeled evaluation of classification results using the repository's existing review and evaluation workflow. This feature MUST NOT recreate or replace the already available review tools.
- **FR-002**: Owners MUST be able to record a baseline and compare later classification setups using the same eligible labels. Each report MUST identify the setup, label sample, date/night/unknown group counts, correct species assignments, unassigned decisions, assignment coverage, and observed error cases.
- **FR-003**: Evaluations MUST distinguish correct species-level assignments, broad-category outcomes, out-of-list animals, unidentifiable examples, and unknown classification decisions. A broad-category match MUST NOT count as a correct species-level assignment.
- **FR-004**: Before a quality claim is described as publication-ready, the evaluation MUST contain at least 10 labeled day and 10 labeled night examples. Reports MUST mark missing or undersized groups as insufficient and MUST NOT imply unmeasured accuracy.
- **FR-005**: The owner MUST be able to maintain a local candidate set that includes locally observed species and broad bird and mammal choices. Each species candidate MUST have a common name and taxonomic description, and both MUST contribute to the textual description used for classification. Candidate and prompt changes MUST be versioned for comparison.
- **FR-006**: A result assigned to a broad bird or mammal candidate MUST be explicitly labeled as a broad category, not a species identification. An out-of-list or unidentifiable label MUST remain distinguishable from a confirmed species label.
- **FR-007**: Crop preparation MUST preserve all available pixels of the detected animal, provide surrounding context without exceeding source-frame boundaries, and retain edge details when preparing crops of different shapes. Crops below a defined minimum usable size MUST be identified as low quality rather than treated as reliable species evidence.
- **FR-008**: Changes to crop preparation MUST produce distinguishable new inputs and results without silently overwriting historical crop data or making old and new evaluations appear to use identical images.
- **FR-009**: The current general-purpose classification path MUST remain available as a reproducible baseline. Reference-assisted classification MUST be optional and MUST use reference examples that are separate from evaluation examples by source video or recording day.
- **FR-010**: Reference-assisted classification MUST fall back to the general-purpose path when available reference examples do not provide a sufficiently close and consistent match. The resulting decision MUST identify whether it came from the reference-assisted path or fallback.
- **FR-011**: Alternative model configurations MAY be benchmarked on a bounded, representative sample. Their reports MUST include quality measures and processing time; the system MUST NOT silently switch a user's selected model or claim an improvement without evaluation evidence.
- **FR-012**: Users MUST be able to configure a minimum score margin between the best and second-best candidates. A result below the existing acceptance threshold or below the configured margin MUST remain unassigned with a reason; tied and competing candidates MUST remain inspectable. Margin behavior MUST NOT replace the existing score-threshold behavior.
- **FR-013**: The owner MUST be able to request a visit-level result for frames confidently grouped into the same visit. Visit-level results MUST remain distinct from crop-level decisions and preserve links to all source crops. Uncertainly grouped frames MUST NOT be combined.
- **FR-014**: Every evaluated result MUST retain enough setup and source identity to distinguish the crop, source video/frame, lighting group, candidate set, model and prompt version, crop-preparation settings, uncertainty settings, reference set when applicable, and aggregation context when applicable.
- **FR-015**: Scores MUST be described as relative to the selected candidates and setup, not as calibrated probabilities of biological correctness. Reports MUST state that unfamiliar species can still receive a high score and that results may differ substantially between day and night.
- **FR-016**: Classification, evaluation, and any reference-example workflow MUST run locally. Source footage, crops, labels, reference examples, and reports MUST NOT be uploaded or committed to version control as part of normal operation.
- **FR-017**: Classification quality comparisons MUST use reviewed examples that are not used to select or tune the compared setup. When the available sample cannot support a fair comparison, the report MUST state that limitation rather than claim an improvement.
- **FR-018**: Core candidate handling, crop-quality decisions, score-margin behavior, reference fallback, visit aggregation, and report comparisons MUST be verifiable with controlled examples without requiring live model services or network access. Model-quality claims MUST be based on reviewed real examples and kept distinct from controlled correctness checks.

### Key Entities *(include if feature involves data)*

- **Classification Setup**: A versioned combination of candidate descriptions, model selection, crop preparation, score threshold, minimum margin, optional reference set, and optional visit aggregation rules.
- **Reviewed Crop Label**: A blind human assessment of a crop, including its lighting and whether it shows a known species, an out-of-list animal, an unidentifiable animal, or an unusable example.
- **Reference Example Set**: Reviewed crop examples available to an optional reference-assisted classification setup and kept separate from examples used to evaluate it.
- **Crop-Level Decision**: A species, broad-category, or unassigned result for one crop, with its competing candidates, score context, decision reason, and setup identity.
- **Visit-Level Decision**: A combined result for crops confidently associated with one visit, with references to the contributing crop-level decisions and the aggregation setup.
- **Quality Comparison**: A report comparing one or more versioned setups against a defined reviewed sample, grouped by lighting and label type, with counts, quality measures, processing time where relevant, and limitations.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A baseline and every compared setup can be evaluated against the same reviewed sample, and the resulting reports expose day, night, and unknown counts plus correct species assignments, unassigned decisions, coverage, out-of-list handling, and observed errors.
- **SC-002**: In acceptance cases, 100% of broad bird or mammal outcomes are reported as category-level outcomes and are excluded from species-level accuracy as if they were exact species matches.
- **SC-003**: In crop-preparation acceptance cases covering frame-edge, elongated, and below-minimum-size detections, 100% retain all available animal pixels, preserve relevant edge details, or are explicitly flagged as low quality; no crop extends beyond its source frame.
- **SC-004**: In score acceptance cases, 100% of examples below the configured threshold or minimum margin remain unassigned with the correct reason, while clear unique candidates that pass both checks remain eligible for assignment.
- **SC-005**: In reference-assisted acceptance cases, no evaluation crop is used as a reference; every insufficient-match case follows the documented fallback, and every output identifies its decision path.
- **SC-006**: Every visit-level acceptance result links to all contributing crop decisions, and no uncertainly grouped frames are combined.
- **SC-007**: No classification-quality claim is reported as publication-ready with fewer than 10 labeled day or 10 labeled night examples. Setup comparisons report sample limitations and do not promise a fixed accuracy gain before measurements exist.
- **SC-008**: Alternative model benchmarks report both the measured classification outcomes and processing time on the stated sample, and never change the active model without an explicit owner choice.

## Assumptions

- The owner is the existing local user operating the current ingestion, indexing, and species-evaluation workflows. The blind crop-review and CSV tools already exist and are prerequisites, not deliverables of this feature.
- The current zero-shot classification setup is retained as the baseline. Reference-assisted classification and alternative model configurations are optional paths; this feature does not mandate training or automatic model replacement.
- The existing embedding-and-tagging specification's prohibition on using labeled crop matches applies to its default zero-shot path; this feature adds an explicitly opt-in reference-assisted path without changing that default.
- Candidate vocabulary additions are driven by reviewed local examples rather than adding every plausible regional species without evidence. Broad bird and mammal choices are coarse fallbacks, not substitutes for a complete taxonomy.
- Existing lighting metadata is used for day/night/unknown reporting; this feature does not reclassify lighting or infer missing capture metadata.
- A visit means a group of frames confidently associated with the same animal visit under a consistent grouping rule. Determining the exact grouping method and suitable local processing budget belongs in planning.
- The attached guidance orders work as measurement, vocabulary and prompt improvements, crop improvements, optional reference-assisted and alternative-model evaluation, then uncertainty and visit aggregation. Planning may stage these changes while preserving a comparable baseline at each stage.
- No absolute accuracy target is promised because trail-camera imagery, night infrared, candidate coverage, and available labels can vary substantially. A setup is not promoted solely because it has higher raw coverage or relative scores.
- Existing embedding storage and scoring contracts remain in force except for the explicitly optional reference-assisted mode and the added uncertainty and visit-level results. The existing general-purpose path remains usable and comparable.
- Private footage, reviewed labels, reference examples, and generated reports remain outside Git; a small evaluation sample is not assumed to be representative of all cameras or seasons.
- User interface redesign, cloud processing, multi-user workflows, live video classification, automatic video re-ingestion, and general-purpose animal tracking are outside this feature.


