# Quickstart: Validate Text Search over Wildlife Crops

**Status**: Planning validation guide; commands and acceptance outcomes are targets
for implementation, not evidence that search is already available or that retrieval
quality has been measured.

Run PowerShell commands from `C:\code\bird_recognition` using the existing `.venv`.
If it is absent, stop and ask the developer; do not activate or create it. See the
[CLI contract](contracts/cli.md) for options/output, the [data model](data-model.md)
for identity and score definitions, and [AGENTS.md](../../AGENTS.md) for approval
and dependency policy.

**Approval boundary**: This guide does not authorize source/dependency changes,
database or service setup, schema/database operations, or using private model assets,
footage, labels, or reports. Use only a developer-approved local dataset and the
selected completed index run. Keep all private footage, crops, model assets, labels,
and generated reports outside Git.

## 1. Prerequisites

- Existing `.venv` with declared project dependencies and Python >=3.14.
- Local PostgreSQL with the existing `bird_embed` schema and pgvector extension.
  Search is read-only and does not initialize or migrate the database.
- Complete local BioCLIP ViT-B-16 bundle from the same immutable upstream revision
  used to index the selected run. The loaded model fingerprint must exactly match
  the run. Search does not fetch model assets or make network requests.
- One completed indexing run (`complete`) or valid empty run (`no_input`), selected
  explicitly by run ID. Its persisted successful/skipped items, model and tagging
  config define the collection/context. Do not search a partial/failed/interrupted
  run as if it were complete.
- A local database URL and model directory, supplied by CLI or existing
  `BIRD_RECOGNITION_DATABASE_URL` and `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR` settings.
  CLI options override process environment, which overrides `.env`; no new search
  environment variables are planned.

Set private paths for the approved local assets and selected run:

```powershell
Set-Location 'C:\code\bird_recognition'
$runId = '<completed-index-run-uuid>'
$model = 'D:\bird-models\bioclip'
```

Use the existing `inspect --list-runs` command to find candidate run IDs; explicitly
inspect the selected run before searching. Do not share database URLs or credentials
in command history or output.

## 2. Baseline offline checks

The standard suite uses controlled substitutes, needs neither model assets nor a
running database, and does not measure real retrieval quality:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Expected tests cover query validation, finite normalized vectors, cosine scores and
range, descending ranking with stable tie ordering, limit boundaries, each metadata
filter and their combination-before-limit, provenance, unavailable crop files,
empty success, context/config validation, and invalid/operational failures. Confirm
search tests do not invoke networking, modify stored records, or load crop images for
inference.

## 3. Search without filters

With developer-approved local prerequisites and context, run:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition search "squirrel on the feeder" `
  --run-id $runId `
  --model-dir $model `
  --limit 5 `
  --json
```

Expected: exit 0 and one versioned JSON `searched` envelope. It identifies the exact
query, filters, requested limit, returned count, run/model/tagging context, and
ordered results. Each result carries cosine similarity, stable crop and
representation identities, source/frame reference and available provenance. A
successful empty result has count 0 and an empty result list. No new representations
or decisions are created.

Similarity is cosine in `[-1, 1]`; higher is more similar, not a probability that the
query is true. Species confidence is candidate-relative; detection confidence is a
separate detector score. None proves species identity, event occurrence, or absence.

## 4. Check filters and boundary behavior

Run controlled unit fixtures for, separately and together:

- Inclusive start/end capture-date bounds, either bound alone, same-day range,
  malformed dates, reversed range, missing timestamps and unknown timezone.
- Exact `day` and `night` values; `unknown` remains eligible only without a lighting
  filter.
- Assigned species ID and the reserved `unknown` value; an unassigned best
  candidate must not qualify for its candidate ID.
- Eligible matches below the unfiltered top five, proving filters run before limit.
- Default limit 5, positive explicit limits, fewer-than-limit results, stable tied
  boundary, and no duplicate crop identities.
- Query text such as "at night" without automatic metadata filtering; explicit
  filters are never overridden by query wording.

A no-match valid filter is exit 0 with explicit zero results. Invalid dates, unknown
species IDs, nonpositive/fractional limits, and invalid run/context selections fail
actionably rather than returning empty results.

## 5. Provenance and unavailable images

In controlled fixtures, move or make a selected crop locator unreadable without
changing its stored vector/metadata. Search must preserve its rank, score, crop and
representation IDs, source video/frame, capture time/timezone, lighting, detection
box/confidence and species decision/confidence, while setting `image_status` to
`unavailable`. Do not decode the crop, silently omit it, replace it, or reconstruct a
full frame. Missing stored metadata remains null/unknown.

Repeated search is read-only with respect to database records, crop bytes, source
footage, manifests, and species decisions.

## 6. Opt-in PostgreSQL boundary

Only with a separately approved disposable local test database configured through
`BIRD_RECOGNITION_TEST_DATABASE_URL`, run the integration tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration
```

Expected database-boundary cases prove read-only preflight/query behavior, exact run
and config joins, assigned species/date/lighting filtering before limit, preservation
of stable provenance, and separation of valid empty from incompatible/missing
context. Do not point this setting at production/private footage data. A skipped
integration test is not database-boundary evidence.

## 7. Optional retrieval-quality evaluation (not run by this guide)

Controlled ranking tests prove implementation correctness only. Before publishing
retrieval-quality claims, obtain separate approval for a privacy-reviewed collection
and manually label at least 10 distinct text queries against stable crop/frame IDs.
For each query, record its selected run/context, judged relevant IDs, top-five output,
whether at least one relevant item appeared in the top five, and notable failures.
Review target selection by video or day so consecutive near-duplicate frames are not
counted as independent evidence. Report `queries_with_a_relevant_top_five / total
labeled_queries` as the hit rate, along with the numerator, denominator, collection,
context, and failure cases. Keep labels and reports outside the repository. No
quality evaluation or hit-rate result is asserted here; do not present controlled
fixtures or unreviewed outputs as measured semantic retrieval quality.

