# Usage and local workflows

This guide contains operational instructions for the workflows summarized in the
[project README](../README.md). Feature contracts and validation evidence remain
in the linked feature documents; this guide is for operating the implemented
commands.

Keep source footage, outputs, manifests, crops, model assets, candidate lists,
evaluation labels, and reports in private locations outside the Git repository.
Do not publish crops or extracted frames without reviewing them for people and
other sensitive content. Person filtering is not a guarantee of anonymity.

## Configure local defaults

On first setup, create `.env` from [`.env.example`](../.env.example) if it does
not exist, and keep local values in `.env` (ignored by Git). Explicit CLI options
override process environment values, which override `.env` values and built-in
defaults. `.env.example` is the complete environment-variable inventory.

## Ingest local videos

The `bird-recognition ingest` command recursively scans local video directories
and writes retained animal crops and a SQLite provenance manifest. It uses the
MIT-licensed MegaDetector V6 variant `MDV6-mit-yolov9-c`; provision its `.ckpt`
weights and `config_v9s.yaml` locally, outside Git. Both files are required and
are never downloaded by ingestion.

Keep input footage and output disjoint and outside the repository. Supported
extensions are `.mp4`, `.mov`, `.m4v`, `.mkv`, `.avi`, `.mpeg`, and `.mpg`.
Sampling defaults to one second; animal and person confidence thresholds default
to `0.2` and qualify inclusively.

Crop context is opt-in: `--crop-policy context-v1` defaults to 10% expansion on
each side, clipped to the frame; `--crop-context` overrides the fraction. The
legacy policy defaults to no expansion. Changed effective crop settings create
new crop identities and preserve historical files and manifest rows.

```powershell
.\.venv\Scripts\uv.exe run bird-recognition ingest `
  --input "D:\trail-camera\videos" `
  --output "D:\trail-camera\ingested" `
  --model "D:\models\MDV6-mit-yolov9-c.ckpt" `
  --model-config "D:\models\config_v9s.yaml"
```

The output contains `manifest.sqlite3` and retained crops. The summary separates
processed, skipped, and failed sources from mutually exclusive frame outcomes
and crop count. Exit codes are `0` for complete/no-input, `1` for processing
failures, and `2` for preflight errors. Capture time is unknown when reliable
camera metadata is unavailable; filesystem timestamps are never substituted.

Optional CLI defaults, including model paths, can be set in `.env`; see
[`.env.example`](../.env.example). For setup, fixture validation, batch recovery,
and implementation/acceptance details, see the [ingestion quickstart](../specs/001-ingest-videos/quickstart.md),
[CLI contract](../specs/001-ingest-videos/contracts/cli.md), and
[V6 upgrade plan](../specs/001-ingest-videos/megadetector-v6-upgrade-plan.md).

## Extract a single frame

Extract a full-resolution PNG without loading MegaDetector:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition extract-frame `
  --input "D:\trail-camera\videos\camera.mp4" `
  --timestamp 2.5 `
  --output "D:\trail-camera\frames"
```

The timestamp must be finite and non-negative, in seconds relative to the first
decoded frame. The command saves the first frame at or after that time as
`camera.mp4_frame_2.5s.png` and prints its path. It creates the output directory
when a matching frame is found and refuses to overwrite existing images.
Requests beyond the last frame fail rather than returning an earlier frame.
Exit codes are `0` for success, `1` for decoding/timing failures, and `2` for
invalid inputs or destinations. The reusable `extract_frame` helper in
`bird_recognition.cli` accepts the same three inputs and returns the saved path.

Keep input footage and output outside Git, with the output separate from the
input video's directory tree. Unlike ingestion, extraction performs **no person
filtering**: full frames may contain people or other sensitive content. Keep
them private and review them before sharing.

## Local database

Start the local PostgreSQL + pgvector service and wait for database migrations
to finish with Podman Compose:

```powershell
podman compose up -d --build --wait
```

Compose waits for PostgreSQL, then a lightweight migration service applies any
pending numbered SQL migrations and stays healthy only while the database is at
the packaged migration head. Existing migrations are skipped, including on
stop/start; future migrations are applied on the next `up`. The persistent volume
preserves the database across `podman compose down` and restarts. Do not use
`podman compose down -v` unless intentionally deleting the database.

