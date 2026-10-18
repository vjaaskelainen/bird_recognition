# Tasks: Ingest Trail-Camera Videos

**Input**: Design documents from `/specs/001-ingest-videos/` (`spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/cli.md`, `quickstart.md`)

**Tests**: Included because FR-014 requires core behavior to be verifiable with local fixtures and controlled detections, without external services or credentials. For each story, add the tests first and confirm they fail before implementing that story.

**Organization**: Tasks are grouped by user story, in priority order. The common settings/types and output safety validation are foundational prerequisites.

## Phase 1: Setup

**Purpose**: Add only the runtime/test dependencies and package/test structure needed by the planned CLI workflow.

- [X] T001 Verify the official MegaDetector inference API/model format and PyTorch, PyAV, Pillow, and pytest compatibility on Python 3.14; declare the tested runtime/development dependency constraints in `pyproject.toml`. Do not edit `uv.lock`; request owner-run `uv sync` per `AGENTS.md`. **Validated 2026-10-18** on Windows/Python 3.14 after owner-run sync: PyTorch 2.14.1, PyAV 19.0.1, Pillow 12.3.0, PyTorch-Wildlife 1.3.0, pytest 9.1.1; real V6 smoke and full pytest suite passed. See `megadetector-v6-upgrade-plan.md`.
- [X] T002 Create the planned ingestion package and test package structure with `src/bird_recognition/ingest/__init__.py` and `tests/ingest/__init__.py`.
- [X] T003 [P] Add reusable tiny synthetic video/frame fixtures and deterministic fake-detector helpers in `tests/ingest/conftest.py`; fixtures must not contain private footage or require model weights/network access.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish shared validated settings, record types, and privacy-safe output path handling before user-story implementation.

- [X] T004 Implement shared typed records, enums, settings, and domain errors in `src/bird_recognition/ingest/models.py`; validate that sampling interval is positive and finite, thresholds are finite in `[0,1]`, confidence is finite in `[0,1]`, dimensions are positive, and frame numbers are non-negative.
- [X] T005 Implement input/output canonicalization and destination safety checks in `src/bird_recognition/cli.py`; reject output that overlaps the input tree or resolves to Git-tracked content, without relying on basenames for identity.

**Checkpoint**: Settings and privacy/path invariants are reusable by all user stories.

---

## Phase 3: User Story 1 - Produce Privacy-Filtered Animal Crops (Priority: P1) 🎯 MVP

**Goal**: Ingest local videos and retain one crop per qualifying animal detection only from complete sampled frames with no qualifying person detection.

**Independent Test**: Use a short local fixture plus controlled detections for animals, empty scenes, vehicles, people, mixed animal/person scenes, confidence equal to/below threshold, and invalid boxes. Confirm expected crops and mutually exclusive frame outcomes without indexing or search.

### Tests for User Story 1

- [x] T006 [P] \[US1\] Add PTS sampling tests for elapsed-time-zero sampling, requested interval, actual frame ordinal/time, variable frame timing, short clips, and corrupt/missing sampled-frame handling in `tests/ingest/test_sampling.py`.
- [x] T007 [P] \[US1\] Add controlled-detection tests for animal/person/other categories, inclusive category thresholds, person precedence, empty/vehicle-only frames, and no retention after detection failure in `tests/ingest/test_filtering.py`.
- [x] T008 [P] \[US1\] Add crop geometry tests for clipped boxes, positive-area validation, pixel-coordinate mapping, and right/bottom-exclusive image regions in `tests/ingest/test_crops.py`.
- [x] T009 [P] \[US1\] Add initial command tests for required paths, numeric validation, help, and processing a small fixture with an injected detector in `tests/ingest/test_cli.py`.

### Implementation for User Story 1

