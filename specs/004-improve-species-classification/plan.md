# Implementation Plan: Improve Wildlife Species Classification

**Branch**: `004-improve-species-classification` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-improve-species-classification/spec.md`

## Summary

Establish a reproducible, blind, lighting-stratified comparison of the current local BioCLIP classifier, then improve candidate vocabulary and prompts, crop views, and optional decision paths without replacing the existing baseline. Keep the default zero-shot pipeline, immutable run/config identities, persisted crop vectors and decisions, and existing review/CSV tools. Extend the versioned local CLI and PostgreSQL/SQLite contracts for candidate-independent shared labels, crop-quality/context settings, score margins, optional reference-assisted decisions, and explicitly grouped visit summaries. All quality claims remain grounded in reviewed held-out examples and all private assets/reports stay outside Git.

## Technical Context

**Language/Version**: Python >=3.14

**Primary Dependencies**: Existing NumPy, Pillow, OpenCLIP/PyTorch BioCLIP adapter, psycopg, pgvector, SQLite manifest; no new runtime dependency planned.

**Storage**: Local PostgreSQL/pgvector for immutable model, candidate, run, vector and decision records; SQLite ingestion manifest and crop files remain authoritative for source provenance; labels, reference manifests and reports are external local files.

**Testing**: pytest unit tests with fake encoders/stores and generated crops; opted-in PostgreSQL migration/integration tests; no live model/network required for core correctness.

**Target Platform**: Local Windows development and local PostgreSQL via Compose; Python CLI, CPU inference.

**Project Type**: Python CLI and library.

**Performance Goals**: No throughput SLA. Keep processing sequential as today; bound optional model benchmarks and reference comparisons by an explicit crop sample. Report elapsed processing time for benchmarked setups.

**Constraints**: Local/offline after asset provisioning; no model training or downloads; preserve old rows/files and existing zero-shot behavior; do not infer missing lighting or taxonomy; no private footage, labels, references, or generated reports in version control. Use stable fingerprints for every input/decision-affecting setting.

**Scale/Scope**: One local owner, existing indexed collections and bounded reviewed cohorts. Extend `src/bird_recognition/{ingest,embed,cli.py}`, packaged SQL migrations, and unit/integration tests. Preserve the existing blind crop-review and CSV conversion tools; do not redesign them.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate for this feature | Result |
|---|---|---|
| Evidence-grounded answers | Preserve source/frame/crop provenance; no quality claim from relative scores or synthetic tests. | Pass |
| Privacy-preserving handling | Keep source media, crops, labels, references, and reports outside Git; local paths and local DB only. | Pass |
| Pretrained models and measured quality | Retain pretrained BioCLIP; no training; compare against reviewed held-out labels and report failure cases/day/night separately. | Pass |
| Testable, offline-friendly core | Exercise decisions and reports with controlled fakes; live model/network is not needed for unit acceptance; DB boundaries receive migration/integration tests. | Pass |
| Small CLI-first scope | Add local CLI workflows only; do not add cloud/UI/multi-user/general tracking. | Pass |

No constitution violation or amendment is required. Existing source data and run contracts remain versioned; new behavior is opt-in when it changes the decision path.

**Post-design recheck**: Pass. The proposed migrations are additive, historical decisions remain readable, all model/quality comparisons are locally measured, and reference/visit paths are explicit opt-ins with offline controlled tests. No new service, training, external data transfer, or constitution amendment is introduced.

## Project Structure

### Documentation (this feature)

```text
specs/004-improve-species-classification/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/cli.md
└── tasks.md             # Generated later by /speckit-tasks
```

### Source Code (repository root)
```text
src/
└── bird_recognition/
    ├── cli.py
    ├── ingest/
    │   ├── models.py
    │   ├── crops.py
    │   ├── manifest.py
    │   └── pipeline.py
    └── embed/
        ├── config.py
        ├── models.py
        ├── scoring.py
        ├── evaluation.py
        ├── pipeline.py
        ├── storage.py
        └── migrations/
tools/
├── review_crops.py
└── review_csv.py
tests/
├── unit/
│   ├── embed/
│   └── ingest/
└── integration/embed/
```

**Structure Decision**: Extend the existing single Python project. Keep pure candidate/scoring/evaluation/grouping logic in `embed`; keep crop geometry and ingestion-settings identity in `ingest`; expose workflows through `cli.py`; add forward-only PostgreSQL migrations under `embed/migrations` and tests at the narrowest existing unit/integration locations. Adapt the existing `tools/review_crops.py` and `tools/review_csv.py` only for candidate-independent labels/case identity and additional distinct label types; preserve their blind review UI, local-only behavior, and CSV workflow.

## Implementation sequence

1. Extend blind review export/label schemas and candidate-independent `case_id`; implement paired evaluation and reports first, preserving legacy single-run report reading. Establish the zero-shot baseline before setup tuning.
2. Add typed local species/category candidates, common-name plus taxonomy prompts, stable prompt/candidate fingerprints, and inspectable coarse-category outcomes.
3. Add immutable context-aware crop generation, minimum-size quality outcomes, full-image fit/pad model input, and identity-safe vector reuse. Verify frame bounds and crop-history retention with generated images.
4. Add opt-in reference embeddings/matching with source/day split validation and zero-shot fallback; add explicit bounded benchmark reporting without model auto-selection.
5. Add independent minimum score margin and controlled decision reason tests; then add explicit visit-group manifests and linked visit-level aggregation while preserving crop decisions.
6. Add additive migrations, CLI contracts, privacy/path guards, historical compatibility tests, and end-to-end offline validation. Only reviewed held-out real cohorts support biological-quality claims.

Each stage has a distinct setup fingerprint and can be compared against the retained baseline. Do not promote settings based solely on relative scores, raw coverage, or synthetic correctness fixtures.

## Complexity Tracking

No violations.
