# Feature Specification: Text Search over Wildlife Crops

**Feature Branch**: `main` (existing branch; no branch-creation hook configured)

**Created**: 2026-10-25

**Status**: Draft

**Input**: User description: "search: Given a text query (and optional filters: date range, day/night, species), return the most similar crops/frames with scores."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find wildlife images with a text query (Priority: P1)

As the local footage owner, I want to describe what I am looking for and receive ranked animal crops, so that I can find relevant footage without inspecting every video.

**Why this priority**: Text-to-image retrieval is the core requested capability and completes a useful workflow from existing indexed crops to inspectable evidence.

**Independent Test**: Search a fixed collection with controlled query-to-crop similarities. Confirm the returned crop identities, ranking, scores, result limit, and source references without requiring filters or answer generation.

**Acceptance Scenarios**:

1. **Given** an indexed collection and a nonblank query such as "squirrel on the feeder", **When** the owner searches through the CLI, **Then** results contain the most similar eligible crops in descending similarity order, each with a rank, score, crop location, and source-frame reference.
2. **Given** more than five eligible crops and no explicit result limit, **When** the owner searches, **Then** at most five results are returned; an explicit positive whole-number limit replaces that default.
3. **Given** fewer eligible crops than the requested limit, **When** the owner searches, **Then** all eligible crops are returned once, without padding or invented results.
4. **Given** unchanged query, collection, and search settings with equal-scoring crops, **When** the owner repeats the search, **Then** tied results have a repeatable order and the same crops occupy the result-limit boundary.

---

### User Story 2 - Narrow results using footage metadata (Priority: P2)

As the local footage owner, I want to restrict a text search by capture date, day or night, and assigned species, so that the returned images match the part of my collection I want to inspect.

**Why this priority**: Explicit filters turn broad visual similarity into targeted retrieval without pretending that natural-language descriptions impose strict metadata restrictions.

**Independent Test**: Search a collection containing known date boundaries, lighting groups, species assignments, and unknown metadata. Apply each filter independently and all filters together, then compare the results with the expected eligible set and ranking.

**Acceptance Scenarios**:

1. **Given** crops captured before, on, and after selected calendar dates, **When** the owner sets a start date, an end date, or both, **Then** only crops whose recorded capture date satisfies the inclusive bounds are eligible; crops without a known capture date are excluded.
2. **Given** crops labeled day, night, and unknown lighting, **When** the owner selects day or night, **Then** only crops with that exact lighting classification are eligible.
3. **Given** crops with an assigned species, unknown decisions, and differing best-candidate suggestions, **When** the owner selects a species identifier, **Then** only crops assigned that identifier in the selected tagging context are eligible; an unassigned best candidate does not qualify.
4. **Given** a text query and multiple filters, **When** the owner searches, **Then** every result satisfies all supplied filters and the highest-scoring eligible crops are returned, rather than filtering only an already limited unfiltered result list.
5. **Given** a valid query and filters with no eligible crops, **When** the owner searches, **Then** the command succeeds with an explicit zero-results outcome and does not relax any filter.

---

### User Story 3 - Inspect evidence and understand limitations (Priority: P3)

As the local footage owner, I want results to explain where each crop came from and what its scores mean, so that I can inspect the original evidence and avoid mistaking a retrieved match for a confirmed sighting.

**Why this priority**: Traceable retrieval supports trustworthy manual inspection now and cited answers in a later feature.

**Independent Test**: Inspect results containing complete and missing capture metadata, unknown species, and an unavailable crop file. Verify provenance, score labels, context identification, and explicit limitations without running answer generation.

**Acceptance Scenarios**:

1. **Given** a returned crop, **When** the owner inspects its result, **Then** stable crop and representation identities, source video, frame number, elapsed time, crop location, detection box and confidence, capture time and timezone when known, lighting, and species decision with confidence when available remain accessible.
2. **Given** similarity, species confidence, and detection confidence in the same result, **When** the owner reads the output and its guidance, **Then** each score is distinctly labeled and similarity is described as relative relevance, not a probability that the query is true or a species identification is correct.
3. **Given** a stored crop whose local image has moved or is unreadable, **When** it is returned, **Then** its ranking and provenance remain available and the crop is explicitly marked unavailable rather than silently omitted or replaced.
4. **Given** invalid input or unavailable search prerequisites, **When** the owner searches, **Then** an actionable error identifies the problem, no results are fabricated, and failure is distinguishable from a successful empty search.

### Edge Cases

