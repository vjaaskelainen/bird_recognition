# Feature Specification: Ask Questions About Footage

**Feature Branch**: `main` (existing branch; no branch-creation hook configured)

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "**Ask** — Answer natural-language questions about the footage using retrieved frames and metadata via a vision LLM; cite the frames used; decline when the evidence is insufficient."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get a grounded, cited answer (Priority: P1)

As the local footage owner, I want to ask a natural-language question about my trail-camera footage and receive a short answer that cites the specific crops and source frames it relies on, so that I can verify the answer myself instead of trusting it blindly.

**Why this priority**: Grounded, cited answering is the core of the feature and completes the workflow from ingestion and search to question answering.

**Independent Test**: Ask a question against a fixed collection with controlled retrieval results and a controlled substitute answer generator. Confirm the answer is returned together with citations that each resolve to a retrieved crop and its source video/frame, without needing filters or refusal handling.

**Acceptance Scenarios**:

1. **Given** an indexed collection containing relevant crops and a nonblank question such as "Which birds visited the feeder at night?", **When** the owner asks through the CLI, **Then** the output contains an answer and a list of cited evidence items, each identifying the crop and its source video, frame, and capture time when known.
2. **Given** an answer that makes several distinct claims, **When** the owner reads it, **Then** each claim is attributed to one or more cited evidence items, and every citation refers to evidence actually supplied for that question.
3. **Given** the answer generator cites evidence that was not supplied or produces an answer with no valid citations, **When** the response is processed, **Then** the invalid citations are not shown as valid evidence and the owner is told the answer is not adequately supported.
4. **Given** unchanged question, collection, and settings, **When** the owner repeats the question, **Then** the same evidence set is selected and presented in the same order.

---

### User Story 2 - Decline when evidence is insufficient (Priority: P1)

As the local footage owner, I want the system to say so when the footage does not support an answer, so that I am never given a confident but unsupported statement.

**Why this priority**: Declining is a required behavior of the project constitution (Evidence-Grounded Answers) and is what distinguishes grounded answering from plain generation.

**Independent Test**: Ask questions that the controlled collection cannot answer (an unseen species, a date range with no footage, a question unrelated to wildlife) and confirm each produces a clear "not supported by the footage" outcome with no fabricated citations.

**Acceptance Scenarios**:

1. **Given** a question for which no eligible crops are retrieved, **When** the owner asks, **Then** the system reports that the footage does not provide enough evidence, does not call the answer generator with an empty evidence set, and cites nothing.
2. **Given** retrieved evidence that does not actually address the question, **When** the answer generator determines the evidence is insufficient, **Then** the output states the evidence is insufficient, and any evidence shown is labeled as retrieved but not supporting an answer.
3. **Given** a question about absence (for example "Did a fox ever visit?"), **When** the owner asks, **Then** the answer never asserts that an event did not happen anywhere in the footage; it may only state that none was found in the retrieved evidence.
4. **Given** a question that is not about the footage, **When** the owner asks, **Then** the system declines rather than answering from general knowledge.

---

### User Story 3 - Scope questions with metadata filters and inspect the evidence (Priority: P2)

As the local footage owner, I want to restrict a question to a date range, day or night, or a species, and to see exactly what evidence and settings were used, so that I can target part of my collection and audit how the answer was produced.

**Why this priority**: Filters and transparency improve precision and auditability but depend on the basic answer flow.

**Independent Test**: Ask the same question with each filter alone and combined against a collection with known metadata. Confirm only eligible crops are used as evidence and the output reports the filters, evidence count, and context.

**Acceptance Scenarios**:

1. **Given** optional start date, end date, lighting, and species filters equivalent to those of search, **When** the owner supplies them, **Then** only crops satisfying all filters can be used as evidence and the output states the applied filters.
2. **Given** a question that mentions "at night" or a date in words, **When** no explicit filter is supplied, **Then** no filter is silently added; the wording only influences retrieval.
3. **Given** an answer, **When** the owner inspects the output, **Then** it shows the question, applied filters, number of evidence items supplied, selected collection/tagging context, and per-item provenance including similarity, species decision with confidence, and detection confidence, each distinctly labeled.
4. **Given** a cited crop whose local image is unavailable, **When** results are shown, **Then** the citation remains with its provenance and is marked unavailable.

---

### User Story 4 - Fail clearly and keep private data safe (Priority: P3)

