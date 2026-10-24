# Tasks: Crop Embeddings and Zero-Shot Species Tags

**Input**: Design documents from `specs/002-embed-species-tags/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cli.md`, `quickstart.md`; `.specify/memory/constitution.md`.
**Tests**: Required by FR-017 and the constitution. Write the listed contract/correctness tests before their implementation; observe the relevant failure, then make them pass. Substitute tests are not persistence or biological-quality evidence.
**Organization**: Setup → shared foundation → US1 (P1/MVP) → US2 (P2) → US3 (P3) → cross-cutting acceptance.

## Format and execution rules

- Tasks use `- [ ] Tnnn [P?] [USn?] Description with exact repository-relative paths`.
- `[P]` means independent files within the stated execution wave, after its prerequisites; it does not authorize running all marked tasks simultaneously.
- All paths below are relative to the repository root. New implementation belongs in the sibling `embed` package; do not modify ingestion behavior or its manifest.
- Follow `AGENTS.md` approval categories and `.agents/skills/nls-python/SKILL.md` for Python edits. Obtain scoped approval before implementation edits, environment/dependency changes, database setup, or external-data work. This task-generation approval does not authorize those actions.
- Dependency edits are confined to `pyproject.toml`; the developer syncs the environment and lock. Stop at an incompatible dependency gate rather than downgrading Python or substituting BioCLIP/PostgreSQL.
- Source footage, assets, species files, labels and generated reports remain external/private. Use generated or explicitly privacy-reviewed test fixtures only. Never record database URLs, passwords or raw credential-bearing errors.
- Contract field rules quoted in tasks are normative; retain the complete associated fields/relationships from `data-model.md`, not merely the quoted subset.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify feasibility and establish the planned package/test boundaries without altering ingestion.

- [x] T001 Verify released OpenCLIP/torchvision, psycopg 3 and pgvector compatibility with Python >=3.14 and existing torch constraints; record exact versions and reproducible compatibility evidence in specs/002-embed-species-tags/research.md, then declare approved dependencies only in pyproject.toml; wait for developer sync and verify local imports before feature code, or stop with evidence of the blocker.
- [x] T002 Create lightweight src/bird_recognition/embed/__init__.py and tests/unit/embed/__init__.py, and configure pytest markers for opt-in real-database/local-model tests in pyproject.toml without introducing eager model/database imports.
- [x] T003 Configure packaged SQL-resource inclusion in pyproject.toml and add an installed-wheel resource test in tests/unit/test_package.py for src/bird_recognition/embed/migrations/001_initial.sql; validate the resource after T014 creates it, using approved external build artifacts rather than installing or syncing dependencies automatically.

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define shared types, validation and read-only ingestion integration needed by every story.
**Gate**: Complete Phase 1 and this phase before story implementation. The package resource assertion from T003 is completed with T014.

