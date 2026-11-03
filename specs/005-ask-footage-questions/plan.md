# Implementation Plan: Ask Questions About Footage

**Branch**: `005-ask-footage-questions` | **Date**: 2026-11-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-ask-footage-questions/spec.md`

## Summary

Add a read-only `ask` CLI command that reuses the existing run-scoped BioCLIP
search and metadata filters to select at most five retained crops. Send only those
crop images and their provenance/decision metadata to the OpenAI Responses API
using a vision-capable model (`gpt-4o-mini` by default). Require a structured
claim-by-claim response, validate every evidence reference against the exact
supplied set, and return either a supported answer, an insufficient-evidence
decline, an input error, or an operational failure. Keep retrieval and answer
orchestration independently testable with controlled offline substitutes.

## Technical Context

**Language/Version**: Python 3.14+

**Primary Dependencies**: Existing argparse CLI, BioCLIP adapter, psycopg/pgvector
read-only store, python-dotenv, pytest; add the OpenAI Python SDK for Responses API
vision requests (implementation dependency change requires separate approval).

**Storage**: Existing local PostgreSQL/pgvector indexed-run data and retained crop
files; no schema changes or durable Ask history.

**Testing**: pytest unit tests with fake search/model/client; opt-in disposable
PostgreSQL integration tests for existing search storage as needed. Standard tests
require no API key, network, private footage, or model assets.

**Target Platform**: Local Python CLI on the repository-supported platform,
including Windows PowerShell; indexed data and crop files remain local.

**Project Type**: Python CLI application.

**Performance Goals**: No latency SLA is specified. Limit the default evidence set
to five items, impose a finite answer-service timeout, and fail explicitly if the
service exceeds it rather than silently truncating evidence or output.

**Constraints**: Reuse search context, filtering, and deterministic ranking; keep
the operation read-only; transmit only selected crops and their metadata; never
send credentials in prompts or output; require valid citations for supported
claims; do not treat similarity or species suggestions as proof.

**Scale/Scope**: One local owner, one question per invocation, one selected
indexed run, and a small bounded evidence set. No history, conversation, visit
aggregation, exact counting, or multi-user/cloud service.

## Constitution Check

| Principle / gate | Status | Plan evidence |
|---|---|---|
| I. Evidence-Grounded Answers | PASS | Reuse ranked evidence; require per-claim citations; downgrade unsupported or invalidly cited responses. |
| II. Privacy-Preserving Data Handling | PASS | Keep crops local; send only selected crops and their metadata to the explicitly configured vision service; keep credentials in ignored local configuration. |
| III. Pretrained Models and Measured Quality | PASS | Use pretrained BioCLIP and a hosted pretrained vision model; make no quality claims from controlled tests. |
| IV. Testable, Offline-Friendly Core | PASS | Inject retrieval and answer-client interfaces; unit tests use controlled substitutes and no network. |
| V. Small, Usable CLI-First Scope | PASS | Implement one local `ask` subcommand; no UI, auth, streaming, agent behavior, or persistent history. |
| Data and read-only constraints | PASS | Read existing run/vector/provenance data and retained crops only; no migration or stored-data mutation. |
| Quality gates | PASS | Run relevant tests and configured Ruff checks during implementation; no test requires external credentials. |

No constitution violations or exceptions are required.

## Project Structure

### Documentation (this feature)

```text
specs/005-ask-footage-questions/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   └── answer-service.md
└── tasks.md              # Phase 2 output; not created by this plan
```

### Source Code (repository root)

```text
src/bird_recognition/
├── cli.py                         # Register and dispatch `ask`
├── ask.py                         # Ask orchestration, prompt, citation validation, outcomes
└── embed/
    ├── search.py                  # Reuse execute_search and SearchResult provenance
    ├── config.py                  # Resolve new Ask configuration
    └── storage.py                 # Reuse read-only collection retrieval

tests/
├── unit/
│   ├── test_ask.py                # Offline orchestration and citation tests
│   └── test_cli_ask.py            # CLI parsing, output, and outcome/exit-code tests
└── integration/
    └── embed/test_search_storage.py # Existing opt-in DB boundary coverage
```

**Structure Decision**: Keep Ask orchestration in a focused `ask.py` module at the
package level. Reuse the existing `embed.search` service and `PgVectorStore`
interfaces rather than duplicating retrieval or adding a second storage path.
Register the public command in the existing `cli.py`; keep API schema and user
validation contracts in the feature's `contracts/` artifacts.

## Complexity Tracking

No complexity exception is required.