As the local footage owner, I want clear errors and control over what leaves my machine, so that failures are not mistaken for answers and my footage is not uploaded unexpectedly.

**Why this priority**: Operational safety and privacy are required but do not add new question-answering capability.

**Independent Test**: Run with missing credentials, invalid input, unavailable storage, and a failing answer service, and confirm each produces an actionable error distinct from a declined answer.

**Acceptance Scenarios**:

1. **Given** missing or rejected LLM credentials, an unreachable answer service, or an unusable response, **When** the owner asks, **Then** an actionable error is shown, no answer or citation is fabricated, and the failure is distinguishable from a "not enough evidence" outcome.
2. **Given** an empty or whitespace-only question, an invalid filter, or a nonpositive evidence limit, **When** the owner asks, **Then** an input error is reported before any image or text is sent to an external service.
3. **Given** an ask command, **When** it runs, **Then** it states which evidence (crops and metadata) will be sent to the external answer service, and sends nothing beyond the retained crops selected as evidence and their metadata.
4. **Given** error output or logs, **When** the owner reads them, **Then** no credentials are disclosed.

### Edge Cases

- Empty or whitespace-only questions, malformed dates, a start date after the end date, unsupported lighting values, unknown species identifiers, and nonpositive or non-whole-number evidence limits are input errors.
- A valid empty indexed collection or a filter combination with no eligible crops yields a successful "insufficient evidence" outcome, not an error. Unavailable storage, missing model assets, or incompatible representations are errors.
- Many near-identical consecutive frames may fill the evidence set; the answer must not treat them as independent sightings or count visits from them.
- Counting and frequency questions ("how many times", "how often") cannot be answered reliably from a limited evidence set; the answer must state the limits of the evidence or decline rather than present a count as fact.
- Retrieved evidence may be low-similarity or irrelevant; a low-scoring match must not be treated as confirmation.
- Species decisions are suggestions, not verified identity; answers must not present them as certain.
- Answer text that contradicts its cited evidence, or names a species or time absent from the evidence, must not be presented as supported.
- Crops that contain people are excluded upstream; no excluded frame is reopened as extra evidence.
- Evidence whose capture time is unknown must be reported as unknown, never guessed.
- A response that exceeds the allowed amount of evidence or a service time limit is a failure, not a silently shortened answer.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide a local CLI command accepting one nonblank natural-language question about the indexed footage and returning a grounded answer or an explicit decline. It MUST NOT require re-ingesting footage or recomputing stored representations.
- **FR-002**: The system MUST retrieve candidate evidence from the retained indexed crops using the question, applying the same context selection and eligibility rules as search, and MUST pass only that retrieved evidence and its metadata to the answer generator.
- **FR-003**: The user MUST be able to supply optional start and end dates (`YYYY-MM-DD`, inclusive), a day/night restriction, a single species identifier or `unknown`, and a positive whole-number maximum number of evidence items with a documented default. All filters MUST apply before the limit. Question wording MUST NOT silently create or override explicit filters.
- **FR-004**: The answer generator MUST be instructed to answer only from the supplied evidence, to cite the evidence items it uses, and to state when the evidence is insufficient instead of answering from general knowledge.
- **FR-005**: Every answer MUST include citations that each identify a supplied evidence item (crop identity, source video, frame, capture time when known). Citations that do not refer to supplied evidence MUST be rejected and MUST NOT be displayed as supporting evidence.
- **FR-006**: An answer without at least one valid citation MUST NOT be presented as a supported answer; it MUST be reported as insufficient evidence or as an unsupported response.
- **FR-007**: When retrieval returns no eligible evidence, the system MUST report insufficient evidence without contacting the answer generator and without fabricating citations.
- **FR-008**: The system MUST distinguish four outcomes: supported answer, insufficient evidence (decline), input error, and operational failure. Operational failures MUST NOT be reported as declines or answers.
- **FR-009**: Answers MUST NOT assert that an event never occurred or that an animal is absent from the footage; they may only report what was found or not found in the supplied evidence. Answers MUST NOT present species suggestions, detection confidence, or similarity scores as proof of identity or occurrence.
- **FR-010**: Output MUST identify the question, applied filters, evidence limit, number of evidence items supplied, and selected collection and tagging context. Per-item similarity, species decision and confidence, and detection confidence MUST be distinctly labeled.
- **FR-011**: Evidence order and selection MUST be repeatable for an unchanged question, collection, filters, and settings. Unavailable local crop files MUST be marked unavailable without removing their citation provenance.
- **FR-012**: The system MUST validate the question, filters, limit, credentials, and required local resources before sending anything to an external service, and MUST report actionable errors. Credentials MUST come only from environment variables or local untracked configuration and MUST NOT be disclosed in any output.
- **FR-013**: Before external transmission, the system MUST make clear that selected crops and their metadata are sent to the configured answer service, and MUST send nothing else from the footage collection. It MUST NOT send people-containing frames, full source videos, or crops outside the selected evidence set.
- **FR-014**: The command MUST be read-only with respect to source footage, crops, manifests, stored representations, and species decisions.
- **FR-015**: User guidance MUST explain prerequisites, credentials setup, filters, evidence limits, the four outcomes, citation meaning, privacy implications of the external service, and known limitations (counting, absence, near-duplicate frames). Any new settings MUST be inventoried without secrets in `.env.example`.
- **FR-016**: Question handling, evidence selection, prompt assembly, citation validation, decline handling, and outcome classification MUST be testable offline using controlled substitutes for retrieval and the answer generator. The standard test suite MUST require neither an API key, network access, nor private footage.

