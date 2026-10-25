# Quickstart: Validate Crop Embeddings and Species Tags

**Status**: US1–US3 commands and offline correctness contracts are implemented.
The developer reports all 31 opted-in PostgreSQL integration tests passed against
a disposable local database and the built wheel exposes its migration resource.
A 143-crop run and repeat were also reported; reviewed quality evidence exists,
but found poor precision. The controlled acceptance matrix remains incomplete;
these results do not claim reliable species identification.

Run all commands from `C:\code\bird_recognition` in PowerShell 5.1. Use the
existing `.venv`; if absent, stop and ask the developer. Do not activate it.
See [CLI contract](contracts/cli.md) for exact options and schemas,
[data model](data-model.md) for score/count/recovery definitions, and
[AGENTS.md](../../AGENTS.md) for approval and dependency-sync policy.

This runbook is not approval for other work. Get separate developer approval
before source/dependency changes, dependency synchronization, database/service
setup or schema changes, or using private assets, labels, or data. Dependency
declarations belong only in `pyproject.toml`; the developer syncs the environment
and lockfile. `database-init` changes database schema; `index` does not migrate.

## 1. Prerequisites and private paths

- Python >=3.14 with the existing uv environment and implementation dependencies.
  Before implementation, verify OpenCLIP/torchvision compatibility with the existing
  torch constraints and psycopg/pgvector support. Follow repository dependency
  approval/developer-sync policy; do not hand-edit `uv.lock` or downgrade Python.
- Podman Compose and local PostgreSQL 17 pgvector service from `compose.yaml`.
- An ingestion output tree containing `manifest.sqlite3` and retained crops; keep
  ingestion idle while the index command captures its read-only metadata snapshot.
  The SQLite snapshot closes before crop inference begins. No video re-ingestion is
  needed. Keep footage/crops/manifests outside Git.
- Externally provisioned original BioCLIP assets, selected candidate JSON and,
  for quality validation, reviewed labels. No automatic asset download during
  indexing. A tiny candidate file in this guide is illustrative, not a default
  vocabulary or a claim that those species occur in the user's footage.

Use these example external paths, adapted to your own files:

```powershell
Set-Location 'C:\code\bird_recognition'
$manifest = 'C:\bird-data\ingested\manifest.sqlite3'
$model = 'C:\bird-models\bioclip'
$species = 'C:\bird-config\species.json'
$labels = 'C:\bird-eval\labels.json'
$report = 'C:\bird-eval\reports\species-quality.json'
```

The developer prepares `species.json` in the exact schema from the CLI contract,
with local species-level names and unique stable IDs. Prepare directories outside
the repository; never copy private images/reports/credentials into a tracked tree.
Existing privacy filtering does not guarantee anonymity; review any published
examples/labels manually.

## 2. Provision model assets separately

Before a run, the developer obtains `open_clip_config.json` and
`open_clip_pytorch_model.bin` from a chosen immutable revision of
`imageomics/bioclip`, verifies its trusted origin, and places them in `$model`.
Prepare `asset-manifest.json` with schema version 1, upstream name/revision and
both file SHA-256 digests as described in the CLI contract. Record the real
upstream revision, not `main`, and use the original BioCLIP ViT-B/16 configuration.
The implementation adapter also requires OpenCLIP's packaged BPE vocabulary to
be installed locally. Never substitute random weights or another CLIP checkpoint.

You can inspect local file hashes without loading/downloading a model:

```powershell
Get-FileHash -Algorithm SHA256 "$model\open_clip_config.json"
Get-FileHash -Algorithm SHA256 "$model\open_clip_pytorch_model.bin"
```

These local hashes prove file identity, not biological quality or trusted origin.
Provisioning external model assets and reviewing their origin are separate
developer actions; the assets are not bundled with the repository.

## 3. Configure and initialize local storage

Populate the ignored local `.env` using the inventory in `.env.example` after
implementation. Set `BIRD_RECOGNITION_DATABASE_URL` to your private local connection
URL, matching Compose database/user/password/port. No built-in credential default
or fallback storage exists. Do not paste real credentials into documentation or
terminal history. Keep existing `POSTGRES_*` values for Compose itself.

Optional indexing defaults: `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR`,
`BIRD_RECOGNITION_SPECIES_LIST`, `BIRD_RECOGNITION_SPECIES_THRESHOLD` (0.5).
CLI overrides process environment, which overrides `.env`, then built-ins.

Set the Compose credentials in the ignored local `.env` file if changing the
defaults. Start the database and wait until the migration service reports ready:

```powershell
podman compose up -d --build --wait
podman compose ps
```

