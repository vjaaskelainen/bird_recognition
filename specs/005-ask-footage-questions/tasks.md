---

description: "Task list for Ask Questions About Footage"
---

# Tasks: Ask Questions About Footage

**Input**: Design documents from `specs/005-ask-footage-questions/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`

**Tests**: Offline tests are required by FR-016 and the project constitution. They must use controlled retrieval and answer-service substitutes and require no API key or network.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated as an increment.

## Phase 1: Setup

**Purpose**: Add the answer-service dependency and inventory its configuration before implementation.

- [X] T001 [P] Obtain explicit dependency-change approval, then add the OpenAI SDK to `pyproject.toml` and synchronize `uv.lock`; do not edit the lockfile manually
- [X] T002 [P] Add empty `BIRD_RECOGNITION_ASK_API_KEY` and `BIRD_RECOGNITION_ASK_MODEL` placeholders with safe descriptions to `.env.example`

---

## Phase 2: Foundational

**Purpose**: Establish the Ask-specific configuration and stable request/evidence boundaries used by the stories.

- [X] T003 [P] Add Ask configuration resolution for API key, model default `gpt-4o-mini`, environment/`.env` precedence, and finite service timeout in `src/bird_recognition/embed/config.py`
- [X] T004 [P] Define validated transient request, evidence, claim/citation, and outcome types with the data-model constraints in `src/bird_recognition/ask.py`

**Checkpoint**: Configuration and request/evidence contracts are ready for story implementation. T001 must be approved and complete before SDK adapter work.

---

## Phase 3: User Story 1 - Get a grounded, cited answer (Priority: P1) 🎯 MVP

**Goal**: Answer a footage question using only selected evidence and provide claim-level citations resolved from the retrieved crops.

**Independent Test**: With fixed fake retrieval results and a fake answer client, verify a supported multi-claim answer cites only supplied evidence and renders crop, source video, frame, and known capture-time provenance.

### Tests for User Story 1

- [X] T005 [P] [US1] Add offline tests for prompt inputs, structured claims, valid and invalid evidence indices, and authoritative citation resolution in `tests/unit/test_ask.py`
- [X] T006 [P] [US1] Add CLI parsing and supported-answer output tests for the Ask command in `tests/unit/test_cli_ask.py`

### Implementation for User Story 1

- [X] T007 [US1] Implement deterministic search-backed evidence selection, selected context retention, and available-crop byte loading in `src/bird_recognition/ask.py`
- [X] T008 [US1] Implement the OpenAI Responses API adapter with strict structured output, base64 selected-crop data URLs, finite timeout, and sanitized failures in `src/bird_recognition/ask.py`
- [X] T009 [US1] Implement evidence-only prompt rules, response-shape validation, request-local citation resolution, and supported/unsupported claim handling in `src/bird_recognition/ask.py`
- [X] T010 [US1] Register the `ask` parser options and dispatch through existing read-only search/storage configuration in `src/bird_recognition/cli.py`
- [X] T011 [US1] Render supported answers and evidence provenance as human-readable output and schema-version-1 JSON in `src/bird_recognition/cli.py`

**Checkpoint**: User Story 1 returns a supported answer only when every displayed claim has valid citations to supplied evidence.

---

## Phase 4: User Story 2 - Decline when evidence is insufficient (Priority: P1)

**Goal**: Decline safely when retrieval or generated evidence is insufficient, without asserting universal absence, exact counts, or visit frequency.

**Independent Test**: With fake retrieval and model responses, verify empty retrieval makes zero answer-service calls, explicit insufficiency returns a decline, and unsupported or invalidly cited claims are never presented as supported.

### Tests for User Story 2

- [X] T012 [P] [US2] Add offline tests for empty retrieval, explicit insufficiency, unrelated questions, invalid citations, absence questions, and count/frequency limits in `tests/unit/test_ask.py`
- [X] T013 [P] [US2] Add CLI tests for decline output, absence of fabricated citations, and successful decline exit codes in `tests/unit/test_cli_ask.py`