- [x] T004 Define typed snapshot/model/candidate/config/vector/decision/run/item entities, model/store protocols and distinguishable validation, isolated-crop, shared-model, storage and unconfirmed-commit errors in src/bird_recognition/embed/models.py; preserve UUID identities, canonical SHA-256 identities and original nullable capture text; run states are "running -> complete | no_input | partial_failure | failed | interrupted" and item states are "pending -> completed | skipped | failed".
- [x] T005 Build deterministic model/store fakes with inference counters, transaction rollback/failure hooks and persisted-state restart support in tests/unit/embed/fakes.py, plus generated images and real-ingestion-schema fixtures in tests/unit/embed/conftest.py; deny network in normal embed tests and skip real boundaries unless their explicit process-environment opt-ins are present.
- [x] T006 [P] Write strict JSON, candidate, threshold, canonicalization, local-database-URL and redaction tests in tests/unit/embed/test_config.py; cover missing/unreadable/empty/malformed files, duplicate object keys, unknown fields, Unicode casefold collisions, reserved unknown IDs, booleans/nonfinite thresholds, file-order invariance and 0.50/0.5 equivalence.
- [x] T007 [P] Write read-only manifest contract tests in tests/unit/embed/test_manifest.py using actual ingestion table schemas; cover composite joins, retained crops from partially failed ingestion, inconsistent/orphan rows, missing metadata, relocation, semantic provenance changes, traversal/symlink escape and isolated file/hash failures; assert manifest/crop bytes and schema are unchanged.
- [x] T008 Implement strict species JSON and threshold validation, canonical UTF-8 JSON/SHA-256 helpers, sanitized errors and local-only connection validation in src/bird_recognition/embed/config.py; require "Sorted array of `{id, name}`; nonempty", "Hash source; retain exact trimmed candidate names" and "Finite double [0,1], default 0.5"; "Reject non-string/blank identifiers or names, reserved identifier `unknown`, duplicate IDs or names after trimming/casefold, unknown fields and duplicate JSON object keys." IDs remain case-preserving/exact; reserve unknown case-insensitively and reject remote hosts without deriving URLs from POSTGRES_*.
- [x] T009 Implement the read-only/query-only consistent SQLite snapshot adapter in src/bird_recognition/embed/manifest.py; select all animal_crop rows ordered by crop ID via source_video/sampled_frame/detection composite keys, reject structural inconsistencies before writes, release the snapshot before inference, never instantiate the writing ingestion Manifest, and document ingestion-idle prerequisite in specs/002-embed-species-tags/quickstart.md.
- [x] T010 Implement complete snapshot provenance validation/digests and safe resolved crop locators in src/bird_recognition/embed/manifest.py; snapshot_id is "SHA-256 of crop_id plus provenance digest; PK", crop_id is "Existing `animal_crop.crop_id`; required", frame/time are "Nonnegative frame/time", detection is "Original ID; qualified `animal` only", confidence is "Finite [0,1], distinct from species confidence", box is "Original four finite normalized detection coordinates", bounds/dimensions are "Original crop bounds and positive frame dimensions", capture values are "Nullable original values; never fabricated" and lighting is "`day`, `night`, `unknown`; copied, not inferred"; hash every semantic field listed in data-model.md, including crop/settings identities, excluding processing times and resolved locators; leave individual path/read/hash/decode errors to run items.

**Checkpoint**: Offline contracts can validate inputs and capture full immutable provenance without loading BioCLIP or connecting to PostgreSQL.

## Phase 3: User Story 1 — Index and identify ingested crops (Priority: P1) — MVP

**Goal**: Explicit species configuration plus local BioCLIP produces atomic durable vectors/decisions, and CLI inspection works after restart without source assets.
**Independent Test**: A controlled 100-readable-crop batch yields 100 durable representations/decisions with complete provenance and assigned+unknown=100; restart and inspect using only storage. Separately prove actual PostgreSQL persistence. Include controlled below/equal/above-threshold, tie and single-candidate cases.

### Tests for User Story 1

- [x] T011 [P] [US1] Write pure scoring tests in tests/unit/embed/test_scoring.py for stable float64 softmax, checkpoint scale, exact maximum-logit ties versus rounded/near ties, threshold equality, below-threshold unknown, single candidate, invalid dimensions/norms and NaN/Infinity vectors/logits/scores; assert warnings and all stored candidate scores.
- [x] T012 [P] [US1] Write local-model adapter contracts in tests/unit/embed/test_bioclip.py with controlled OpenCLIP substitutes; deny network and test missing/hash-mismatched bundles, unsupported config/dimension, immutable revision validation, packaged BPE identity, strict checkpoint loading, no random-weight/pretrained/hub fallback and CPU float32 deterministic preprocessing.
- [x] T013 [P] [US1] Write opt-in real PostgreSQL tests in tests/integration/embed/test_storage_integration.py for idempotent transactional initialization, unknown schema/version and permission/vector failures, 512-vector roundtrip, finite/range/norm/uniqueness/model-candidate consistency checks, rollback between every result insert and persisted inspection across connections; use only BIRD_RECOGNITION_TEST_DATABASE_URL with disposable schema cleanup, never the production variable.

### Implementation for User Story 1