Compose waits for PostgreSQL, then applies only migrations newer than the stored
schema version. Starting an initialized volume does not reapply completed
migrations; future numbered SQL files are applied on the next `up`. The
`database-init` CLI applies the same migrations for explicit/manual setup, while
`index` remains read-only with respect to schema setup and fails preflight with
exit 2 when the database is not ready. Do not run `podman compose down -v` unless
intentionally deleting the database and its private results.

## 4. Run the unit correctness suite first

Default pytest discovery is limited to `tests/unit`, so this single command runs
all unit tests without collecting smoke or real-database tests.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Expected: no model downloads, DB connection or network in the standard suite;
real-boundary tests skip unless explicitly opted in. Offline tests prove scoring,
validation, provenance and orchestration correctness, not database persistence or
species accuracy. Keep ingest/extract-frame/help usable with no BioCLIP assets or
running database.

## 5. Index, inspect, and repeat

```powershell
.\.venv\Scripts\uv.exe run bird-recognition index --manifest $manifest --model-dir $model --species-list $species --threshold 0.5 --json
.\.venv\Scripts\uv.exe run bird-recognition inspect --list-runs --json
```

Record the actual first command's `run_id` in `$runId`, then inspect it:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition inspect --run-id $runId --json
.\.venv\Scripts\uv.exe run bird-recognition index --manifest $manifest --model-dir $model --species-list $species --threshold 0.5 --json
```

For a controlled 100-readable-crop fixture: first run selects/completes 100,
assigned+unknown=100, zero failures; repeat completes 0/skips 100, zero new
inference and zero duplicate results. Vectors and decisions survive a process
restart. A new inspect process needs only the database, not the model/species file
or readable crops. Check original source/frame/elapsed/detection/capture/lighting
provenance and distinguish detector confidence from species confidence.

Developer-recorded acceptance run (2026-10-23): ingestion processed 9 sources
(270 sampled, 2 person-excluded, 151 with no animal, 117 retained) and produced
143 crops. Index run `fb65c3f8-210c-41a6-987f-52555b3094de` selected/completed
143, assigned 126, marked 17 unknown, failed 0, and reported
`durable_status_confirmed: true`. The repeat run
`86168b1c-04f8-429d-8613-8492218c6279` selected/skipped all 143, completed 0,
and failed 0. The developer confirms the correct checkpoint loaded after fixing
model-loading order. The logged model fingerprint was
`b0290be8181221f3a818c9e7928041ab6a24313f57a560639a0d1797d13c95f8`; that same
fingerprint appeared in an earlier attempt that logged a no-pretrained-weights
warning, so it does not independently establish checkpoint identity. The asset
manifest revision and file hashes were not included in the acceptance record.
This run demonstrates successful processing and repeat skipping, not species
accuracy or completion of the controlled 100-crop/retry/retag/failure/preflight
matrix. Assigned and unknown counts are model outputs, not reviewed correctness
labels.

Warnings must explain candidate-relative confidence, incomparable scores across
candidate sets, and possible high confidence for out-of-list animals. Controlled
scores prove below-threshold/tie unknowns, qualifying threshold equality, and
single-candidate warning. No real model's output guarantees those edge cases;
the correctness suite supplies deterministic cases.

An empty retained-crop manifest with valid prerequisites returns no-input, exit 0,
all counts 0 and no vectors/decisions.

## 6. Retag without re-ingestion or new image inference

```powershell
.\.venv\Scripts\uv.exe run bird-recognition index --manifest $manifest --model-dir $model --species-list $species --threshold 0.7 --json
```

Expected: new decision-config fingerprint, same compatible representation IDs and
image inference count 0; threshold-only changes may reuse stored scores. Select a
different valid species file and rerun: candidate/scoring/config fingerprints
change, only compatible image vectors are reused. Inspect each explicit run;
earlier decisions remain available and are never mixed with the selected config.
Changing the model/checkpoint identity requires new compatible vectors. Relocated
crops use `--crop-root`; moving locators alone does not alter semantic provenance.

## 7. Failure, interruption, and preflight scenarios

Use only disposable copies/fake fixtures, never alter production manifest/crops.

| Scenario | Expected evidence |
|----------|-------------------|
| One missing/corrupt crop among 100 | 99 completed, 1 failed with crop ID/reason, assigned+unknown=99, exit 1 |
| Interrupt after N confirmed commits | Persisted N decisions remain inspectable; next writer marks prior run interrupted and skips N while finishing remainder |
| Inject error between vector and decision inserts | No new partial complete vector/decision; prior committed crops remain usable |
| Change threshold/list after completed run | New decisions reference reused image vectors; old configuration remains inspectable |
| Unavailable database mid-batch | Stop immediately, exit 1, committed-only counts/pending remainder; no claim of unsaved completion |
| Lost commit acknowledgement | Mark work unconfirmed; retry checks durable DB completion before inference |
| Missing/invalid species/model/manifest, NaN or >1 threshold, missing vector extension | Exit 2 before crop-result writes; no backend/download fallback |
| Duplicate/blank candidates or exact-score ties | Reject candidate config preflight; valid tied scores become unknown with all tied IDs/shared score |
| Simultaneous index writer | Second writer exits preflight `writer_busy`; no duplicate inference |

Path/hash checking still applies on repeat index, so a newly unreadable selected
crop is a failure rather than a skip. Inspection of its earlier successful run
continues to work without the image.

## 8. Prove the real persistence/model boundaries separately

Have the developer provision a dedicated disposable local test database and set
`BIRD_RECOGNITION_TEST_DATABASE_URL` in the process environment. Do not point tests
at the private production database. With explicit test opt-in:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration
```

