# Implementation Plan: Crop Embeddings and Zero-Shot Species Tags

**Branch**: `main` (existing; no branch created) | **Date**: 2026-10-19 | **Spec**: [spec.md](spec.md)

**Input**: `specs/002-embed-species-tags/spec.md`

**Status**: Phase 0 research and Phase 1 design complete; implementation not started.

## Summary

Add a local `index` workflow that reads retained crops from the ingestion SQLite
manifest without modifying it, embeds them with locally provisioned BioCLIP, and
atomically stores 512-dimensional pgvector representations and versioned species
decisions in PostgreSQL. Use explicit species JSON, normalized image/text similarity
and candidate-relative softmax confidence, with `unknown` for ties or low scores.
Add database setup, persisted inspection, and lighting-grouped evaluation commands.
Keep ingestion independent of database availability and BioCLIP assets.

## Technical Context

**Language/Version**: Python >=3.14; existing uv-managed package and argparse CLI.

**Primary Dependencies**: Existing torch >=2.14.1,<2.15, NumPy, Pillow,
python-dotenv; proposed `open-clip-torch` for BioCLIP inference, `psycopg[binary]`
3.x and `pgvector` Python adapter. Exact compatible releases are selected and
recorded during the implementation dependency gate, not claimed tested here.

**Storage**: Existing read-only SQLite ingestion manifest; PostgreSQL 17 with
pgvector through existing Compose service. Explicit versioned schema setup;
no SQLite result fallback, ORM, similarity index, or new service.

**Testing**: pytest offline fakes for model/store; opt-in real PostgreSQL and
local BioCLIP smoke tests; Ruff lint/format. Labeled quality evaluation is separate
from substitute-based correctness tests.

**Target Platform**: Local Windows/PowerShell 5.1, Python CPU inference initially,
Compose PostgreSQL. Portable Python boundaries; GPU support is not required.

**Project Type**: Single Python CLI package.

**Performance Goals**: Acceptance batch of 100 crops; unchanged retries perform
zero image/text inference for complete decisions; retagging reuses crop vectors.
One model load and one candidate-text encoding per run requiring new scores.
Bound memory to one crop plus candidate matrix; no unmeasured latency promise.

**Constraints**: Offline processing, no automatic model downloads, no training,
no source modifications, per-crop atomic durability, fail-stop storage loss,
explicit provenance and configuration fingerprints, secrets redacted everywhere.

**Scale/Scope**: Single local owner, sequential batch processing, three user
stories; no search, Q&A, UI, taxonomy service, top-k, or multi-user feature.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Before research | After design |
|------|-----------------|--------------|
| I: Evidence-grounded answers | Pass: no Ask workflow in scope | Pass: complete provenance retained for later evidence; tags are suggestions |
| II: Privacy | Pass: no uploads or private tracked inputs | Pass: external assets/reports, read-only manifest, redacted DB credentials; checked fixtures only |
| III: Pretrained/measured quality | Pass: BioCLIP, no training | Pass: labeled evaluation with day/night/unknown groups and explicit publication gate |
| IV: Offline-friendly boundaries | Pass: controlled model/store substitutes | Pass: shared-manifest contract tests and opt-in real DB/model tests |
| V: Small CLI-first scope | Pass: local batch/inspection/evaluation only | Pass: direct SQL and one feature package; no retrieval service |
| Technical constraints | Pass: Python >=3.14, uv, PostgreSQL/pgvector | Pass by design; dependency compatibility must pass before implementation proceeds |

No constitutional exceptions. Before writing feature code, verify the selected
OpenCLIP/psycopg/pgvector releases against Python 3.14 and existing torch/torchvision
constraints. Edit dependency declarations only in `pyproject.toml` under repository
guidance; the developer performs `uv sync`. Do not downgrade Python or replace
BioCLIP/storage if compatibility fails: report the blocker. Planning performed no
installation or model provisioning.

## Project Structure

### Documentation (this feature)

```text
specs/002-embed-species-tags/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
└── contracts/
    └── cli.md
```