- [x] T014 [US1] Create the versioned bird_embed schema and all entity/relationship/count constraints in src/bird_recognition/embed/migrations/001_initial.sql; use UTC timestamptz and explicitly reject PostgreSQL NaN; representation embedding is "`vector(512)`, finite, nonzero, L2-normalized within documented float32 tolerance (1e-5)", model architecture/dimension are "`ViT-B-16`, 512 for this schema", and logit scale is "Finite positive effective scale from checkpoint"; enforce unique (crop_id, provenance_sha256), (snapshot_id, model_fingerprint), (representation_id, config_fingerprint), run-item "(run_id, crop_id) PK" and explicit schema version 1; do not add ANN indexes or a fallback backend.
- [x] T015 [US1] Implement explicit transactional/idempotent database-init, bundled migration loading and read-only schema/vector/permissions/dimension preflight in src/bird_recognition/embed/storage.py; only initialization may create the extension/migrate, reject unknown schema versions without destructive changes, and verify T003 installed-resource packaging.
- [x] T016 [US1] Implement session-level nonblocking advisory writer lock acquisition/release and run/config/pending-item registration after successful preflight in src/bird_recognition/embed/storage.py; only the lock owner writes/finalizes runs, writer contention is writer_busy preflight failure, immutable metadata registration is allowed but no crop results are fabricated for zero input.
- [x] T017 [US1] Implement normalized image/text scoring and decision validation in src/bird_recognition/embed/scoring.py: L_i=exp(model.logit_scale)*dot(u,t_i), stable float64 softmax, exact maximum-logit equality, unique score>=threshold assignment and tie precedence; confidence is "Maximum candidate-relative softmax score, finite [0,1]", best is "Unique best ID or null on exact tie", tied IDs are "Empty for unique best, otherwise >=2 candidate IDs", scores are "Ordered `{id, logit, score}` entries for every candidate" in canonical ID order, reason is "`assigned`, `below_threshold`, `exact_tie`" and warnings are "Always relative-candidate warning; single-candidate warning when applicable"; invalid values fail rather than become unknown.
- [x] T018 [P] [US1] Implement local-only BioCLIP loading, image/text inference and model identity in src/bird_recognition/embed/bioclip.py using original imageomics/bioclip ViT-B-16, 224-pixel transforms, 512 normalized float32 outputs, packaged CLIP BPE and strict checked checkpoint loading; asset-manifest.json schema 1 names the two exact local files/hashes and immutable upstream revision; disable all pretrained/hub downloads, use CPU eval/inference mode, record actual effective scale and hash assets, tokenizer, preprocessing, adapter and relevant runtime versions; paths are not model identity.
- [x] T019 [US1] Build/persist canonical model, candidate, scoring and decision configuration identities in src/bird_recognition/embed/config.py; config is "PK: model + candidates + scoring + threshold digest", scoring is "Model/candidates/prompt/scale/normalization/softmax/tie contract digest; excludes threshold", prompt/version are "`a photo of {name}.`, `species-photo-v1`", effective scale is "Finite positive" and canonical JSON retains the complete contract; no user-adjustable prompt or temperature in v1.
- [x] T020 [US1] Implement atomic per-crop commit and exact-completion/compatible-vector lookups in src/bird_recognition/embed/storage.py; store full immutable snapshot/model/candidate/config/vector/decision plus successful item and counters in one transaction, validate candidate membership/model match/score-map sum/reason-field agreement at the storage boundary, insert a new vector only with its first completed decision, and resolve unique conflicts by loading compatible immutable records rather than overwriting history.
- [x] T021 [P] [US1] Write orchestration acceptance tests in tests/unit/embed/test_pipeline.py with controlled vectors/store: 100 successes, full provenance after restart, zero-input with full preflight, isolated corrupt/missing/hash-mismatched crop giving 99 successes/1 failure, invalid-vector/score failures, fatal shared-model stop and every preflight error causing zero crop-result writes.
- [x] T022 [P] [US1] Write initial command contract tests in tests/unit/embed/test_cli.py for database-init/index/inspect, JSON-only stdout and sanitized stderr, usage/preflight exit 2, processing exit 1 and success/no-input exit 0; test inspect list/run/crop selections and no current model/species/crop/manifest access, plus unchanged ingest/extract-frame/help without BioCLIP assets or database.
- [x] T023 [US1] Compose preflight and initial indexing in src/bird_recognition/embed/pipeline.py; validate manifest/species/threshold/local assets/model/database/vector/schema/permissions and acquire writer lock before run/result writes, hash-check each crop before exact-completion lookup, avoid decoding/inference on complete decisions, infer only as needed and encode candidates once per run requiring scores; isolate crop errors, fail-stop shared model/storage errors, count only confirmed commits and finalize complete/no_input/partial_failure/failed outcomes.
- [x] T024 [US1] Implement read-only persisted run/item/provenance/config/decision queries in src/bird_recognition/embed/storage.py, including newest-first run listing and exact run/crop selection; return actual skipped decision references, no completed decision for pending/failed items, null capture values and preserved day/night/unknown, without source files or model inference.
- [x] T025 [US1] Add lazy database-init/index/inspect dispatch and exact options from specs/002-embed-species-tags/contracts/cli.md in src/bird_recognition/cli.py; require run-id XOR list-runs and crop-id only with run-id; emit versioned JSON envelopes/preflight codes, all summary keys including pending/durable_status_confirmed/unconfirmed_crop_ids, and full decision/provenance/warnings; redact credentials and distinguish exit 0/1/2 while preserving existing commands.