- [X] T010 [P] \[US1\] Implement single-pass PyAV frame decoding and elapsed-time target sampling with PTS-derived seconds, zero-based decoded frame numbers, VFR handling, short-video first-frame behavior, and safe handling of corrupt or missing sampled-frame timing in `src/bird_recognition/ingest/video.py`.
- [x] T011 [P] \[US1\] Implement a detector protocol and local pretrained MegaDetector adapter in `src/bird_recognition/ingest/detection.py`; initialize once per run, normalize outputs to `animal`/`person`/`other`, record model identity/version and SHA-256, and fail closed on load or inference errors without downloading weights.
- [X] T012 [P] \[US1\] Implement box validation/clipping and deterministic local crop encoding in `src/bird_recognition/ingest/crops.py`; store each box as clipped original-frame pixel coordinates `(left, top, right, bottom)` with right/bottom exclusive, reject malformed or zero-area regions, and stage/publish one frame's crops as a complete set or publish none.
- [X] T013 \[US1\] Implement the sampled-frame filtering pipeline in `src/bird_recognition/ingest/pipeline.py`; evaluate each complete frame once, apply inclusive separate thresholds, give qualifying people precedence, discard no-animal/vehicle-only frames, publish no image for person-excluded or failed-detection frames, and report a crop/storage failure without exposing a partial frame result.
- [X] T014 \[US1\] Implement the `ingest` argparse command, default interval/threshold values, preflight validation, model configuration, readable help, and the `bird-recognition` console entry point in `src/bird_recognition/cli.py` and `pyproject.toml`.
- [x] T015 \[US1\] Integrate fixture decoding, controlled detection, and crop assertions in `tests/ingest/test_cli.py`; verify a frame with multiple safe animal detections yields separate crops and a mixed person/animal frame yields none.

**Checkpoint**: User Story 1 produces local privacy-filtered crops and can be tested without a model service or database service.

---

## Phase 4: User Story 2 - Trace Every Crop to Its Source (Priority: P2)

**Goal**: Persist complete, stable provenance for each crop, including timing, lighting, source/frame identity, confidence, and exact image-region box.

**Independent Test**: Ingest known daylight, infrared-night, ambiguous-lighting, reliable-time, and missing/ambiguous-time fixtures. Inspect the persisted manifest and reconstruct each crop's exact frame, timing, source, and region.

### Tests for User Story 2

- [ ] T016 [P] \[US2\] Add manifest/model tests for required crop provenance, foreign-key relationships, confidence and box constraints, timezone-unknown representation, and common frame lighting across crops in `tests/ingest/test_metadata.py`.
- [ ] T017 [P] \[US2\] Add capture-time tests for reliable offset timestamps plus elapsed PTS time, local time with unknown timezone, missing/malformed/conflicting metadata, and no filesystem-time fallback in `tests/ingest/test_capture_time.py`.
- [ ] T018 [P] \[US2\] Add verified color-day, infrared-night, and ambiguous-image tests for the deterministic lighting classifier in `tests/ingest/test_lighting.py`.
- [ ] T019 [P] \[US2\] Add persistence tests that reopen the output manifest, verify crop file hashes/locations and original-frame boxes, and ensure crop rows never point to missing images in `tests/ingest/test_storage.py`.

### Implementation for User Story 2

