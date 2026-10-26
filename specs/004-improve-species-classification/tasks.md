---
description: "Actionable tasks for improving wildlife species classification"
---

# Tasks: Improve Wildlife Species Classification

**Input**: Design documents from `/specs/004-improve-species-classification/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`, and `quickstart.md`.

**Tests**: Tests are included because FR-018 requires controlled offline verification of core logic and the quickstart specifies unit and opted-in migration validation.

**Organization**: Tasks are grouped by the five prioritized user stories. The existing Python project, CLI, test layout, review utilities, and initial database migration are reused; no project initialization or new dependency task is required.

## Phase 1: Setup

**Purpose**: Reuse the existing project structure and offline test environment. Keep footage, crops, labels, references, and generated reports outside the repository as specified in the quickstart.

No additional setup tasks are required.

---

## Phase 2: Foundational

**Purpose**: There is no new shared service or infrastructure prerequisite. The existing CLI, canonical identity/persistence patterns, fake encoders/stores, and migration framework are extended by the story tasks below.

No separate blocking foundational tasks are required.

---

## Phase 3: User Story 1 - Measure Classification Quality (Priority: P1) 🎯 MVP

**Goal**: Create candidate-independent blind labels and compare immutable runs against the same reviewed cases, with lighting-stratified results and limitations.

**Independent Test**: With generated inspect records and controlled persisted decisions, convert a blind review CSV to shared labels, evaluate two runs against one-to-one `case_id` matches, and verify day/night/unknown metrics, paired changes, out-of-list/category handling, null empty denominators, and insufficient-sample warnings. Existing schema-1 labels and reports remain readable.

### Implementation and tests for User Story 1

- [ ] T001 [P] [US1] Extend deterministic stratified sampling, repeated `--source-id` filtering, shared label conversion, split-key hashing, and `case_id` preservation in `tools/review_csv.py`; cover selection limits, role/split validation, and duplicate/ambiguous case handling in `tests/unit/test_review_csv.py`.
- [ ] T002 [P] [US1] Extend the existing blind review vocabulary and label choices for `species`, `out_of_list`, `unidentifiable`, and `unusable`, with optional `expected_category`, in `tools/review_crops.py`; test legacy mappings and blind/local-only behavior in `tests/unit/test_review_crops.py`.
- [ ] T003 [US1] Extend label validation, setup-specific one-to-one case matching, lighting-stratified metrics, paired outcome changes, held-out/sample-size gates, and legacy report compatibility in `src/bird_recognition/embed/evaluation.py`; test shared and schema-1 reports, unmatched/ambiguous cases, category-versus-species accounting, and undefined denominators in `tests/unit/embed/test_evaluation.py`.
- [ ] T004 [US1] Add `compare-species` CLI parsing/dispatch and extend `evaluate-species` to accept shared labels while retaining legacy inputs in `src/bird_recognition/cli.py`; test required options, explicit run selection, report output, and privacy/path refusal in `tests/unit/embed/test_cli.py`.
- [ ] T005 [US1] Preserve source-content digest, frame, detection ID, original detector-box coordinates, and stable crop-independent `case_id` through manifest records and inspection exports in `src/bird_recognition/ingest/manifest.py`, `src/bird_recognition/embed/manifest.py`, and `src/bird_recognition/cli.py`; verify identity stability across crop policies and non-matches after source/detection changes in `tests/unit/ingest/test_manifest.py` and `tests/unit/embed/test_manifest.py`.

**Checkpoint**: A held-out reviewed cohort can measure the existing zero-shot baseline and compare a later run without leaking predictions into review or binding labels to candidate IDs.

---

## Phase 4: User Story 2 - Improve the Local Candidate Vocabulary (Priority: P1)

**Goal**: Support validated local species and explicit broad bird/mammal candidates, versioned taxonomy-aware prompts, and inspectable category-level outcomes.

**Independent Test**: Load schema-1 and schema-2 candidate files; verify strict validation, stable fingerprints, exact prompt text, historical prompt reproduction, and separate species/category outcomes. Evaluate known species absent from a setup without treating a category match as exact species correctness.

### Implementation and tests for User Story 2