### Source Code (repository root)
```text
src/bird_recognition/
├── cli.py                  # add lazy command dispatch; preserve ingest/extract-frame
├── ingest/                 # unchanged source of manifest contracts
└── embed/
    ├── __init__.py
    ├── models.py           # typed entities, errors, model/store protocols
    ├── config.py           # precedence, species JSON, fingerprints
    ├── manifest.py         # read-only joined crop snapshot
    ├── bioclip.py          # local-only model adapter
    ├── scoring.py          # pure scoring/decision functions
    ├── storage.py          # psycopg transactions, queries, advisory lock
    ├── migrations/001_initial.sql
    ├── pipeline.py         # preflight, reuse, per-crop work, run outcomes
    └── evaluation.py       # persisted-decision metrics, no inference
tests/
├── ingest/                 # regression suite
└── embed/
    ├── conftest.py
    ├── fakes.py
    ├── test_config.py
    ├── test_manifest.py
    ├── test_scoring.py
    ├── test_bioclip.py
    ├── test_pipeline.py
    ├── test_retry.py
    ├── test_cli.py
    ├── test_evaluation.py
    ├── test_storage_integration.py
    └── test_bioclip_smoke.py
```

**Structure Decision**: Add an `embed` sibling of `ingest`, with small model/store
protocols solely for test substitution. Direct psycopg SQL is sufficient. Package
SQL migration resources in the wheel and test installed-resource availability.
Future implementation also updates `README.md`, `.env.example`, relevant agent
guidance, and pytest marker/CI configuration; no such runtime changes in planning.

## Phase 0: Research Outcomes

See [research.md](research.md). Decisions resolve model variant/local loading,
512-dimensional vector format, score formula/prompts, candidate fingerprinting,
read-only manifest joins, transactional storage/reuse, command/config contracts,
and evaluation semantics. Upstream configuration was inspected; dependency
installation and real-model quality were not measured.

## Phase 1: Design and Execution Order

1. Establish dependency compatibility and offline fixture/model/store protocols.
2. Implement strict species/config validation and read-only manifest snapshot.
3. Implement explicit schema initialization and tested PostgreSQL persistence.
4. Implement local BioCLIP adapter and pure decision logic.
5. Compose preflight, per-crop atomic indexing, retries, and durable run summaries.
6. Expose index/setup/inspect/evaluate commands without eager BioCLIP/DB imports.
7. Validate all three stories, document provisioning and run quality evaluation.

Entities and transaction/recovery rules: [data-model.md](data-model.md).
User-facing formats/options: [contracts/cli.md](contracts/cli.md).
Runnable implementation acceptance guide: [quickstart.md](quickstart.md).

## Validation Strategy

- FR-001/003/013: real ingestion-schema fixtures, read-only access/no source
  changes, source/detection joins, relocated paths, unknown metadata, bad manifests.
- FR-002/005/006/007: mocked adapter contract and controlled vectors/logits;
  exact ties, threshold equality, one candidate, NaN/Inf, zero norm, wrong dimension.
- FR-004/008/015: malformed/duplicate species, stable content fingerprints,
  CLI/environment/.env/default precedence, redaction and cross-configuration output.
- FR-009/010/011/012: persisted inspection, 100-crop acceptance, 100 skipped on
  repeat, 99/1 partial batch, interrupted retry, changed threshold/list/model,
  transaction rollback and connection loss, exact summary invariants.
- FR-014/017: standard suite denies network; ingest/help work with no BioCLIP
  assets/DB; opt-in local-model smoke test and real PostgreSQL rollback,
  pgvector roundtrip, dimension/uniqueness, lock and restart integration tests.
- FR-016: hand-calculated quality metrics including empty and unassigned groups;
  actual quality report needs >=10 labeled day and >=10 labeled night examples
  before any quality claim (SC-007). No substitute test satisfies that gate.
- Final implementation checks: full pytest suite plus Ruff check and format check.
  A dedicated opt-in local database job must run the real persistence tests before
  feature acceptance; skipping them in the normal suite is not persistence proof.

## Complexity Tracking

None. No exceptions or extra architectural layers are required.

`tasks.md` is intentionally deferred to `/skill:speckit-tasks`.