- [X] T020 \[US2\] Implement the SQLite schema and repository operations for `IngestionRun`, `SourceVideo`, `RunSource`, `SampledFrame`, `Detection`, and `AnimalCrop` in `src/bird_recognition/ingest/manifest.py`; enforce run status `running`/`complete`/`no_input`/`partial_failure`/`failed`, source status `processed`/`already_processed`/`failed`, non-negative run-source counts whose frame outcomes reconcile to sampled count, zero-based non-negative frame numbers and elapsed seconds, positive frame dimensions, frame outcome exactly `person_excluded`/`no_animal`/`retained`/`failed` with failure reason required for `failed`, detection category `animal`/`person`/`other`, finite confidence in `[0,1]` and inclusive threshold qualification, normalized validated boxes, and crop paths confined to output root with non-empty clipped exclusive-right/bottom pixel boxes matching positive original frame dimensions and saved image region. Preserve null capture time/timezone as explicit unknown and link crops to source/frame/detection/run/settings.
- [X] T021 \[US2\] Implement a deterministic versioned image-evidence day/night classifier in `src/bird_recognition/ingest/lighting.py`; classify uncertain/conflicting evidence as `unknown` and expose the classifier rule/version/thresholds for run settings.
- [X] T022 \[US2\] Extend video metadata extraction in `src/bird_recognition/ingest/video.py` to parse only recognized reliable capture-start metadata, preserve explicit timezone offsets, represent timezone ambiguity as unknown, and never use filename, file modification, or ingestion time.
- [X] T023 \[US2\] Extend crop/run orchestration in `src/bird_recognition/ingest/pipeline.py` to persist all required data-model fields, link each crop to its source/frame/detection/run/settings, share lighting and frame dimensions, and compute stable source/settings/crop identities; preserve operational run time as distinct from capture time and retain explicit unknown capture time/timezone instead of filesystem or ingestion-time fallbacks.
- [X] T024 \[US2\] Implement frame-level staged image publication and SQLite transaction coordination in `src/bird_recognition/ingest/crops.py` and `src/bird_recognition/ingest/manifest.py`; commit all frame crops/records together only after every image and metadata record is complete, otherwise expose none as successful.
- [ ] T025 \[US2\] Add end-to-end provenance tests that reopen a completed run and verify timestamp derivation, explicit unknowns, lighting, detection confidence, image dimensions, and crop region equality in `tests/ingest/test_cli.py`.

**Checkpoint**: Each retained crop is durable and independently traceable to its original source frame and effective run settings.

---

## Phase 5: User Story 3 - Complete and Review a Local Batch (Priority: P3)

**Goal**: Process recursive local batches safely, report partial failures and reconciled totals, recover from interruption, and skip unchanged successful work without collisions or overwrites.

**Independent Test**: Process a directory containing valid, unreadable, and same-basename/different-directory videos; repeat unchanged successful inputs; then change source contents/settings and inject frame/storage failures. Verify statuses, no duplicate outputs, no partial frame publication, and exact outcome-count reconciliation.

### Tests for User Story 3

- [ ] T026 [P] \[US3\] Add unchanged-rerun, changed-content/settings, and same-basename collision tests in `tests/ingest/test_idempotence.py`.
- [ ] T027 [P] \[US3\] Add mixed readable/unreadable batch, per-frame failure, crop-write failure, interrupted-publication recovery, and frame-count reconciliation tests in `tests/ingest/test_batch.py`.
- [ ] T028 [P] \[US3\] Add CLI tests for empty input, source/frame summaries, partial/total failure status, and exit codes `0`, `1`, and `2` in `tests/ingest/test_cli.py`.

### Implementation for User Story 3

- [X] T029 \[US3\] Implement deterministic recursive discovery, case-insensitive supported extensions, canonical-path ordering, full source SHA-256, and path-plus-content source fingerprints in `src/bird_recognition/ingest/video.py`.
- [X] T030 \[US3\] Implement completed-source lookup by destination, source fingerprint, and effective settings fingerprint in `src/bird_recognition/ingest/manifest.py`; skip identical successful work, retain distinct results for changed work, and never overwrite prior output.
- [X] T031 \[US3\] Implement destination writer locking, stale staging cleanup, orphan crop-directory reconciliation, and rollback/cleanup of failed frame publication in `src/bird_recognition/ingest/manifest.py` and `src/bird_recognition/ingest/crops.py`.
- [X] T032 \[US3\] Implement batch/source/frame failure isolation and run summary accounting in `src/bird_recognition/ingest/pipeline.py`; report processed/skipped/failed videos, sampled frames, each mutually exclusive frame outcome, and crops as a separate count.
- [X] T033 \[US3\] Complete CLI preflight, no-input messaging, per-source actionable errors, summary rendering, and exit-code mapping in `src/bird_recognition/cli.py`; reject invalid values/unsafe paths before producing outputs.
- [ ] T034 \[US3\] Complete fixture-driven batch and recovery integration tests in `tests/ingest/test_batch.py`; assert sampled-frame totals equal person-excluded + no-animal + retained + failed, with no crop files/records for person-excluded or failed frames.

