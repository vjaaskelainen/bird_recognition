# Quickstart: Validate Crop Embeddings and Species Tags

**Status**: US1 commands and offline contracts are implemented. Real PostgreSQL,
installed-wheel, provisioned-model, and US2/US3 acceptance gates remain pending.

Run all commands from `C:\code\bird_recognition` in PowerShell 5.1. Use the
existing `.venv`; if absent, stop and ask the developer. Do not activate it.
See [CLI contract](contracts/cli.md) for all options/formats and
[data model](data-model.md) for score/count/recovery definitions.

## 1. Prerequisites and private paths

- Python >=3.14 with the existing uv environment and implementation dependencies.
  Before implementation, verify OpenCLIP/torchvision compatibility with the existing
  torch constraints and psycopg/pgvector support. Follow repository dependency
  approval/developer-sync policy; do not hand-edit `uv.lock` or downgrade Python.
- Docker/Compose and local PostgreSQL 17 pgvector service from `compose.yaml`.
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
No real BioCLIP assets were provisioned by the planning workflow.

## 3. Configure and initialize local storage

Populate the ignored local `.env` using the inventory in `.env.example` after
implementation. Set `BIRD_RECOGNITION_DATABASE_URL` to your private local connection
URL, matching Compose database/user/password/port. No built-in credential default
or fallback storage exists. Do not paste real credentials into documentation or
terminal history. Keep existing `POSTGRES_*` values for Compose itself.

Optional indexing defaults: `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR`,
`BIRD_RECOGNITION_SPECIES_LIST`, `BIRD_RECOGNITION_SPECIES_THRESHOLD` (0.5).
CLI overrides process environment, which overrides `.env`, then built-ins.

After explicit approval for service/schema setup, run:

```powershell
docker compose up -d postgres
docker compose ps
.\.venv\Scripts\uv.exe run bird-recognition database-init --json
```

Expected: healthy local service; extension/schema initialized transactionally with
schema/version response. Repeat initialization: no destructive changes. Indexing
without schema/vector support must instead fail preflight with exit 2. Extension
permission errors require developer/admin setup; indexing must not repair them
silently. Do not stop/delete a database containing private results for testing.

## 4. Run the offline correctness suite first

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests\embed
```

Expected: no model downloads, DB connection or network in the standard suite;
real-boundary tests skip unless explicitly opted in. Offline tests prove scoring,
validation, provenance and orchestration correctness, not species accuracy.
Keep ingest/extract-frame/help usable with no BioCLIP assets or running database.

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
.\.venv\Scripts\python.exe -m pytest tests\embed\test_storage_integration.py
```

Expected: real pgvector roundtrip, schema/vector preflight errors, dimensional and
unique constraints, atomic rollback, restart recovery, concurrent writer lock and
connection-loss handling pass. Run before feature acceptance; a skipped test is
not a passed persistence boundary.

For optional local-model smoke validation, set
`BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR` and
`BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE` to reviewed external files, then:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\embed\test_bioclip_smoke.py
```

Expected: no network requests; finite normalized 512-vector and candidate scores.
This proves adapter execution only, not species-quality targets.

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

## 10. Final implementation checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\uv.exe run ruff check .
.\.venv\Scripts\uv.exe run ruff format --check .
```

Document exact results, including skipped integration/smoke tests and any unmet
quality evidence gate. No source code, dependencies, services or private data are
created by this planning guide itself.