- [ ] T006 [P] [US2] Add typed species/category candidate representations and canonical candidate-set content in `src/bird_recognition/embed/models.py`; test required fields, stable IDs, uniqueness, supported kinds, and schema-1 compatibility in `tests/unit/embed/test_models.py`.
- [ ] T007 [US2] Parse strict schema-2 species files, reject duplicate JSON keys/unknown fields, generate the exact versioned common-name-plus-taxonomy prompt, and fingerprint prompt/candidate content in `src/bird_recognition/embed/config.py`; test order stability, content changes, broad bird/mammal requirements, and legacy prompt identity in `tests/unit/embed/test_config.py`.
- [ ] T008 [US2] Thread typed candidates and prompt identity through indexing, persisted score maps, and inspection output in `src/bird_recognition/embed/pipeline.py`, `src/bird_recognition/embed/storage.py`, and `src/bird_recognition/cli.py`; test that a category assignment is explicitly coarse and absent species candidates remain measurable in `tests/unit/embed/test_pipeline.py` and `tests/unit/embed/test_evaluation.py`.
- [ ] T009 [US2] Update the example candidate file and user-facing candidate/prompt documentation in `species.json.example` and `docs/usage.md`; retain the old schema-1 example/reading path as a reproducible baseline.

**Checkpoint**: Candidate vocabulary and prompts can evolve as immutable setups, and broad category predictions cannot be mistaken for species identifications.

---

## Phase 5: User Story 3 - Preserve Useful Animal Detail in Reviewed Crops (Priority: P2)

**Goal**: Produce bounded context-aware crops, preserve rectangular image detail in model input, and distinguish low-quality crops without changing historical outputs.

**Independent Test**: Use generated edge, elongated, and undersized detections to verify frame-bounded geometry, preserved image details in fit/pad input, distinct crop/settings identities, and a low-quality unassigned result. Existing crop files and historical decisions remain unchanged.

### Implementation and tests for User Story 3

- [ ] T010 [P] [US3] Add versioned crop-context/policy settings and include effective values in ingestion identity in `src/bird_recognition/ingest/models.py`, `src/bird_recognition/ingest/manifest.py`, and `src/bird_recognition/ingest/pipeline.py`; test changed settings create distinct output/crop identities without overwriting old rows in `tests/unit/ingest/test_manifest.py` and `tests/unit/ingest/test_pipeline.py`.
- [ ] T011 [P] [US3] Expand detector boxes proportionally, clip to source bounds, and retain the expanded rectangle in `src/bird_recognition/ingest/crops.py`; test frame-edge and elongated geometry with generated images in `tests/unit/ingest/test_crops.py`.
- [ ] T012 [US3] Implement versioned full-image fit/pad preprocessing and include its fingerprint in image-representation reuse identity in `src/bird_recognition/embed/bioclip.py`, `src/bird_recognition/embed/models.py`, and `src/bird_recognition/embed/pipeline.py`; test no center-crop, no distortion, and no incompatible vector reuse in `tests/unit/embed/test_bioclip.py` and `tests/unit/embed/test_pipeline.py`.
- [ ] T013 [US3] Add minimum width/height quality checks and completed `low_quality` unassigned outcomes, report accounting, and inspection details in `src/bird_recognition/embed/pipeline.py`, `src/bird_recognition/embed/models.py`, and `src/bird_recognition/embed/evaluation.py`; test empty score maps, no assignment, and separation from inference failures in `tests/unit/embed/test_pipeline.py` and `tests/unit/embed/test_evaluation.py`.

**Checkpoint**: Changed crop or model-input settings create distinct, inspectable inputs; tiny crops are not presented as reliable classifications.

---

## Phase 6: User Story 4 - Adapt Classification to Reviewed Local Examples (Priority: P2)

**Goal**: Offer opt-in reference-assisted classification with verified train/evaluation separation, zero-shot fallback, and bounded model benchmarking without automatic model replacement.

**Independent Test**: Use generated embeddings and manifests with disjoint and overlapping source/day splits. Verify accepted consistent references, weak/inconsistent fallback with recorded decision paths, failure on unverifiable splits, and benchmark reports containing sample identity and elapsed time without changing the active model.

### Implementation and tests for User Story 4