**Checkpoint**: US1 is usable with an explicitly selected list and threshold. Basic exact-result skipping and per-crop atomicity already exist; US2 expands configuration/reuse guarantees and US3 hardens recovery/evaluation.

## Phase 4: User Story 2 — Control the candidate species (Priority: P2)

**Goal**: Honor every configuration source and retag compatible persisted vectors with distinguishable candidate/threshold settings.
**Independent Test**: Retag stored representations with two candidate lists and changed thresholds; verify selected-only IDs, versioned historical decisions, zero image inference and explicit CLI > environment > .env > default precedence.

### Tests for User Story 2

- [x] T026 [P] [US2] Extend tests/unit/embed/test_config.py with conflicting CLI/process environment/discovered .env/default cases, missing/empty required settings, explicit invalid values that must not fall back, no selection aliases for manifest/run/labels/output, no POSTGRES_* URL fallback and remote-host rejection/redaction.
- [x] T027 [P] [US2] Add retagging tests in tests/unit/embed/test_retry.py proving threshold-only score-map reuse with zero image/text inference, changed candidates reusing only image vectors with one candidate encoding, changed model requiring new vectors, historical decision isolation, list reorder/path relocation stability and changed provenance invalidating reuse.
- [x] T028 [P] [US2] Extend command tests in tests/unit/embed/test_cli.py for environment/default configuration, exact candidate/config identities across index and inspect, retained best/tied candidates, incomparable candidate-relative confidence warnings and single-candidate limitations without taxonomy/synonym resolution.

### Implementation for User Story 2

- [x] T029 [US2] Implement complete explicit CLI > process environment > discovered .env > built-in resolution in src/bird_recognition/embed/config.py and wire it in src/bird_recognition/cli.py; support only BIRD_RECOGNITION_DATABASE_URL, BIRD_RECOGNITION_BIOCLIP_MODEL_DIR, BIRD_RECOGNITION_SPECIES_LIST and BIRD_RECOGNITION_SPECIES_THRESHOLD aliases, preserve default 0.5, fail empty/invalid required values and require only command-relevant settings.
- [x] T030 [US2] Implement reusable score-map lookup by representation/scoring fingerprint in src/bird_recognition/embed/storage.py; threshold-only configurations may reference compatible historical scores, never mix candidate/model contracts, and retain each prior config's unique decision.
- [x] T031 [US2] Complete configuration-aware reuse in src/bird_recognition/embed/pipeline.py: complete snapshot/model/config skips before any inference, compatible representation without exact decision is newly completed not skipped, threshold-only changes reuse validated stored logits/scores, changed candidates recompute text comparisons only, changed model recomputes image embeddings and relocation never changes semantic identity.
- [x] T032 [US2] Finalize config-scoped inspection and warnings in src/bird_recognition/cli.py; include canonical candidate/model/scoring/config versions and threshold, preserve exact candidate IDs, show ties/shared scores and explain relative confidence, non-comparability, detector-confidence distinction and potentially high out-of-list scores using the CLI contract's required warning text.
- [x] T033 [P] [US2] Inventory all four runtime and three opt-in test environment variables in .env.example using nonsecret placeholders, with no implicit species or credential default and a clear distinction between private application URL and Compose POSTGRES_* settings.

