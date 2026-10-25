# Implementation Plan: Text Search over Wildlife Crops

**Branch**: `003-search-crops` | **Date**: 2026-10-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-search-crops/spec.md`

## Summary

Add a local CLI search over previously indexed retained animal crops. Encode the
nonblank query with the exact locally loaded BioCLIP model that created the stored
512-dimensional normalized image representations, calculate cosine similarity, and
rank only crops eligible under the selected collection/tagging context and all
metadata filters. Keep search read-only, local, deterministic, and independent of
ingestion, re-embedding, species inference, and answer generation.

## Technical Context

**Language/Version**: Python >=3.14

**Primary Dependencies**: Existing BioCLIP/OpenCLIP + PyTorch adapter, NumPy,
psycopg 3, pgvector, python-dotenv, and argparse; no new dependency planned.

**Storage**: Existing local PostgreSQL/pgvector `bird_embed` schema; search performs
read-only queries and does not add migrations or mutate indexed data.

**Testing**: pytest offline unit tests with controlled model/store substitutes;
opt-in local PostgreSQL integration tests for the search query boundary; optional
local-model smoke test. The standard suite needs neither network nor private data.

**Target Platform**: Local Windows/PowerShell-first CLI; CPU inference with
externally provisioned local BioCLIP assets and a local PostgreSQL service.

**Project Type**: Python package with CLI.

**Performance Goals**: Return an exact deterministic top-N from the full filtered
eligible set; default N=5. No latency or throughput target is specified.

**Constraints**: No upload, network inference, asset downloads, writes, re-ingestion,
or recomputation of stored image vectors. Query and crop vectors must be compatible,
normalized, dimensionally correct, and finite. Apply metadata filters before limit;
never mix collection, model, or tagging contexts. Preserve unavailable crop matches
and provenance in results.

**Scale/Scope**: One local owner and one selected collection/context per search;
results are crop-level, capped by a positive user limit (default 5). No pagination,
deduplication across adjacent frames, threshold, reranking, or quality claim.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle/gate | Assessment |
|---|---|
| Evidence-grounded answers | Pass: this feature retrieves and identifies evidence only; it does not generate claims about footage. Similarity is explicitly not proof. |
| Privacy-preserving handling | Pass: query, footage, crops, and model remain local; outputs stay local and no private data is added to Git. |
| Pretrained models and measured quality | Pass: reuse pretrained BioCLIP; no training/fine-tuning. Make no retrieval-quality claim without the specified reviewed query evaluation. |
| Testable, offline-friendly core | Pass: controlled offline tests cover ranking/filters/errors; opt-in DB tests cover persistence boundary. |
| Small, usable CLI-first scope | Pass: add only the local `search` command and supporting contracts/docs; no UI, cloud, authentication, or answer generation. |

No constitution violations or unresolved gates are identified. Re-check after the
design artifacts; no schema migration is expected.

## Project Structure

### Documentation (this feature)

```text
specs/003-search-crops/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/bird_recognition/
├── cli.py                         # argparse command and dispatch/output
└── embed/
    ├── search.py                  # request validation, query embedding, ranking/outcome
    ├── storage.py                 # read-only context/candidate queries on PgVectorStore
    ├── models.py                  # search request/context/result and protocols as needed
    └── config.py                  # resolve database/model settings and precedence

tests/
├── unit/embed/
│   ├── test_search.py              # validation, ranking, filters, ties, empty/errors
│   ├── test_cli.py                 # command/config/output/exit behavior
│   └── test_storage.py             # controlled read-only storage boundary
└── integration/embed/
    └── test_search_storage.py      # opt-in local PostgreSQL result/filter boundary

docs/usage.md                       # operational search guidance
.env.example                       # update only if a new environment setting is added
```

**Structure Decision**: Extend the existing `src/bird_recognition/embed` feature
package and top-level `cli.py`; keep search-specific contracts and acceptance
guidance in `specs/003-search-crops`. Add no external interface or schema migration.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
