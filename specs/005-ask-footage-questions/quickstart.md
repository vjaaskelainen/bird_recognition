# Ask Validation Quickstart

This guide validates the Ask feature without private footage, network access, or
an API key. It is an implementation/acceptance guide, not evidence of real-world
answer quality.

## Prerequisites

- Python project environment synchronized with the approved dependency set.
- The feature's unit tests and fake search/answer-service fixtures.
- For optional local acceptance only: an existing completed index run, its local
  PostgreSQL/pgvector database, matching BioCLIP model assets, retained crops, an
  OpenAI API key configured privately, and an available vision model.

Keep all footage, crop files, model assets, and credentials outside Git. Do not
put an API key in a command-line argument or shell history.

## Offline validation

From the repository root in PowerShell, run the focused controlled tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_ask.py tests\unit\test_cli_ask.py
```

Expected results: tests pass without network access, model assets, or credentials.
The controlled cases should establish that:

- Supported responses have valid per-claim citations resolving only to supplied
  evidence, and citations render crop/source/frame/time provenance.
- Out-of-range, missing, or invalid citations are never displayed as supported.
- Empty retrieval and explicit model insufficiency decline without fabricated
  citations; empty retrieval makes zero answer-service calls.
- Input errors, timeouts, refusals, incomplete responses, and malformed service
  payloads remain distinguishable from declines.
- Filters apply before the evidence limit, output order is deterministic, and
  unavailable images retain provenance and are marked unavailable.
- No command path mutates the selected run, stored representations, crops, or
  species decisions.

## Optional local acceptance

1. Configure the local database, matching BioCLIP model directory, API key, and
   optional model override in ignored `.env`. Add only variable names and empty
   placeholders to `.env.example`; never commit credentials.
2. Select a complete index run and confirm its context with the existing `inspect
   --run-id` command.
3. Use the `ask` command documented in [CLI contract](contracts/cli.md) with a
   question known to have relevant evidence, then repeat the exact request to
   compare evidence order.
4. Ask an unanswerable question, a count/frequency question, an absence question,
   and a question unrelated to the footage. Confirm declines or stated evidence
   limitations, with no universal absence assertion or unsupported count.
5. Apply date, lighting, and species filters alone and together. Inspect that
   every selected result satisfies all filters and that output reports the
   selected run/tagging context, evidence count, scores, and provenance.
6. Review the transmission notice and verify that only the selected evidence
   crops and their metadata are sent. Do not use any excluded people-containing
   frame or source video as additional evidence.

An API-backed run can demonstrate command behavior for that collection but is not
a measured answer-quality evaluation. Keep labels and generated reports private;
publish no accuracy claim without a separate reviewed evaluation.