**Checkpoint**: Owners can choose/revise vocabulary and threshold without re-ingestion or redundant compatible image inference; prior configurations remain inspectable.

## Phase 5: User Story 3 — Resume processing and inspect quality (Priority: P3)

**Goal**: Safely repeat interrupted/failing work and evaluate persisted decisions with transparent per-lighting metrics.
**Independent Test**: Interrupt after N commits, restart and reach exactly 100 complete decisions without repeated completed inference; inject write/commit-acknowledgement loss at the actual DB boundary. Separately match evaluation reports against hand-calculated day/night/unknown outcomes, including failures, skipped items and empty denominators.

### Tests for User Story 3

- [x] T034 [P] [US3] Extend tests/unit/embed/test_retry.py for 100-skip unchanged repeats, newly unreadable completed inputs failing rather than skipping, interruption after N commits, stale-run recovery, vector/decision rollback, retag write failure preserving earlier vectors, pending remainder, fatal shared-model/storage stop and lost-acknowledgement reconciliation with zero duplicate durable results.
- [x] T035 [P] [US3] Extend tests/integration/embed/test_storage_integration.py with concurrent-writer rejection, lock release on connection death, restart/stale-run recovery, connection loss before/during commit and lost-acknowledgement fault injection around a real PostgreSQL commit; prove committed-only local counts, atomic durable counters/item references and durable lookup on retry instead of substitute-only assertions.
- [x] T036 [P] [US3] Write label/metric/report tests in tests/unit/embed/test_evaluation.py for strict JSON schemas, duplicate/unknown fields/keys/IDs, mismatched run IDs, exact species candidate membership, out-of-list/unidentifiable truth, empty/subset labels, skipped decisions, failed/pending versus unknown, unlabeled count, all lighting groups/zero denominators, 10-day/10-night gate and external no-overwrite atomic output; use hand-calculated examples, not fabricated quality claims.
- [x] T037 [P] [US3] Extend tests/unit/embed/test_cli.py for interrupted/partial/fatal/unconfirmed summary envelopes, stable failure codes and durable_status_confirmed, evaluate-species option/read/validation exits, read-only evaluation with absent model/species/crops, private report path rejection and valid low-quality reports returning success.

### Implementation for User Story 3

- [x] T038 [US3] Implement lock-owner-only stale-run interruption, immutable retry history and atomic failed/skipped/completed item/counter transitions in src/bird_recognition/embed/storage.py; enforce "assigned + unknown = completed", ordinary "selected = completed + skipped + failed" and running/interrupted/fatal "selected = completed + skipped + failed + pending"; failed/pending items may exist without snapshots and cannot borrow an older decision.
- [x] T039 [US3] Harden interruption/failure/finalization in src/bird_recognition/embed/pipeline.py; recover stale runs only after all preflight checks, start a new retry run, preserve confirmed prior work, stop immediately on any storage failure, retain pending remainder, release lock on close and report lost commit acknowledgement as unconfirmed rather than locally successful; leave unfinalizable durable runs running for next-writer recovery and never claim saved final status without confirmation.
- [x] T040 [US3] Implement strict persisted-run label validation in src/bird_recognition/embed/evaluation.py; expected_species_id is "nonblank string or null", truth_kind is "`species`, `out_of_list`, `unidentifiable`", "Species truth requires a known candidate ID; out-of-list may carry an external truth ID or null, but must not name a candidate; unidentifiable requires null." Reject duplicate IDs, unknown fields/keys and labels outside the selected run; preserve optional privacy-reviewed notes and hash canonical label content.
- [x] T041 [US3] Implement persisted-only per-day/night/unknown metrics in src/bird_recognition/embed/evaluation.py with sample/completed/correct/incorrect/unknown/failed/pending counts, unlabeled run count, full evaluated fingerprints/threshold, evaluation UUID/UTC time and failure examples; "Precision = correct / assigned; null if assigned=0.", "Assignment coverage = assigned / completed labeled decisions; null if completed=0." and "Processing coverage = completed / labeled samples; null if labeled samples=0." Include skipped decisions, count out-of-list/unidentifiable assignments incorrect, never count unknowns as correct, and require >=10 completed labeled day and >=10 completed labeled night for publication_ready without implying accuracy.
- [x] T042 [US3] Add privacy-safe external report writing in src/bird_recognition/embed/evaluation.py; validate paths first, reject output inside any Git repository and existing targets, use atomic temporary-file finalization without overwriting, clean temporary artifacts on failure and never read images or current model/species files.
- [x] T043 [US3] Expose evaluate-species in src/bird_recognition/cli.py with explicit run-id/labels/output, database configuration and optional JSON stdout; always write the versioned external report, use unavailable for null human metrics, preserve read-only storage access and map invalid inputs to exit 2, operational reads/writes to exit 1 and valid low-quality reports to exit 0.

