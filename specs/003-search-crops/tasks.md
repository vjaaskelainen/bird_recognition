---
description: "Actionable implementation tasks for local text search over indexed wildlife crops"
---

# Tasks: Text Search over Wildlife Crops

**Input**: Design documents from `/specs/003-search-crops/`

**Prerequisites**: `plan.md`, `spec.md`; supporting decisions and contracts in `research.md`, `data-model.md`, `contracts/cli.md`, and `quickstart.md`.

**Tests**: Include offline unit tests and opt-in PostgreSQL boundary tests as required by the specification. Write tests first and confirm they fail before implementation.

**Organization**: Tasks are grouped by user story to support incremental, independently verifiable delivery.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Reuse existing project infrastructure. No new dependency, database migration, environment setting, or model download is planned.

No setup tasks are required; existing CLI, BioCLIP adapter, PostgreSQL/pgvector store, and test configuration are reused.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared search contracts and configuration before implementing any user story.

- [X] T001 [P] Define transient `SearchRequest`, `SearchContext`, `SearchResult`, `SearchOutcome`, and typed search failure contracts in `src/bird_recognition/embed/models.py`, including query/run identity, filters, context fingerprints, result provenance, and success versus failure outcomes.
- [X] T002 [P] Extend `src/bird_recognition/embed/config.py` to resolve required database URL and local model directory using CLI > process environment > discovered `.env` precedence, with no credential or asset-path built-in defaults.

**Checkpoint**: Shared contracts and local configuration rules are available to all story implementations.

---

## Phase 3: User Story 1 - Find wildlife images with a text query (Priority: P1) 🎯 MVP

**Goal**: Search one explicitly selected indexed run using a nonblank text query and return the exact deterministic top-N crop matches without filters.

**Independent Test**: With controlled query and crop vectors, verify query encoding, finite normalized 512-dimensional vector validation, cosine scores, descending rank, `crop_id` tie-breaking, default/custom limits, source references, valid empty results, and repeatable limit boundaries without a database or model assets.

### Tests for User Story 1

- [ ] T003 [P] [US1] Add offline tests for blank queries, query embedding, vector validation, float64 cosine scoring, stable tie ordering, limits, duplicate identities, and empty outcomes in `tests/unit/embed/test_search.py`.
- [ ] T004 [P] [US1] Add controlled read-only storage tests for selected-run context, compatible representations, and exclusion of failed/pending or cross-run records in `tests/unit/embed/test_storage.py`.
- [ ] T005 [P] [US1] Add CLI tests for the unfiltered `search QUERY --run-id UUID` command, configuration resolution, output, and success/empty/input/operational exit behavior in `tests/unit/embed/test_cli.py`.
- [ ] T006 [P] [US1] Add opt-in PostgreSQL boundary tests for selected-run lookup, compatible crop representations, and read-only search queries in `tests/integration/embed/test_search_storage.py`.

### Implementation for User Story 1

- [ ] T007 [P] [US1] Implement read-only selected-run and compatible crop-representation retrieval in `src/bird_recognition/embed/storage.py`; accept only `complete` or valid `no_input` runs and keep each search within one run and tagging context.
- [ ] T008 [P] [US1] Implement query validation/encoding, exact loaded-model fingerprint matching, 512-dimensional finite nonzero normalized-vector checks, float64 cosine computation clamped only for drift to `[-1, 1]`, validation of all eligible scores, deterministic `crop_id` tie-breaking, and top-N selection in `src/bird_recognition/embed/search.py`.
- [ ] T009 [US1] Add the `search` parser and dispatch in `src/bird_recognition/cli.py` for positional query, required `--run-id`, `--limit` defaulting to 5, database/model configuration, and readable or versioned JSON success/empty/failure outcomes with exit codes 0/1/2.

**Checkpoint**: User Story 1 supports deterministic text search and successful zero-result searches using offline substitutes.

---

## Phase 4: User Story 2 - Narrow results using footage metadata (Priority: P2)

**Goal**: Apply optional inclusive capture-date, exact day/night, and assigned-species filters across the full selected eligible set before ranking and limiting.

**Independent Test**: Using controlled records, test each filter separately and in combination, including boundary/missing dates, unknown lighting/species, best-candidate-only assignments, and matches below the unfiltered top five. Verify a valid no-match filter succeeds with zero results.

### Tests for User Story 2

- [ ] T010 [P] [US2] Add offline tests for strict date parsing/ranges, inclusive recorded calendar-date matching without timezone conversion, missing-date exclusion only under date filtering, day/night matching, assigned species and reserved `unknown`, combined filters before limit, and zero-match success in `tests/unit/embed/test_search.py`.
- [ ] T011 [P] [US2] Add storage tests proving date, lighting, and final-assigned-species predicates are applied to the complete candidate set before result limiting in `tests/unit/embed/test_storage.py`.
- [ ] T012 [P] [US2] Add CLI tests for `--start-date`, `--end-date`, `--lighting`, and `--species-id`, malformed values, and explicit filters remaining independent of query wording in `tests/unit/embed/test_cli.py`.
- [ ] T013 [US2] Extend the opt-in PostgreSQL boundary cases in `tests/integration/embed/test_search_storage.py` to verify combined metadata filters, assigned-species semantics, and filtering before limit.

### Implementation for User Story 2

- [ ] T014 [P] [US2] Validate strict `YYYY-MM-DD` dates, independently optional inclusive bounds, start-before-or-equal-to-end, exact `day`/`night`, known candidate IDs or reserved `unknown`, and positive whole-number limits in `src/bird_recognition/embed/search.py`.
- [ ] T015 [P] [US2] Extend the read-only candidate query in `src/bird_recognition/embed/storage.py` to apply all supplied date, lighting, and final-assigned-species predicates before returning candidates for scoring; never qualify a best-candidate suggestion as an assignment.
- [ ] T016 [US2] Add the four metadata filter options and pass validated explicit values through search dispatch in `src/bird_recognition/cli.py`; do not derive or override filters from query text.