**Checkpoint**: A local owner can review a complete/partial batch and safely repeat or recover it without duplicate or incomplete results.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Document safe operation and verify the full feature without weakening privacy or offline testability.

- [X] T035 [P] Document installation/model provisioning, supported video formats, defaults, CLI examples, output safety, privacy limitations, and batch summary interpretation in `README.md` and `specs/001-ingest-videos/quickstart.md`.
- [ ] T036 Run the documented quickstart scenarios and the complete pytest, Ruff lint, and Ruff format checks from `README.md`; fix feature regressions in the corresponding `src/bird_recognition/ingest/`, `src/bird_recognition/cli.py`, and `tests/ingest/` files. Full pytest passed 2026-10-18; documented CLI quickstart and Ruff lint/format checks remain to be recorded.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001-T003; T001 and T002 can begin in parallel, while T003 follows creation of `tests/ingest/` by T002.
- **Foundational (Phase 2)**: T004-T005 depend on the package structure; both block all user stories.
- **User Stories (Phases 3-5)**: Execute in priority order. Each story's tests are written first and should fail before its implementation begins.
- **Polish (Phase 6)**: Depends on all selected user stories being complete.

### User Story Dependencies

- **US1 (P1)**: Starts after Phase 2; no dependency on another story. Delivers the MVP crop workflow.
- **US2 (P2)**: Builds on US1's sampled-frame, detection, crop, and CLI behavior to add complete persistent provenance.
- **US3 (P3)**: Builds on the persisted records and frame-level publication from US2 to add safe repeat processing, recovery, and batch reporting.

### Within Each Story

- Write that story's fixture-based tests before implementation and verify the expected failures.
- Implement independent modules in parallel only where marked `[P]`; integrate after their prerequisites are complete.
- Preserve the privacy invariant at every checkpoint: a qualifying person or incomplete detection prevents all image retention from that frame.

### Parallel Opportunities

- **Setup**: T001 and T002 can run in parallel; T003 follows T002.
- **US1 tests**: T006-T009 can run in parallel after the shared fixture helpers exist. Implementations T010-T012 touch separate files and can run in parallel after Phase 2 and test contracts are agreed; T013 follows them; T014 follows T013; T015 validates the integration.
- **US2 tests**: T016-T019 can run in parallel. T020-T022 touch distinct files and may proceed in parallel after US1; T023 follows those data services, T024 follows T023, and T025 verifies integration.
- **US3 tests**: T026-T028 can run in parallel after US2. T029 and T030 may run in parallel after the tests; T031 follows T030 because both change `manifest.py`, then T032 follows storage/idempotence, T033 follows T032, and T034 validates recovery/reporting.
- **Polish**: Update `README.md` and `quickstart.md` in T035 after interfaces stabilize; T036 runs the documented quickstart and quality checks after T035.

## Parallel Example: User Story 1

```text
After Phase 2, author the independent tests in parallel:
T006 tests/ingest/test_sampling.py
T007 tests/ingest/test_filtering.py
T008 tests/ingest/test_crops.py
T009 tests/ingest/test_cli.py

Then implement independent modules in parallel:
T010 src/bird_recognition/ingest/video.py
T011 src/bird_recognition/ingest/detection.py
T012 src/bird_recognition/ingest/crops.py

Integrate filtering and command after module contracts are complete:
T013 src/bird_recognition/ingest/pipeline.py
T014 src/bird_recognition/cli.py
```

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Setup and Foundational phases.
2. Complete User Story 1 tests first, then its video/detector/crop/filtering/CLI implementation.
3. Stop at the US1 checkpoint and validate animal/empty/vehicle/person/mixed outcomes using only generated fixtures and fake detections.
4. Demonstrate persistent local crop output without indexing, search, database service, or network access.