**Checkpoint**: All stories have offline correctness coverage and executable real-persistence proof. Real model quality is still an explicit external-data acceptance gate, not inferred from fakes.

## Phase 6: Polish and Cross-Cutting Acceptance

**Purpose**: Complete private-data safeguards, documentation, runnable boundary validation and measured-quality evidence.

- [x] T044 [P] Add explicitly opted-in local-model smoke coverage in tests/smoke/test_bioclip_smoke.py using BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR and BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE; deny network, verify deterministic finite normalized 512-vectors and candidate scores, and state that smoke execution is not species-quality evidence.
- [ ] T045 [P] Update README.md with model/dependency provisioning, local-only pgvector/schema setup, candidate JSON, threshold/relative-confidence caveats, run-scoped inspect, retry/retag/evaluation commands and private external destinations; retain ingestion/extract-frame independence and link to the feature quickstart rather than duplicating detailed contracts.
- [ ] T046 [P] Add a dedicated opt-in disposable local PostgreSQL acceptance job and retain network-free default pytest/Ruff checks in .github/workflows/ci.yml; use explicit test URL/service health and schema cleanup, require real persistence tests before acceptance, avoid production URLs/model downloads, and pin any added third-party actions to full commit SHAs with adjacent version comments.
- [ ] T047 Align specs/002-embed-species-tags/quickstart.md, specs/002-embed-species-tags/contracts/cli.md and AGENTS.md with the implemented safe workflow and actual option/schema details; keep guidance brief, link to authoritative docs, record developer-sync/approval requirements and distinguish offline correctness, DB proof, optional model smoke and actual quality gates.
- [ ] T048 Audit privacy and lazy boundaries with assertions in tests/unit/embed/test_cli.py and tests/unit/embed/test_pipeline.py: credentials absent from settings/errors/reports/JSON, remote connections rejected, no implicit production test database, index never migrates/downloads, sources unchanged and ingest/extract-frame/help/inspect/evaluate require no model assets where inapplicable.
- [ ] T049 Execute the 100-crop/retry/retag/99-plus-1/preflight acceptance matrix in specs/002-embed-species-tags/quickstart.md and tests/unit/embed/test_pipeline.py / tests/unit/embed/test_retry.py; run the explicitly opted-in tests/integration/embed/test_storage_integration.py against an approved disposable local database and T003 installed-wheel resource check, record actual outcomes in specs/002-embed-species-tags/quickstart.md, and leave unavailable gates explicitly blocked rather than treating skipped tests as proof.
- [x] T050 With separately approved external BioCLIP assets and privacy-reviewed labeled examples, run the measured evaluation workflow in specs/002-embed-species-tags/quickstart.md for >=10 completed daylight and >=10 completed night crops plus separately reported unknown lighting; keep labels/reports external, review failure cases and record only nonprivate measured aggregate evidence/report identifiers in specs/002-embed-species-tags/quickstart.md; if inputs are unavailable, leave this task and SC-007 unmet and publish no quality claims.
- [ ] T051 Run the full offline suite and final configured Ruff checks from repository root using .\.venv\Scripts\python.exe -m pytest, .\.venv\Scripts\uv.exe run ruff check . and .\.venv\Scripts\uv.exe run ruff format --check .; record results and explicitly skipped/blocked real-DB/model/quality gates in specs/002-embed-species-tags/quickstart.md, then rerun Ruff last if any fixes or documentation edits were needed.