Compose reads `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and
`POSTGRES_PORT` from `.env` (with defaults in `.env.example`). The migration
service also creates the pgvector extension when needed. Set the private
`BIRD_RECOGNITION_DATABASE_URL` in `.env` to connect the application to this local
database; it must match your local Compose settings. The application does not
derive a URL from `POSTGRES_*` or supply a built-in credential default. For
explicit/manual setup, initialize the schema after the database is ready:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition database-init
```

Indexing never installs extensions or migrates the schema.

## Crop embeddings and species tags

Indexing is an optional local workflow layered on ingestion. It reads the existing
SQLite manifest and retained crops without changing them; ingestion and
`extract-frame` remain usable without BioCLIP assets or the embedding database.

Dependencies are declared in `pyproject.toml` and provisioned with the project
environment. Obtain the original pretrained `imageomics/bioclip` ViT-B-16 bundle
separately from a trusted immutable upstream revision. The local model directory
must contain `open_clip_config.json`, `open_clip_pytorch_model.bin`, and a valid
`asset-manifest.json` with the revision and file SHA-256 values. The adapter uses
the tokenizer vocabulary packaged with OpenCLIP and never downloads weights or
falls back to random weights. Model paths and assets are private and must remain
outside the repository.

The species list is required; there is no implicit vocabulary. Copy
[`species.json.example`](../species.json.example) to a private location and edit
it for the intended candidates. It is schema 2: each entry has a stable unique
`id`, `kind` (`species` or `category`), `common_name`, and
`taxonomic_description`; category entries additionally require `category`
(`bird` or `mammal`). A schema-2 list must contain exactly one broad bird and one
broad mammal candidate. Species descriptions should use owner-verified taxonomy;
no remote taxonomy service validates these values. Entry order does not affect
the candidate fingerprint.

Schema-2 text prompts use both descriptive fields exactly as
`a photo of {common_name} ({taxonomic_description}).` and are versioned as
`species-taxonomy-photo-v2`. A selected bird or mammal category is a coarse
outcome, not a confirmed species; category matches are reported separately and
never count as exact species correctness. Keep the legacy schema-1 prompt
(`a photo of {name}.`, `species-photo-v1`) reproducible with
[`species.schema1.json.example`](../species.schema1.json.example); schema-1
candidate files remain supported and are not rewritten. Both examples are
illustrative formats, not regional checklists. Configure
`BIRD_RECOGNITION_BIOCLIP_MODEL_DIR`, `BIRD_RECOGNITION_SPECIES_LIST`, and the
required private `BIRD_RECOGNITION_DATABASE_URL` in ignored `.env`, or supply the
supported command options. `BIRD_RECOGNITION_SPECIES_THRESHOLD` defaults to `0.5`;
explicit CLI options override process environment, which overrides `.env`.

Use one explicit manifest and inspect the resulting run by its returned ID:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition index --manifest "D:\trail-camera\ingested\manifest.sqlite3" --json
.\.venv\Scripts\uv.exe run bird-recognition inspect --run-id "<run-id-from-index>" --json
```

New index setups default to `--input-view fit-pad-v1`, preserving the complete
rectangular crop with square padding, and minimum crop dimensions of 32 by 32
pixels (`--minimum-crop-width` / `--minimum-crop-height`). Undersized crops produce
completed but unassigned `low_quality` decisions, not inference failures. The
historical `legacy-center-crop-v1` view remains explicitly selectable. Changing
the input view changes representation identity and requires compatible new vectors.
Optional `--minimum-margin` adds a top-two candidate-score gap requirement to
`--threshold`; below-threshold, below-margin, and tied decisions remain unassigned.

Repeat the index command to retry/resume and skip compatible completed work. To
retag with a new threshold or candidate file, index the same manifest with the new
selection; the command creates a versioned decision while reusing compatible
stored image vectors:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition index --manifest "D:\trail-camera\ingested\manifest.sqlite3" --threshold 0.7 --json
.\.venv\Scripts\uv.exe run bird-recognition index --manifest "D:\trail-camera\ingested\manifest.sqlite3" --species-list "D:\bird-config\alternate-species.json" --json
```

