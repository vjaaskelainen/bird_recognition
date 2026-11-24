# Ask User Stories 1-3 Validation Quickstart

This guide validates grounded answers, safe declines, metadata filters, and
auditable evidence output without private footage, network access, or an API key.
It is not evidence of real-world answer quality.

## Prerequisites

- Python project environment synchronized with the approved dependency set.
- The User Story 1-3 unit tests and fake search/answer-service fixtures.
- For optional local acceptance only: an existing completed index run, its local
  PostgreSQL/pgvector database, matching BioCLIP model assets, retained crops, an
  OpenAI API key configured privately, and an available vision model.

Keep all footage, crop files, model assets, and credentials outside Git. Do not
put an API key in a command-line argument or shell history. The current MVP sends
the selected crop images when available and their metadata to the configured
external answer service; do not run it unless that transfer is acceptable.

## Offline validation

From the repository root in PowerShell, run the focused controlled tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\unit\test_ask.py tests\unit\test_cli_ask.py
```

Expected results: tests pass without network access, model assets, or credentials.
The controlled cases establish that:

- Supported multi-claim responses cite only supplied evidence; citations resolve
  to the selected crop, source video, frame, and known capture time.
- Invalid citation indices are discarded, and uncited claims are not presented
  as supported.
- Empty retrieval skips the answer service; explicit insufficiency, unrelated
  questions, absence questions, and count/frequency questions follow the
  insufficient-evidence rules without fabricated citations.
- Retrieved evidence accompanying a decline is labeled as nonsupporting and is
  shown without citations.
- The CLI accepts the question, selected run, and evidence limit and renders both
  human-readable and schema-version-1 JSON supported answers.
- Date bounds are strict inclusive calendar dates; lighting and species filters
  constrain candidates before the limit, including eligible crops outside the
  unfiltered top results.
- Repeated equal-score candidates use stable crop-ID ordering, and unavailable
  images retain their provenance with separately labeled similarity, species,
  and detection-confidence values.
- Retrieval and answer generation use controlled substitutes; tests require no
  external credentials or network access.

## Optional local acceptance

1. Configure the local database, matching BioCLIP model directory, API key, and
   optional model override in ignored `.env`. Add only variable names and empty
   placeholders to `.env.example`; never commit credentials.
2. Select a complete index run and confirm its context with the existing
   `inspect --run-id` command.
3. Use the `ask` command documented in [CLI contract](contracts/cli.md) with a
   question known to have relevant evidence. Optionally add `--start-date`,
   `--end-date`, `--lighting`, and `--species-id`; confirm the displayed filters,
   evidence limit/count, selected run/tagging context, and each claim's citation
   mapping to the crop, source video, frame, and known capture time.
4. Repeat the same question and run to compare evidence selection and ordering.
   The command currently uses the default limit of five unless `--limit` is set.
5. Date, lighting, and species filters are applied by the same search contract.
   The transmission notice and additional operational-failure safeguards remain
   planned for User Story 4. Declines do not present retrieved-but-nonsupporting
   evidence as citations.

An API-backed run can demonstrate command behavior for that collection but is not
a measured answer-quality evaluation. Keep labels and generated reports private;
publish no accuracy claim without a separate reviewed evaluation.