- [ ] T014 [P] [US4] Add an external reference-manifest loader, canonical fingerprinting, split validation, top-five cosine matching, minimum-three-neighbor/agreement checks, and zero-shot fallback logic in `src/bird_recognition/embed/reference.py`; test leakage rejection, accepted matches, and fallback using controlled vectors in `tests/unit/embed/test_reference.py`.
- [ ] T015 [US4] Integrate opt-in reference embeddings, compatible model/input identity checks, decision-path provenance, and explicit CLI reference options without changing the default zero-shot path in `src/bird_recognition/embed/pipeline.py`, `src/bird_recognition/embed/config.py`, `src/bird_recognition/embed/models.py`, and `src/bird_recognition/cli.py`; test unchanged baseline behavior and path recording in `tests/unit/embed/test_pipeline.py` and `tests/unit/embed/test_cli.py`.
- [ ] T016 [US4] Add explicit bounded benchmark execution with a required positive crop cap of at most 500, quality evaluation, elapsed-time reporting, and no model auto-selection in `src/bird_recognition/embed/evaluation.py` and `src/bird_recognition/cli.py`; test caps, unsupported local adapters, report identity, and unchanged selected model in `tests/unit/embed/test_cli.py` and `tests/unit/embed/test_evaluation.py`.

**Checkpoint**: Reference mode is opt-in and split-safe, and benchmark results are attributable and cannot silently change the active setup.

---

## Phase 7: User Story 5 - Withhold Uncertain Decisions and Use Repeated Frames (Priority: P3)

**Goal**: Reject narrow score leads independently of the existing threshold and provide explicitly grouped visit summaries without replacing crop-level decisions.

**Independent Test**: Exercise clear lead, narrow lead, below-threshold, and exact-tie score maps, then aggregate explicit compatible groups using mean logits. Verify rejection reasons/competing candidates, deterministic visit results, all source links, and unchanged crop decisions; uncertain/cross-video groups are rejected.

### Implementation and tests for User Story 5

- [ ] T017 [US5] Add optional minimum-margin configuration/fingerprinting and independent threshold, margin, and tie decision reasons in `src/bird_recognition/embed/config.py`, `src/bird_recognition/embed/scoring.py`, and `src/bird_recognition/embed/models.py`; test one-candidate rejection when margin is enabled, narrow/clear leads, below-threshold results, exact ties, and retained candidate scores in `tests/unit/embed/test_scoring.py` and `tests/unit/embed/test_config.py`.
- [ ] T018 [US5] Add explicit versioned visit-group manifest validation and deterministic mean-logit aggregation with threshold/margin reapplication in `src/bird_recognition/embed/visits.py`; test minimum group size, unique crop membership, source/setup compatibility, uncertain-group rejection, deterministic results, and contributor links in `tests/unit/embed/test_visits.py`.
- [ ] T019 [US5] Add `aggregate-visits` CLI input/output handling and report serialization while preserving every crop-level result in `src/bird_recognition/cli.py` and `src/bird_recognition/embed/visits.py`; test explicit run selection, external atomic output, links, and refusal of unsafe/overwrite destinations in `tests/unit/embed/test_cli.py` and `tests/unit/embed/test_visits.py`.

**Checkpoint**: Individual assignments require both configured gates; visit outcomes are separate derived results and never infer grouping from video membership alone.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Complete additive persistence, CLI contract coverage, privacy checks, historical compatibility, and offline validation across all stories.

- [ ] T020 Add a forward-only migration for candidate kinds/descriptions, setup and prompt identities, representation/input-view identity, low-quality and margin reasons, and optional reference/visit decision provenance in `src/bird_recognition/embed/migrations/002_species_classification.sql`; preserve existing rows and validate the upgrade with `tests/integration/embed/test_migrations.py`.
- [ ] T021 Extend storage read/write validation for new setup fields, candidate compatibility, score maps, low-quality completion counts, and decision provenance in `src/bird_recognition/embed/storage.py`; cover database constraints and historical records in `tests/integration/embed/test_storage.py`.
- [ ] T022 Add end-to-end offline CLI coverage for baseline evaluation, shared-label comparison, candidate/prompt changes, crop-quality outcomes, reference fallback, margin decisions, and visit reports in `tests/unit/embed/test_cli.py` and `tests/integration/embed/test_species_classification.py`.
- [ ] T023 Add/report privacy and interpretation safeguards for external labels, references, benchmark/quality/visit reports, relative scores, out-of-list risk, day/night differences, null denominators, and held-out limitations in `src/bird_recognition/embed/evaluation.py`, `src/bird_recognition/cli.py`, and `tests/unit/embed/test_evaluation.py`.
- [ ] T024 Validate the documented offline workflow and exact CLI examples against implemented options; update `specs/004-improve-species-classification/quickstart.md` and `specs/004-improve-species-classification/contracts/cli.md` for any contract corrections without including private assets or reports.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Existing project/package/test structure is reused; no setup task blocks implementation.
- **Foundational (Phase 2)**: No separate foundation is needed; the feature extends existing identities and persistence patterns.
- **User Stories (Phases 3–7)**: Implement in priority/plan order. US1 establishes candidate-independent cases, held-out labels, and the comparison baseline. US2 builds on that comparison path. US3 can be implemented independently after the shared identity contract is established. US4 requires stable run/model/input identities and evaluation; US5 requires persisted score maps and compatible setup identities.
- **Polish (Phase 8)**: Depends on the story contracts being implemented; completes persistence, compatibility, privacy, and end-to-end validation.