### Implementation for User Story 2

- [X] T014 [US2] Return insufficient evidence without invoking the answer client when retrieval is empty, and downgrade responses with unsupported claims in `src/bird_recognition/ask.py`
- [X] T015 [US2] Enforce prompt and outcome rules against universal absence, exact counts/frequency, general-knowledge answers, and species/similarity claims presented as proof in `src/bird_recognition/ask.py`
- [X] T016 [US2] Render decline reasons and any retrieved-but-nonsupporting evidence without valid-support citations in `src/bird_recognition/cli.py`

**Checkpoint**: Empty and explicitly insufficient evidence produce declines, never fabricated citations or operational failures.

---

## Phase 5: User Story 3 - Scope questions with metadata filters and inspect the evidence (Priority: P2)

**Goal**: Apply explicit filters before the evidence limit and expose the exact selected context, settings, and provenance.

**Independent Test**: Test each filter alone and in combination with controlled candidates, including eligible crops outside the unfiltered top results; verify only matching candidates are selected and output identifies all applied filters and evidence metadata.

### Tests for User Story 3

- [X] T017 [P] [US3] Add offline tests for strict date bounds, day/night and species filters, filter-before-limit behavior, deterministic ordering, and unavailable images in `tests/unit/test_ask.py`
- [X] T018 [P] [US3] Add CLI parsing and rendering tests for filters, evidence limit/count, context fingerprints, per-item score labels, unknown capture time, and unavailable crop status in `tests/unit/test_cli_ask.py`

### Implementation for User Story 3

- [X] T019 [US3] Build the existing `SearchRequest` from the question and explicit filters, preserving search's filter-before-limit and deterministic ranking semantics in `src/bird_recognition/ask.py`
- [X] T020 [US3] Render question, filters, evidence limit/count, run and tagging context, separately labeled similarity/species/detection confidence, and unavailable-image provenance in `src/bird_recognition/cli.py`
- [X] T021 [US3] Preserve the search contract's strict inclusive `YYYY-MM-DD` dates, exact `day`/`night` lighting, selected-context species ID or `unknown`, and positive whole-number evidence limit with default 5 in `src/bird_recognition/cli.py`

**Checkpoint**: Every supplied filter constrains evidence before limiting; unchanged inputs yield the same selected evidence order.

---

## Phase 6: User Story 4 - Fail clearly and keep private data safe (Priority: P3)

**Goal**: Distinguish input errors, operational failures, and declines; validate before transmission and disclose exactly what leaves the machine.

**Independent Test**: Exercise blank questions, invalid filters, missing credentials, unavailable local resources, timeout, refusal, incomplete/malformed responses, and verify sanitized failures, exit-code distinction, and transmission notice without leaking credentials or transmitting unselected footage.

### Tests for User Story 4

- [ ] T022 [P] [US4] Add offline tests for blank input, invalid filters/limits, credential preflight, unavailable images, timeout, refusal, incomplete/malformed responses, and secret sanitization in `tests/unit/test_ask.py`
- [ ] T023 [P] [US4] Add CLI tests for input-error and operational-failure JSON envelopes, exit codes, and transmission notices to stderr in JSON mode in `tests/unit/test_cli_ask.py`

### Implementation for User Story 4

- [ ] T024 [US4] Validate the question, filters, limit, credentials, run context, and local resources before external service invocation in `src/bird_recognition/ask.py`
- [ ] T025 [US4] Classify input errors, operational failures, and declines separately and sanitize service, storage, and configuration errors in `src/bird_recognition/ask.py`
- [ ] T026 [US4] Emit the selected-crops-and-metadata transmission notice before service calls and ensure only limited selected evidence is serialized to the answer service in `src/bird_recognition/cli.py`
- [ ] T027 [US4] Document prerequisites, credential setup, filters, limits, outcomes, citation meaning, external transmission, and known limitations in `docs/usage.md`