### Incremental Delivery

1. Deliver US1 as the privacy-filtered crop MVP.
2. Add US2 provenance and persistence; verify every crop can be traced and its stored box reconstructs the saved region.
3. Add US3 batch idempotence, recovery, and honest partial-failure summaries.
4. Complete documentation and full quality checks.

## Notes

- `[P]` means the task touches a different file and has no dependency on unfinished work.
- `[US#]` maps to the corresponding prioritized story in `spec.md`.
- Keep all tests offline; the optional real-model smoke test must not be part of the default suite.
- Do not edit `uv.lock`; dependency changes are declared in `pyproject.toml` and synchronized by the owner as required in `AGENTS.md`.






## Phase 7: Convergence

- [X] T037 Verify and record the official MegaDetector API/model format and Python 3.14 compatibility evidence for the declared PyTorch, PyAV, Pillow, and pytest constraints; retain the owner-run `uv sync` requirement per T001. Validated 2026-10-18 on Windows/Python 3.14 after owner-run sync; package versions and smoke/full-suite results are recorded in `megadetector-v6-upgrade-plan.md`.
- [ ] T038 Add fixture-driven end-to-end unchanged-rerun, changed-content/settings, and same-basename collision tests that verify output records and files, not only identity helper functions, per T026, US3/AC2-3, and SC-004 (partial).
- [ ] T039 Add mixed-batch and injected frame/storage-failure integration tests, including interrupted-publication recovery, absence of crop files/records for excluded or failed frames, and exact frame-outcome reconciliation, per T027, T034, US3/AC1/5, and SC-005 (partial).
- [ ] T040 Extend persisted provenance tests to verify capture-start-plus-PTS derivation, explicit unknown time/timezone, run/source/detection relationships, crop hashes/locations, frame lighting, and exact crop-region equality after reopening the manifest, per T016, T019, T025, US2/AC1-5, and SC-002 (partial).
- [ ] T041 Validate the lighting classifier against representative verified daylight-color, infrared-night, and ambiguous fixture images rather than only uniform-color images, per T018, US2/AC4, and SC-003 (partial).
- [ ] T042 Add CLI assertions for partial processing failure, source/frame summaries, and exit codes 0, 1, and 2, per T028, US3/AC1/4, and FR-012 (partial).
- [ ] T043 After T037 is resolved and required dependencies/model are provisioned, execute the documented local CLI quickstart with a controlled safe fixture and record its outcome alongside the already-passing pytest/Ruff checks, per T036, SC-006, and plan: compatibility gate (partial).

## Phase 8: MegaDetector V6 MIT Compact Integration

- [X] T044 Select `MDV6-mit-yolov9-c`; verify the official PyTorch-Wildlife 1.3.0 wheel exposes `MegaDetectorV6MIT` and that the selected checkpoint uses the MIT variant API.
- [X] T045 Replace the legacy dependency declaration and implement V6 class/output conversion with explicit local checkpoint/config loading and fail-closed preflight; do not edit `uv.lock`.
- [X] T046 Record package version, model variant, checkpoint digest, and config digest in effective settings/fingerprints and CLI output.
- [X] T047 Add offline adapter, CLI, and identity tests, plus an opt-in real-model smoke test.
- [X] T048 Update the README, quickstart, CLI/data-model contracts, upgrade plan, and repository guidance for local-only V6 provisioning.
- [ ] T049 After owner-run `uv sync` and separate weight/config provisioning, run the real V6 smoke and reviewed-label absolute acceptance evaluation on the target Python/platform; document results and any required follow-up. The real-model smoke passed on Windows/Python 3.14 on 2026-10-18; the reviewed-label evaluation and its pre-set absolute acceptance criteria remain outstanding.