Inspecting an explicit run reads persisted data and does not require current model
files, species files, crops, or inference. Species confidence is candidate-relative,
not a calibrated probability of biological correctness; candidate-set scores are
not comparable, and an out-of-list animal may score highly. Treat tags as
suggestions and review measured errors before relying on them.

Evaluate reviewed labels against one persisted run. Keep both labels and report in
private external paths; evaluation reads stored decisions and does not load model
assets or images:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition evaluate-species --run-id "<run-id>" --labels "D:\bird-eval\labels.json" --output "D:\bird-eval\reports\species-quality.json" --json
```

The day/night sample-count gate is not an accuracy guarantee. Review measured
precision, coverage, and failure examples; do not publish claims beyond the
reviewed results. See the [crop-embedding quickstart](../specs/002-embed-species-tags/quickstart.md)
for model provisioning, retry/retag scenarios, acceptance evidence, and the
measured evaluation results, and the [CLI contract](../specs/002-embed-species-tags/contracts/cli.md)
for command details.

## Classification quality and optional decision paths

These commands use the configured local database. Keep labels, reference/group
manifests, assets, and reports outside Git. Reports refuse overwrite; use a new
output filename and an existing external parent directory. Examples below show
command forms, not authorization to access private data or start services.

### Blind review and paired comparisons

Use the existing `tools/review_csv.py create`, `tools/review_crops.py`, and
`tools/review_csv.py to-labels` workflow. Shared schema-2 labels record an
independent review taxonomy, label role, source-video/day split, and `case_id`.
A case identifies the unchanged source/frame/detection across crop-policy
variants; a crop ID identifies one setup-specific saved image. Neither is a visit.
Keep tuning and held-out cohorts disjoint and do not expose predictions during
blind review. See the [classification quickstart](../specs/004-improve-species-classification/quickstart.md#1-establish-blind-labels-from-the-existing-workflow)
for the complete review/export sequence.

Compare at least two explicit run IDs against the same shared labels:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition compare-species `
  --run-id "<baseline-run-id>" --run-id "<comparison-run-id>" `
  --labels "D:\bird-eval\held-out-labels.json" `
  --output "D:\bird-eval\reports\comparison.json" --json
```

Comparison reads persisted decisions without model inference. Inspect paired,
unpaired, failed, low-quality, species, and coarse-category outcomes separately.
The day/night sample-count gate never proves accuracy; tuning labels cannot
support publication-quality claims.

### Optional reference-assisted classification

Enable reviewed references explicitly on `index` with `--reference-set PATH`,
`--reference-min-similarity VALUE`, and `--reference-min-agreement VALUE`.
The external manifest pins model/input-view identities and reviewed image hashes.
References must be disjoint from indexed examples under the selected verified
split: source video by default, or explicit `--reference-split-mode recording_day`
when every day is known. A qualifying match records `reference_match`; weak or
inconsistent evidence records `zero_shot_fallback`. These are decision paths,
not uncertainty reasons such as `below_margin`. Without references, indexing
uses the zero-shot path. No reference similarity is a biological probability.

### Explicit visits and capped model benchmarks

A visit is an owner-reviewed, confident association of at least two crops from
one source video, supplied through an external group manifest. Same-video
membership alone is insufficient. Aggregation averages compatible candidate
logits and reapplies threshold/margin; the derived report links contributors
without changing crop-level decisions or inflating crop-level sample counts.

```powershell
.\.venv\Scripts\uv.exe run bird-recognition aggregate-visits `
  --run-id "<run-id>" --groups "D:\bird-eval\visit-groups.json" `
  --output "D:\bird-eval\reports\visits.json" --json
.\.venv\Scripts\uv.exe run bird-recognition benchmark-species `
  --run-id "<run-id>" --labels "D:\bird-eval\held-out-labels.json" `
  --model-dir "D:\bird-models\bioclip" --max-crops 40 `
  --output "D:\bird-eval\reports\benchmark.json" --json
```