**Checkpoint**: No input/preflight failure sends data; service failures are actionable and distinct from declines, with no credential disclosure.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Align the feature's acceptance guide with the implemented command and validate the complete increment.

- [X] T028 [P] Update offline and optional local acceptance instructions for the implemented command and outputs in `specs/005-ask-footage-questions/quickstart.md`
- [X] T029 Run focused Ask unit tests and the configured Ruff lint and format checks; fix any Ask-related failures in `tests/unit/test_ask.py`, `tests/unit/test_cli_ask.py`, and `src/bird_recognition/`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 requires explicit dependency-change approval; T002 is independent. SDK adapter implementation is blocked until T001 is complete.
- **Foundational (Phase 2)**: Depends on Setup. T003 and T004 provide shared configuration and transient contracts before the stories.
- **User Stories (Phase 3+)**: Depend on the Foundational phase. Stories may proceed independently after that phase, subject to shared-file coordination.
- **Polish (Phase 7)**: Depends on all desired stories being complete.

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational. Delivers the MVP grounded-answer path.
- **User Story 2 (P1)**: Can start after Foundational; implements decline handling on the Ask flow without requiring User Story 1 output rendering to be complete.
- **User Story 3 (P2)**: Can start after Foundational; reuses existing search filter semantics and does not depend on a supported answer being generated.
- **User Story 4 (P3)**: Can start after Foundational; operational behavior wraps the same retrieval and answer-service boundary.

### Within Each User Story

- Write and run controlled tests before implementing the corresponding behavior.
- Preserve request-local evidence indices and resolve citation provenance only from selected local results.
- Keep each story independently testable with fake search and answer-client implementations.
- Coordinate changes to the shared `src/bird_recognition/ask.py`, `src/bird_recognition/cli.py`, and test modules when stories are implemented in parallel.

### Parallel Opportunities

- T001 and T002 can proceed independently, although SDK-related implementation waits for T001 approval/completion.
- Within each story, the two test tasks target separate test modules only where explicitly marked `[P]`; implementation tasks that touch a shared file remain sequential.
- After Foundational, different user stories can be implemented by separate contributors with coordination on the shared Ask and CLI files.
- T028 can be drafted independently of source implementation once CLI behavior is settled; T029 is a final validation task.

---

## Parallel Example: User Story 1

```text
Task: "Add offline tests for prompt inputs, structured claims, valid and invalid evidence indices, and authoritative citation resolution in tests/unit/test_ask.py"
Task: "Add CLI parsing and supported-answer output tests for the Ask command in tests/unit/test_cli_ask.py"
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational tasks, including explicit approval before changing dependencies.
2. Complete User Story 1's offline tests and grounded retrieval/answer/citation path.
3. Validate supported answers independently with controlled substitutes.
4. Deliver the single-command MVP; add decline behavior, filters/transparency, and operational/privacy safeguards in their story increments.

### Incremental Delivery

1. Complete Setup + Foundational → shared request and configuration boundaries ready.
2. Add User Story 1 → validate supported answers and citations.
3. Add User Story 2 → validate safe declines and unsupported-answer handling.
4. Add User Story 3 → validate filters, context, and auditable evidence display.
5. Add User Story 4 → validate preflight, failure distinctions, and privacy disclosure.
6. Complete Polish → update quickstart and run focused tests and Ruff checks.

## Notes

- `[P]` marks work that can be performed in parallel without editing the same file or depending on incomplete tasks.
- `[US1]` through `[US4]` map to the prioritized stories in `specs/005-ask-footage-questions/spec.md`.
- The OpenAI SDK dependency change requires explicit approval; no dependency manifest or lockfile change is authorized by task generation.
- No tests in this plan may require an API key, network access, private footage, or private model assets.