Recorded result (developer-reported): all 31 tests in
`tests/integration/embed/test_storage_integration.py` passed against the configured
disposable local PostgreSQL database. This is real persistence/recovery evidence;
database URLs and credentials are intentionally not recorded. It does not complete
T049's separate 100-crop/retry/retag/99-plus-1/preflight matrix. A skipped test is
not a passed persistence boundary.

The developer also reports a successful wheel build at
`%TEMP%\bird-recognition-wheel-check\bird_recognition-0.1.0-py3-none-any.whl` and
a successful `importlib.resources` read of
`bird_recognition/embed/migrations/001_initial.sql` from that wheel. This verifies
the packaged migration resource (T003/T015); it does not complete T049's remaining
acceptance matrix.

The PostgreSQL integration tests prove database-boundary behavior, not model
execution or biological quality. For optional local-model smoke validation, set
`BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR` and
`BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE` to reviewed external files, then:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\smoke\test_bioclip_smoke.py
```

Expected: no network requests; finite normalized 512-vector and candidate scores.
This proves local adapter execution only; it is optional and is not species-quality
evidence. Actual quality requires separately approved, privacy-reviewed labels and
external model/data, then the measured evaluation gate in section 9.

## 9. Measure actual quality before publishing claims

Prepare labels in the CLI contract's schema, using the actual selected run ID and
crop IDs. Include at least 10 reviewed daylight (`day`) and 10 reviewed night
examples with completed decisions; unknown-lighting examples form a separate
group. Include out-of-list/unidentifiable examples to expose confident false tags.
No generated or fabricated labels/results count as quality evidence.

```powershell
.\.venv\Scripts\uv.exe run bird-recognition evaluate-species --run-id $runId --labels $labels --output $report --json
```

Expected: atomic external JSON report with exact evaluated versions/threshold,
per-lighting sample/completion/correct/incorrect/unknown/failure counts, precision,
assignment and processing coverage, and observed failure cases. Zero denominators
yield null/unavailable. Report unlabeled samples; low precision/coverage is a
measured limitation, not a reason to omit a group. `publication_ready` only checks
minimum sample coverage, never certifies accuracy. If real labeled examples are
unavailable, explicitly leave SC-007 unmet and publish no quality claims.

Reviewed biological-quality evaluation (2026-10-24): report
`1c44f970-9941-4b1b-b702-f64a72b97b6d` evaluated run
`d944a363-bf92-4cc5-96be-4c64d5cfdf2c` with model fingerprint
`b0290be8181221f3a818c9e7928041ab6a24313f57a560639a0d1797d13c95f8` and
threshold 0.5. It covered 10 completed day and 10 completed night labels, so
`publication_ready` was true for the sample-count gate only. Day: 9 assigned,
2 correct, precision 0.2222, assignment coverage 0.9, processing coverage 1.0;
night: 4 assigned, 0 correct, precision 0.0, assignment coverage 0.4, processing
coverage 1.0. There were no unknown-lighting labels in this reviewed cohort;
the report's unknown group had sample count 0. The report documented failure
examples and 194 unlabeled run items. These are measured results, not a positive
quality finding: precision was low, and this workflow makes no claim of reliable
species identification. The report and labels remain external; only non-private
aggregate metrics and evaluation/run IDs are retained here. This evaluation
completes the evidence requirement for SC-007/T050, not the separate T049
acceptance matrix. The model fingerprint identifies the tested model contract;
as noted above, it does not independently authenticate checkpoint origin.

## 10. Final implementation checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\uv.exe run ruff check .
.\.venv\Scripts\uv.exe run ruff format --check .
```

Document exact results, including skipped integration/smoke tests and any unmet
quality evidence gate. No source code, dependencies, services or private data are
created by this planning guide itself.