### Key Entities *(include if feature involves data)*

- **Question Request**: The owner's natural-language question, optional date/lighting/species filters, selected context, and evidence limit.
- **Evidence Item**: One retrieved crop with its identity, source video and frame, capture time and timezone when known, lighting, species decision and confidence, detection confidence, similarity, and image availability; the unit that can be cited.
- **Citation**: A reference from an answer claim to a supplied Evidence Item; valid only if the item was supplied for that question.
- **Answer Outcome**: One of supported answer (text plus valid citations), insufficient evidence (with any non-supporting evidence labeled), input error, or operational failure.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a fixed acceptance set with controlled retrieval and a controlled answer generator, 100% of supported answers include at least one citation and 100% of displayed citations resolve to evidence actually supplied for that question.
- **SC-002**: In acceptance cases where the evidence is empty, irrelevant, or the generator signals insufficiency, 100% produce a decline outcome with no fabricated or invalid citations, and zero calls to the answer generator occur when no evidence is retrieved.
- **SC-003**: Acceptance cases covering each filter alone and combined show 100% of evidence items satisfying every supplied filter, including cases where eligible crops fall outside the unfiltered top results.
- **SC-004**: All input-error and operational-failure acceptance cases (blank question, invalid filters, missing credentials, unreachable service, malformed response) produce an actionable message distinguishable from a decline, with no credentials disclosed.
- **SC-005**: Repeated identical questions against an unchanged collection select the same evidence in the same order in 100% of acceptance cases, and repeated runs change no stored data.
- **SC-006**: Before answer-quality claims are published, a documented evaluation covers a small labeled question set (at least a handful of answerable questions and several that the footage cannot answer) and reports the number of correct answers, correct citations, and correct declines, with failure cases. Controlled correctness tests MUST NOT be presented as measured real-world answer quality.
- **SC-007**: The owner can go from a question to an answer or decline, with citations they can inspect, in a single command invocation.

## Assumptions

- The user is the single local footage owner using the existing CLI. Ingestion, indexing, and search provide retained crops, compatible representations, species decisions, and provenance, and the search eligibility and filter semantics are reused.
- Evidence is crop-level with source-frame references; full frames need not exist. Viewing or exporting images is outside this feature.
- Answer generation uses a vision-capable external LLM service reached with credentials from environment variables; the specific provider, model, prompt design, and command options belong to planning.
- The default evidence limit is small enough to keep each request modest; the exact value is chosen during planning and documented.
- Questions are single-turn. Conversation history, follow-up questions, streaming output, UI, authentication, multi-user support, cloud deployment, agent behavior, and tool use are out of scope.
- Visit aggregation, tracking across frames, text-to-SQL over structured logs, and exact counting or frequency analysis are out of scope; answers must acknowledge these limits.
- Sending crops to an external service is acceptable to the owner when explicitly configured; it does not guarantee anonymity beyond upstream person filtering.
- Systematic answer-quality evaluation belongs to the separate Evaluate feature; this feature only guarantees grounding, citation validity, and decline behavior, not unmeasured semantic accuracy.