Benchmarking runs local inference on a deterministic capped held-out cohort
(`--max-crops` is required and at most 500), reports elapsed time and quality,
and never changes the default model. Only the supported `bioclip` adapter is
available; BioCLIP 2 is not silently substituted. See the
[classification CLI contract](../specs/004-improve-species-classification/contracts/cli.md)
for exact reference/group schemas, options, report fields, and split rules.

## Search indexed crops with text

Search uses one explicitly selected indexed run and its exact model/tagging context.
The run must be `complete` or a valid empty `no_input` run; partial, failed, or
incompatible runs are errors, not empty results. Use `inspect --list-runs` to find
available run IDs, then inspect the selected run before searching. Search requires
the existing local PostgreSQL/pgvector database and the local BioCLIP ViT-B-16 bundle
used to create that run's vectors. The loaded model fingerprint must match exactly.
Search is read-only: it does not migrate the database, download assets, contact a
service, load crop images for inference, or re-embed stored crops. Keep the database,
model assets, footage, and crops local and outside Git.

Provide the database URL and model directory with command options or the existing
`BIRD_RECOGNITION_DATABASE_URL` and `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR` settings.
Precedence is command-line option, process environment, then discovered `.env`; there
are no built-in database credential or model-path defaults. Keep credentials private
and avoid putting database URLs in shell history.

```powershell
Set-Location 'C:\code\bird_recognition'
$runId = '<completed-index-run-uuid>'
$model = 'D:\bird-models\bioclip'
.\.venv\Scripts\uv.exe run bird-recognition search "squirrel on the feeder" `
  --run-id $runId `
  --model-dir $model `
  --limit 5 `
  --json
```

The positional query must be nonblank. Optional `--start-date YYYY-MM-DD` and
`--end-date YYYY-MM-DD` bounds are inclusive recorded calendar dates; a missing
capture time does not match a supplied date bound, and timezone conversion is not
performed. `--lighting` accepts exactly `day` or `night`; unknown lighting does not
match either. `--species-id` accepts a candidate ID from the selected run or the
reserved `unknown` value, which selects unassigned decisions rather than best-candidate
suggestions. All supplied filters are combined over the full eligible set before
ranking and limiting. Query wording never sets metadata filters.

Results are crop-level evidence with stable crop/representation and selected decision
identities, source/frame references, and available capture, lighting, detection, and
species-decision provenance. Missing metadata is shown as `null` or `unknown`. An
unavailable crop image remains in its ranked position with its score and provenance;
`image_status` indicates availability. Cosine similarity is relative retrieval
relevance in `[-1, 1]`, not a probability or confirmation that the query is true.
Species confidence is candidate-relative, while detection confidence is a separate
detector score. None proves species identity or event occurrence.

With `--json`, search emits a schema-versioned outcome. Exit `0` means results were
returned or the valid search found zero matches; the latter is not evidence that an
event is absent from all footage. Exit `2` indicates invalid input, selection, context,
or preflight requirements; exit `1` indicates an operational failure. Failures are
distinct from successful empty searches and do not present partial results as complete.
See the [search CLI contract](../specs/003-search-crops/contracts/cli.md) and
[search quickstart](../specs/003-search-crops/quickstart.md) for output fields and
validation scenarios.

### Optional text-search quality evaluation

Do not claim retrieval quality from controlled tests or unreviewed output. Before
publishing a quality claim, obtain separate approval for a privacy-reviewed local
collection and manually label at least 10 distinct text queries. Record each query's
selected run and model/tagging context, reviewed relevant target crop/frame IDs, and
the top-five result IDs. Select targets by video or day and review near-duplicate
frames so consecutive crops are not counted as independent evidence. For each query,
record whether at least one reviewed relevant item appears in the top five, along with
notable failures.

Report the hit rate as
`queries_with_a_relevant_top_five / total_labeled_queries`, including the numerator,
denominator, selected collection/context, target-selection method, and failure cases.
Keep footage, crops, labels, and generated reports outside the repository. No measured
text-search quality is asserted by this guide.