## Dependencies and Execution Order

### Phase graph

```text
T001 compatibility/developer-sync gate
  → T002–T003 package/resource scaffolding
  → Phase 2 shared types/fakes/input contracts (T004–T010)
  → US1 (T011–T025): atomic index + persisted inspect [MVP]
  → US2 (T026–T033): precedence + configuration-aware retagging
  → US3 (T034–T043): recovery + persisted evaluation
  → Phase 6 (T044–T051): boundary/quality evidence + final checks
```

- **US1** depends on the shared foundation, not on later stories. It already includes selected candidate validation, basic threshold configuration, exact-result skipping, atomicity and isolated failure handling so the MVP is coherent.
- **US2** integrates with US1's stored representations/configs. Its tests independently demonstrate configuration control using persisted vectors and controlled scores; it does not require ingestion or US3 evaluation.
- **US3** recovery builds on US1/US2's completion/reuse contract. Evaluation tests can be authored independently against persisted-run fixtures once the foundation types exist; delivery still requires run-scoped storage/inspection.
- Do not assume whole stories are parallel: storage.py, pipeline.py, config.py and cli.py are shared editing hotspots. Serialize edits there.
- Within Phase 2: T004 → T005 → parallel T006/T007 → T008 and T009/T010; T010 follows T009.
- Within US1: write T011/T012/T013 first; T014 → T015 → T016; T017 and T018 use established types and may proceed independently of storage. T019 follows scorer/model identity contracts. T020 integrates T014–T019. T021/T022 precede T023–T025. T023 consumes storage/model/scorer/config; T024 precedes inspect wiring in T025. Complete T003's resource validation after T014.
- Within US2: T026/T027/T028 first; T029 and T030 precede T031; T032 follows reuse integration. T033 is independent of source edits after the environment contract is fixed.
- Within US3: T034/T035/T036/T037 first; T038 → T039; T040 → T041 → T042 → T043, with T043 serialized after other CLI changes.
- Final validation follows implementation. Real DB service/schema operations, local model execution and labeled-data work need their own scoped approval and prerequisites. T050 can remain an explicit unmet acceptance gate if real examples are unavailable; do not fabricate completion.

### Parallel opportunities and examples

All examples assume preceding phase/gates and common fixtures are complete; test-authoring waves are separate from implementation waves.

**US1**:

- Wave A: T011 tests/unit/embed/test_scoring.py + T012 tests/unit/embed/test_bioclip.py + T013 tests/integration/embed/test_storage_integration.py.
- Wave B: T017 src/bird_recognition/embed/scoring.py + T018 src/bird_recognition/embed/bioclip.py, alongside storage work only when their shared interfaces are stable.
- Wave C: T021 tests/unit/embed/test_pipeline.py + T022 tests/unit/embed/test_cli.py before orchestration/CLI implementation.

**US2**:

- Wave A: T026 tests/unit/embed/test_config.py + T027 tests/unit/embed/test_retry.py + T028 tests/unit/embed/test_cli.py.
- Wave B: T033 .env.example alongside T030 storage reuse, with the environment contract already fixed; T029/T031/T032 shared-source edits remain sequenced.

**US3**:

- Wave A: T034 tests/unit/embed/test_retry.py + T035 tests/integration/embed/test_storage_integration.py + T036 tests/unit/embed/test_evaluation.py + T037 tests/unit/embed/test_cli.py.
- Wave B: evaluation T040–T042 can proceed alongside recovery T038–T039 once persisted read contracts are stable; serialize shared CLI integration.

**Cross-cutting**: T044 smoke-test authoring, T045 README and T046 CI are disjoint; coordinate wording before T047 and do not run terminal checks concurrently.

## Implementation Strategy

1. **MVP first**: Complete Setup + Foundation + US1; prove controlled 100-crop persistence/provenance and restarted inspection, plus the real DB boundary. Do not claim model accuracy.
2. **Incremental vocabulary control**: Deliver US2 with precedence and threshold/list/model invalidation/reuse matrices. Show new decisions on old compatible image vectors and retain historical results.
3. **Reliability and quality tooling**: Deliver US3 with interruption/commit uncertainty proof and hand-checked grouped evaluation. Persisted failures/pending items must not masquerade as unknown species.
4. **Acceptance**: Complete documentation, privacy audit, packaged resources, CI, real DB tests and final offline checks. Run real local-model/quality work only with approved private prerequisites, reporting unavailable gates honestly.