- Empty or whitespace-only queries, malformed calendar dates, a start date after the end date, unsupported lighting values, unknown species identifiers, and nonpositive or non-whole-number result limits are input errors.
- Start and end dates may be supplied independently. A same-day range includes the entire recorded calendar day. Missing capture dates never match a date filter; missing timezones are not guessed.
- A phrase such as "at night" influences similarity only. It does not silently add a night filter or change an explicit day filter; natural-language date or species expressions likewise do not create metadata filters.
- Unknown lighting remains eligible without a lighting filter. An unknown species decision can be searched without a species filter and can be selected explicitly using the reserved `unknown` decision value.
- Multiple representations of a crop and historical tagging configurations must not cause duplicate or incompatible results. Ambiguous search contexts require explicit selection rather than silently mixing versions.
- A valid empty indexed collection returns zero results. Unavailable storage, unavailable local model assets, and a collection containing only incompatible representations are errors, not empty successful searches.
- Non-finite query representations or similarity scores are failures, not valid ranked results. A failure must not be disguised as a complete shorter result list.
- Similar crops from consecutive frames may all be returned. Visit grouping and near-duplicate suppression are not implied.
- A low-scoring nearest match may still be irrelevant. Search alone cannot establish that an animal or event is present or absent from all footage.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a local CLI-first search accepting one nonblank text query against previously indexed retained animal crops. It MUST NOT require re-ingesting footage, recomputing stored crop representations, or generating an answer.
- **FR-002**: Search MUST compare the query with compatible stored crop representations and return the highest-scoring eligible crops in descending similarity order. Similarity scores MUST be finite, higher scores MUST indicate greater similarity, and the score range and interpretation MUST be documented. Equal scores MUST be ordered by stable crop identity.
- **FR-003**: Users MUST be able to request a positive whole-number maximum result count, defaulting to five. Search MUST return no more than that count and no more than the number of eligible crops, without duplicate crop identities. No minimum-similarity cutoff is applied in this feature.
- **FR-004**: Users MUST be able to supply optional start and end calendar dates in `YYYY-MM-DD` form. Bounds MUST be inclusive and independently optional, using the recorded capture-time calendar date, not indexing time, filesystem time, or elapsed video time. Missing capture dates MUST be excluded only when a date filter is present. Search MUST NOT invent timezones or convert timezone-unknown values into assumed absolute times.
- **FR-005**: Users MUST be able to restrict results to exactly day or night using the stored lighting classification. Unknown lighting MUST not match either filter and MUST remain eligible when no lighting filter is supplied.
- **FR-006**: Users MUST be able to restrict results to one stable species identifier from the selected tagging context or the reserved `unknown` decision value. Filtering MUST use the final assigned species or unknown decision, never an unassigned best candidate. Invalid identifiers MUST be reported as input errors; a valid species with no matching crops MUST produce a successful empty result.
- **FR-007**: All supplied metadata filters MUST apply together before the maximum result count is imposed. Omitted filters MUST impose no restriction on their corresponding metadata. Query wording MUST NOT silently create or override explicit metadata filters.
- **FR-008**: Each result MUST include rank, similarity score, stable crop and representation identities, crop location, and source video/frame reference. Available provenance MUST remain inspectable: elapsed time, detection box and confidence, capture time and timezone, lighting, and species decision and confidence. Missing metadata MUST remain explicitly unknown. An unavailable local crop file MUST be marked unavailable without silently removing its stored match.
- **FR-009**: Every search MUST identify its query, applied filters, requested limit, returned count, and selected collection and representation/tagging context. One search MUST use compatible representations and one unambiguous tagging context; configuration versions MUST NOT be silently mixed. If available contexts do not uniquely determine a selection, the owner MUST be able to select one explicitly and receive actionable guidance when selection is required.
- **FR-010**: Output and guidance MUST distinguish retrieval similarity from species-tagging confidence and detection confidence. They MUST NOT describe any of these as proof of species identity, event occurrence, or event absence. Existing candidate-relative confidence limitations MUST be retained.
- **FR-011**: Search MUST validate query, filters, result limit, context selection, and required local resources. It MUST distinguish successful results, successful zero results, invalid input, and operational failure. Unavailable or incompatible resources and invalid numeric results MUST not be reported as successful searches. Error output MUST NOT disclose credentials.
- **FR-012**: Search MUST be read-only with respect to source footage, crops, ingestion manifests, stored crop representations, and species decisions. It MUST run locally without uploading footage or queries, calling an answer-generation service, or automatically downloading model assets. It MUST search only the retained indexed collection and MUST NOT reopen excluded ingestion frames as additional candidates.
- **FR-013**: Explicit CLI configuration MUST take precedence over process environment, local `.env`, and built-in defaults, in that order. User guidance MUST explain prerequisites, context selection, filters and unknown metadata, scores, result inspection, and empty/error outcomes. Any new environment settings MUST be inventoried without secrets in `.env.example` during implementation.
- **FR-014**: Query handling, ranking, limits, filters, score validation, context selection, provenance, and empty/error outcomes MUST be testable offline using controlled substitutes. Tests MUST cover affected storage and representation boundaries separately from real-world retrieval-quality measurements; standard tests MUST require neither private footage nor network access.