**Checkpoint**: User Story 2 returns only crops satisfying every supplied filter, including eligible matches outside the unfiltered top-N, and treats valid empty matches as success.

---

## Phase 5: User Story 3 - Inspect evidence and understand limitations (Priority: P3)

**Goal**: Preserve crop-level provenance and distinguish similarity, species confidence, and detection confidence, including when the local crop image is unavailable.

**Independent Test**: Inspect controlled results with complete and missing metadata and an unavailable/unreadable crop locator. Confirm stable identities, provenance, explicit unknowns, score guidance, and retained rank/results without image decoding, re-embedding, or answer generation.

### Tests for User Story 3

- [ ] T017 [P] [US3] Add offline tests for result identity/provenance fields, missing metadata, unavailable-image retention, and read-only availability checks in `tests/unit/embed/test_search.py`.
- [ ] T018 [P] [US3] Add storage tests for source/frame, capture-time/timezone, lighting, detection-box/confidence, and selected-context species-decision provenance in `tests/unit/embed/test_storage.py`.
- [ ] T019 [P] [US3] Add CLI tests for complete JSON result fields, explicit null/unknown metadata, distinct score labels and warnings, and unavailable-image representation in `tests/unit/embed/test_cli.py`.

### Implementation for User Story 3

- [ ] T020 [P] [US3] Extend `src/bird_recognition/embed/storage.py` search records with stable crop/snapshot/representation/decision identities and all available source, frame, capture, lighting, detection, and selected-tagging-context provenance.
- [ ] T021 [P] [US3] Add a read-only local crop availability check in `src/bird_recognition/embed/search.py`; retain the match, rank, score, and provenance when the locator is missing or unreadable, without decoding, replacing, or re-embedding the image.
- [ ] T022 [US3] Complete readable and schema-version-1 JSON result formatting in `src/bird_recognition/cli.py`, preserving explicit unknowns and clearly explaining that similarity is relative relevance, species confidence is candidate-relative, and detection confidence is detector output—not proof.

**Checkpoint**: User Story 3 provides inspectable evidence and actionable sanitized failures without turning retrieval scores into identity or occurrence claims.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Document local operation and validate the offline, read-only, and user-facing acceptance criteria.

- [ ] T023 [P] Update `docs/usage.md` with local prerequisites, run/context selection, command examples, configuration precedence, filters and unknown metadata, result inspection, score interpretation, and empty versus failure outcomes.
- [ ] T024 [P] Document the optional privacy-reviewed evaluation procedure in `docs/usage.md`: at least 10 labeled queries, stable crop/frame IDs, top-five hit-rate numerator/denominator, selected context, reviewed target selection, and failure cases; do not claim unmeasured quality.
- [ ] T025 Run the documented offline checks from `specs/003-search-crops/quickstart.md` against `tests/unit/embed/` and verify the search path neither mutates indexed data nor requires network/private assets; run the configured lint and format checks before completion.
- [ ] T026 Validate the opt-in database scenarios in `tests/integration/embed/test_search_storage.py` only against a separately approved disposable local test database; confirm read-only behavior and separation of empty success from missing/incompatible context.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No setup work is required; existing project infrastructure is reused.
- **Foundational (Phase 2)**: T001-T002 define shared contracts and configuration and block all user-story work.
- **User Stories (Phases 3-5)**: US1 follows the foundation; US2 extends US1's search and storage behavior; US3 extends the filtered result path with provenance and inspection semantics.
- **Polish (Phase 6)**: Depends on the stories being delivered and validated.

### User Story Dependencies

- **US1 (P1/MVP)**: Starts after Phase 2; no dependency on later stories.
- **US2 (P2)**: Starts after US1; adds metadata eligibility to working query search.
- **US3 (P3)**: Starts after US2; makes the complete result path and selected filtering context inspectable.

### Parallel Opportunities

- T001 and T002 can proceed in parallel because they edit separate files.
- Within each story, its unit test tasks target separate test files and can be authored in parallel before implementation; US1's opt-in integration test is also separate.
- After each story's tests are in place, its storage, search-service, and CLI implementation tasks can proceed in parallel because they edit separate modules and share the Phase 2 contracts.
- T023 and T024 edit the same documentation file and should be completed together or sequentially, not in parallel. T025 and T026 are distinct validation activities; run T026 only with explicit disposable-database approval.

---

## Parallel Example: User Story 1

```text
# After T001-T002, author these independent tests first:
T003: tests/unit/embed/test_search.py
T004: tests/unit/embed/test_storage.py
T005: tests/unit/embed/test_cli.py
T006: tests/integration/embed/test_search_storage.py

# Once the tests are in place, these separate modules can be implemented in parallel:
T007: src/bird_recognition/embed/storage.py
T008: src/bird_recognition/embed/search.py
T009: src/bird_recognition/cli.py
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 2 shared contracts and configuration.
2. Complete US1 tests and implementation.
3. Validate the independent US1 criteria with offline substitutes; run the optional database boundary test only when its disposable test database is approved.
4. Stop at the US1 checkpoint for a usable, filter-free MVP.

### Incremental Delivery

1. Add US2 metadata filters and validate every filter alone, together, and before limiting.
2. Add US3 provenance and unavailable-image handling without image decoding or score overclaims.
3. Complete documentation and cross-cutting validation; publish no quality claim without the specified reviewed evaluation.