## Requirements Coverage

| Requirement | Primary tasks |
|-------------|---------------|
| FR-001 read-only CLI ingestion input | T007, T009–T010, T023, T025 |
| FR-002 BioCLIP + PostgreSQL/pgvector | T001, T012–T015, T018, T020 |
| FR-003 complete provenance | T004, T007, T009–T010, T014, T020, T024 |
| FR-004 strict explicit candidates | T006, T008, T019, T026, T029 |
| FR-005 zero-shot image/text comparison | T011–T012, T017–T018, T023 |
| FR-006 relative confidence and inspectable decisions | T011, T017, T020, T024–T025, T032 |
| FR-007 finite threshold/ties/equality | T006, T008, T011, T017, T026 |
| FR-008 model/candidate/scoring/config versions | T010, T018–T020, T027–T032 |
| FR-009 inference-free persisted inspection | T022, T024–T025, T032, T048 |
| FR-010 skip/reuse/history | T020, T023, T027, T030–T031, T034 |
| FR-011 transactional completion | T013–T014, T020, T035, T038–T039 |
| FR-012 outcomes/fail-stop/counts/exits | T021–T023, T025, T034–T039 |
| FR-013 full preflight including no-input | T007–T010, T012, T015–T016, T021, T023 |
| FR-014 local-only/privacy/ingestion independence | T005, T008, T012, T018, T022, T042, T048 |
| FR-015 precedence/docs/environment inventory | T026, T028–T029, T033, T045, T047 |
| FR-016 grouped measured evaluation | T036–T037, T040–T043, T050 |
| FR-017 offline substitutes + real boundaries | T003, T005–T007, T011–T013, T021–T022, T034–T037, T044, T046, T049, T051 |
| SC-001–SC-003 complete/valid/provenanced results | T011, T021, T024–T025, T049 |
| SC-004–SC-006 repeat/partial/reuse acceptance | T027, T034–T035, T049 |
| SC-007 actual day/night quality evidence | T040–T043, T050; met by reviewed measured evidence, not by fakes or smoke tests; evidence does not imply good accuracy |

## Completion Notes

- Task inventory: **51 tasks** — Setup 3, Foundation 7, US1 15, US2 8, US3 10, Polish/Acceptance 8.
- Independent test criteria appear in each story phase; all story tasks carry exactly one US label and all tasks name concrete paths.
- Mark tasks complete only after evidence is available. Do not run implementation as part of generating this document.
- US3 offline tests and implementation are complete. The developer reports all 8 real PostgreSQL integration test cases passed against the disposable smoke-test database using the repository's `pyproject.toml` pytest configuration; no database URL or credentials are recorded. T035 is complete. The developer also reports a successful wheel build and migration resource read from `bird_recognition-0.1.0-py3-none-any.whl`; T003 and T015 are complete. The expanded storage integration test file passed all 31 tests against the configured disposable PostgreSQL database, and repository-wide Ruff lint and format checks passed; T013 is complete. On 2026-10-23, the developer reported an ingestion/index acceptance run with 143 crops: 143 completed (126 assigned, 17 unknown, 0 failed), durable status confirmed, and a repeat skipped all 143. Correct checkpoint loading was confirmed by the developer; the model fingerprint and lack of asset-manifest revision/file hashes are documented in quickstart.md. This is evidence for successful processing/repeat behavior only. The reviewed biological-quality evaluation documented in quickstart.md completes T050 and meets SC-007's evidence gate, but measured precision is low and is not a positive accuracy claim. T049 remains unchecked because the rest of its controlled retry/retag/99-plus-1/preflight matrix has not been reported as run.

[US1]: spec.md#user-story-1---index-and-identify-ingested-crops-priority-p1
[US2]: spec.md#user-story-2---control-the-candidate-species-priority-p2
[US3]: spec.md#user-story-3---resume-processing-and-inspect-quality-priority-p3