### Key Entities *(include if feature involves data)*

- **Search Request**: The owner's text query, optional capture-date bounds, optional lighting and species filters, selected search context, and maximum result count.
- **Search Context**: The identified indexed collection and compatible representation version, together with one selected species candidate set and tagging configuration. It determines which stored representations and decisions are eligible for comparison and inspection.
- **Search Result**: One ranked crop match with finite similarity, stable crop and representation identities, local image availability, existing source-frame provenance, and the selected context's species decision. Multiple results may reference the same source frame when it contains multiple retained crops.
- **Search Outcome**: The request context, returned count and ordered results, or a distinguishable validation/operational failure. A successful empty outcome makes no claim that the described event never occurred.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a fixed 100-crop acceptance collection with known similarities, every tested query returns exactly the expected top five eligible crop identities by default; custom limits, fewer-than-limit collections, and equal-score boundaries produce the expected count and repeatable ordering in 100% of cases.
- **SC-002**: Across acceptance cases covering each filter alone and all filters combined, 100% of returned crops satisfy every supplied filter. Boundary-day, missing-date, unknown-lighting, assigned-species, and unknown-species cases match the specified eligible sets, including cases where eligible crops fall outside the unfiltered top five.
- **SC-003**: Every returned acceptance result can be traced to its crop and source video/frame with all available provenance preserved. Inspection distinguishes all three score meanings, and missing metadata or unavailable images are explicitly identified in 100% of corresponding cases.
- **SC-004**: All invalid-input and unavailable-resource acceptance cases produce actionable failure outcomes, while all valid zero-match cases succeed with zero results. Repeated searches cause zero changes to indexed crop data, species decisions, or source images.
- **SC-005**: Before retrieval-quality claims are published, a documented manual or automated evaluation covers at least 10 labeled queries, reports the number of queries with at least one relevant crop in the top five and the corresponding hit rate, and records failure cases and the collection/context evaluated. Labels refer to stable crop or frame identities; target selection is reviewed by video or day to avoid treating near-duplicate frames as independent evidence. Controlled correctness tests MUST NOT be presented as measured real-world retrieval quality.

## Assumptions

- The user is the single local footage owner using the existing CLI. Existing ingestion and indexing supply retained crops, compatible stored representations, versioned species decisions, and provenance. Their privacy filtering is reused, not repeated, and does not guarantee anonymity.
- Results are crop-level matches with source-frame references, not newly extracted full frames. Full-frame files need not exist. Opening a viewer, exporting images, and reconstructing source frames are outside this feature.
- The default result limit of five supports a small inspection workflow. There is no pagination, visit aggregation, automatic deduplication across neighboring frames, relevance threshold, reranking, or similarity calibration in this feature.
- Date filters select recorded local calendar dates, which remain useful when camera timezone metadata is absent. Absolute instant filtering, timezone normalization, natural-language filter extraction, taxonomy resolution, species-name aliases, and multiple species filters are outside scope.
- Species filters reflect stored suggestions, not verified biological identity. One species or `unknown` can be selected per search. Candidate identifiers and their meaning come from the selected existing tagging configuration.
- Locally provisioned search model assets and accessible indexed storage are prerequisites. Exact model selection, similarity calculation, storage access, command options, and output encoding belong in implementation planning.
- Retrieval-quality reporting may be performed manually on a small privacy-checked labeled set. A new evaluation command or general evaluation framework belongs to the separate Evaluate feature. Quality claims require measurements; this specification promises no unmeasured semantic accuracy.
- Grounded answers, LLM integration, UI, authentication, multi-user support, cloud deployment, real-time streaming, model training/fine-tuning, and ingestion or tagging changes are excluded. Search preserves evidence identities for later Ask work without implementing it.