### User Story Dependencies

- **US1 (P1)**: No feature dependency; MVP. Establish the baseline and shared-label comparison first.
- **US2 (P1)**: Depends on US1's setup comparison and candidate-independent labels to measure vocabulary changes fairly.
- **US3 (P2)**: Depends on US1's stable case identity for crop-policy comparisons; otherwise independent of US2.
- **US4 (P2)**: Depends on the stable identities/evaluation path from US1 and compatible candidate/model/input identities from US2/US3.
- **US5 (P3)**: Margin gating can follow persisted scores from US2; visit aggregation follows margin behavior and requires compatible score/setup identities from US3.
- **Polish**: Requires all selected story behavior to be in place before final migration, integration, and CLI contract validation.

### Parallel Opportunities

- **US1**: T001 and T002 edit separate review utilities and can proceed in parallel; evaluation logic/tests can be developed against the shared-label contract independently, while CLI integration waits for T003.
- **US2**: Candidate model/schema tests can proceed before prompt/config integration; keep `models.py` and `config.py` work sequenced where the latter imports the former.
- **US3**: T010/T011 ingestion crop work and T012 model-input preparation touch separate ingestion versus embedding paths and can proceed in parallel once US1 case identity is stable.
- **US4**: Reference matching in T014 is isolated from the bounded benchmark CLI/report work in T016; T015 integrates reference matching after T014.
- **US5**: Implement margin/scoring before visit aggregation; visit manifest validation can be built separately from CLI serialization, but T019 depends on T018.
- **Across stories**: After US1's shared label/case contract is complete, US3 may proceed alongside US2 if separate contributors coordinate interfaces; US4/US5 should wait for their stated identity and scoring prerequisites.

## Parallel Example: User Story 1

```text
Task: T001 Extend shared-label sampling/conversion in tools/review_csv.py and tests/unit/test_review_csv.py
Task: T002 Extend blind label choices in tools/review_crops.py and tests/unit/test_review_crops.py
Task: T003 Implement paired evaluation in src/bird_recognition/embed/evaluation.py and tests/unit/embed/test_evaluation.py
```

## Implementation Strategy

### MVP First (User Story 1)

1. Reuse the existing CLI, review workflow, and unit-test infrastructure.
2. Complete US1 shared labels, stable case identity, baseline evaluation, paired comparison, and legacy compatibility.
3. **Stop and validate** against controlled generated records; confirm day/night/unknown grouping, out-of-list handling, and insufficient-sample behavior before tuning any setup.
4. Establish a held-out real-label baseline only with separately approved local assets/labels; synthetic tests establish correctness, not biological quality.

### Incremental Delivery

1. Deliver US1 to measure a retained zero-shot baseline.
2. Add US2 candidate/prompt revisions and compare to the same labels.
3. Add US3 crop context, input preparation, and quality gates as a separately fingerprinted setup.
4. Add US4 reference assistance and bounded benchmarks as explicit opt-ins.
5. Add US5 margin decisions and explicit visit aggregation without rewriting crop-level history.
6. Complete additive migrations, compatibility checks, privacy/path guards, and offline validation.

## Notes

- Every checklist task has a sequential ID, a required story label in story phases, and concrete source/test/document paths; `[P]` is used only where files can be worked on independently.
- Relative classifier scores and reference similarities are not probabilities. Do not claim setup improvement from synthetic correctness tests, raw coverage, or scores alone.
- Only reviewed held-out real cohorts support biological-quality claims; reports with fewer than 10 reviewed day and 10 reviewed night examples remain insufficient for publication-ready claims.
- Never commit private media, labels, references, embeddings, or generated reports.
