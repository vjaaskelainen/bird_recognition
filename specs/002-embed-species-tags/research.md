# Research: Crop Embeddings and Zero-Shot Species Tags

**Date**: 2026-10-19 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

All design questions are resolved below. Compatibility and quality checks are
implementation acceptance gates, not claims of completed experiments.

## 1. BioCLIP variant, local provisioning, and dependency gate

**Decision**: Use original `imageomics/bioclip` (ViT-B/16, image size 224,
512-dimensional image/text embeddings, CLIP context length 77). Use
`open-clip-torch` rather than a model wrapper that fetches weights implicitly.
Provision an external asset directory containing `open_clip_config.json`,
`open_clip_pytorch_model.bin`, and a project `asset-manifest.json` that names the
upstream repository and immutable revision and records SHA-256 hashes. Keep all
assets outside Git. Setup downloads are a separate, deliberate developer action.

The adapter validates architecture/config/checkpoint hashes and strict checkpoint
loading. Instantiate built-in `ViT-B-16` without pretrained downloads and load the
validated local checkpoint using OpenCLIP's checkpoint loader; use the supplied
BioCLIP preprocessing values and OpenCLIP's packaged CLIP BPE tokenizer. Explicitly
disable pretrained image/text tower fetching. Reject hub identifiers or fallback
pretrained tags at runtime. Use eval mode, inference mode, CPU float32, deterministic
evaluation transforms, and normalized embeddings. No random-weight fallback.
Network-denied adapter tests prove loading/inference never make a network request;
offline environment flags alone are not sufficient proof.

Model identity hashes the asset contents, upstream revision, architecture,
preprocessing, tokenizer/BPE digest, adapter contract version, relevant library
versions, precision and device policy. A file path or mutable upstream name alone
is not a model version. Record the actual checkpoint logit scale.

**Rationale**: BioCLIP's public config confirms compatible 512-dimensional towers.
Explicit local loading avoids inference-time Hugging Face downloads and captures
the real reproducibility boundary. Original BioCLIP is a small, bounded choice;
the feature does not require BioCLIP 2 or a taxonomy package.

**Alternatives considered**: `hf-hub:imageomics/bioclip` loading (can fetch files);
`pybioclip` convenience pipeline (unneeded taxonomy/download behavior); BioCLIP 2
(larger scope/assets); training or a generic CLIP substitute (violates intent).

**Evidence inspected on 2026-10-19**:

- https://huggingface.co/imageomics/bioclip/raw/main/open_clip_config.json
  (`embed_dim=512`, ViT-B/16 configuration, normalization means/stds).
- https://github.com/mlfoundations/open_clip/blob/main/src/open_clip/factory.py
  (`create_model`, `load_checkpoint`, `get_tokenizer`, local checkpoint handling).
- https://github.com/mlfoundations/open_clip/blob/main/src/open_clip/tokenizer.py
  (tokenizer implementation; implementation must verify packaged BPE availability).

These mutable source references explain the design; the provisioned asset manifest
and locked implementation dependencies must identify immutable versions.

**Implementation gate**: Existing runtime requires Python >=3.14 and
torch >=2.14.1,<2.15. Verify a released `open-clip-torch`, compatible torchvision,
`psycopg[binary]` 3.x, and `pgvector` adapter resolve and run on this environment.
Record exact selected versions in the implementation change. No dependency was
installed or resolved during planning. Respect repository policy: declaration
edits only in `pyproject.toml`, developer syncs the environment/lock. If incompatible,
stop and report evidence rather than downgrade Python or swap model/storage.

## 2. Candidate file, prompting, and scoring

**Decision**: UTF-8 JSON with `schema_version: 1` and nonempty `species` array of
`{id, name}` objects. Trim identifiers/names, reject blanks, reserve `unknown`,
reject case-insensitive duplicate IDs and names using Unicode casefold, and reject
unknown fields/types. No biological taxonomy validation or synonym merging.
Sort entries by stable ID for canonical UTF-8 JSON hashing; order/whitespace alone
do not change the content version, but spelling/case/name/identifier changes do.
Save the canonical content, not only its file path or hash.

Use one prompt per name: `a photo of {name}.` (prompt contract `species-photo-v1`).
For unit-normalized image vector u and text vectors t_i, compute logits
`L_i = exp(model.logit_scale) * dot(u, t_i)` and numerically stable float64 softmax
`p_i = exp(L_i - max(L)) / sum_j exp(L_j - max(L))`. Validate scale, logits and
scores are finite; validate final scores in [0,1]. Rank by logits; exact equal
maximum logits are ties (not approximate ties or display-rounded equal scores).
Store tied IDs and their shared score with no unique best candidate. Unique maxima
qualify at `score >= threshold`; otherwise unknown. The single-candidate score is
1 and carries an additional limited-vocabulary warning.

Persist all candidate scores/logits, ordered candidate IDs, prompt, scale,
normalization, softmax and tie-policy versions, threshold and model fingerprint.
This is small enough for a local species list and permits fully offline inspection.
The scoring fingerprint excludes threshold; the decision-config fingerprint
includes threshold. Changed threshold can reuse stored scores; changed candidates
reuse only compatible image vectors and recompute text comparisons. A run needing
new scores encodes its candidate texts once, not once per crop.

**Rationale**: A specified relative-confidence calculation is testable and exposes
why changing the candidate set changes confidence. Unknown is a decision, not an
extra text candidate. Exact ties and threshold equality are deterministic.

**Alternatives considered**: raw cosine mapped to [0,1] (different confidence
semantics); sigmoid (different training/scoring assumption); arbitrary temperature
(not checkpoint scoring); prompt ensembles (unneeded configuration surface);
nearest labeled crop or LLM classification (explicitly excluded).

## 3. Manifest boundary and provenance

**Decision**: Open existing SQLite via URI `mode=ro`, query-only connection and a
consistent read transaction. Do not construct ingestion's writing `Manifest`
class, run migrations, call ingestion recovery, or request journal changes.
Validate tables/columns, integrity and required relationships before result writes.
Select all `animal_crop` rows joined to `source_video`, `sampled_frame`, and the
matching qualified animal `detection`; accept durable retained crops even if their
ingestion run ended partially failed. Order by crop ID for reproducible selection.
Reject inconsistent retained/detection joins as invalid manifest, rather than
silently dropping crops. Copy all available provenance into PostgreSQL.

The actual schema has provenance on `animal_crop`, normalized detector boxes on
`detection`, and source content/path identity on `source_video`. It is not a single
flat JSON manifest. Resolve relative image paths against the manifest directory;
`--crop-root` allows relocation without changing semantic crop identity. Reject
relative traversal/symlink escape outside the crop root. Preserve original paths
separately from resolved locators. Hash and check each selected readable crop
against `crop_sha256` before reuse or inference; read/hash errors are isolated
crop failures. No image decoding or inference for unchanged completed decisions.

Define a provenance digest over ingestion identity, content hashes, original
source/frame/detection/capture/lighting metadata and original relative crop path;
exclude run-local resolved paths and manifest location. Key snapshots by crop ID
plus this digest. Thus manifest relocation does not invalidate vectors, but
changed source metadata/content cannot silently inherit an earlier result.

**Rationale**: Stable ingestion IDs are already available, but no cross-database
foreign key exists. A durable provenance snapshot is inspectable after a restart
without reopening footage or SQLite. Unknown values stay null/`unknown`.

**Alternatives considered**: changing ingestion to PostgreSQL (unnecessary scope);
copying only crop ID/path (loses evidence); file path or mtime as identity (unsafe);
SQLite `immutable=1` (can ignore live WAL state); modifying source manifest
(forbidden). Require ingestion to be idle while snapshotting, without changing it.

## 4. Persistence, idempotence, concurrency, and recovery

**Decision**: Reuse Compose `pgvector/pgvector:pg17`. Use psycopg direct SQL and
the pgvector adapter, with `vector(512)` normalized image vectors. No ANN index:
this feature does no general similarity search. Explicit `database-init` creates
the extension and versioned schema in a transaction. Indexing only validates
connection, vector support, schema version, permissions and dimensions; it never
silently creates/migrates or substitutes a backend. Model variants with different
dimensions need an explicit future migration, not accidental vector reuse.

Per crop, transactionally write provenance/model/candidate/config references,
representation, decision, run-item status and summary counters. Never persist a
new vector as complete without its first completed decision. Existing vectors
remain usable if a later retag transaction fails. Unique keys enforce one vector
per crop snapshot/model and one decision per representation/config. Commit before
counting a crop as successful. Keep historical decisions: no ambiguous global
"latest" tag. Inspection is run/config-scoped.

Take one nonblocking session-level advisory writer lock for the feature/database
before recovering/starting runs; a second index command fails preflight. This is
appropriate for a single local owner and prevents duplicate inference races.
Inspection uses independent read-only connections. After acquiring the lock and
passing all preflight checks, mark previous running batches interrupted; their
committed decisions/counters remain intact and uncommitted work rolls back.
Retry creates a new run and skips those decisions. Complete cached decisions are
checked before any text/image inference, although model assets remain a preflight
requirement. All selected items are recorded as pending after preflight.

Classify missing/corrupt image, invalid vector/score, and isolated inference errors
as per-crop failures while storage/model remain healthy. A broken shared model
session stops further processing. Any storage write/connection failure stops the
batch, exits 1 and emits committed-only counts to stderr/stdout as appropriate;
do not continue on the assumption rollback restored service. If durable final
status cannot be written, leave the run running for next-run recovery and report
that limitation. A commit with lost acknowledgement is unconfirmed, not counted
as success locally; retry consults durable unique records before inference.

**Rationale**: Database transactions are the durable completion boundary. SQLite's
`BEGIN IMMEDIATE` pattern is not PostgreSQL syntax; use ordinary PostgreSQL
transactions plus the advisory lock. Explicit setup separates administrative DDL
from processing and makes missing vector support a clear preflight error.

**Alternatives considered**: ORM/general migration framework (unneeded layer);
per-row autocommit (partial completion); durable vectors before decisions
(breaks initial completion contract); continuing after DB errors (false success);
overwriting old tags (loses configuration context); multiple writer workers
(not required).

## 5. CLI, configuration, and private data

**Decision**: Add `index`, `inspect`, `evaluate-species`, and `database-init`
subcommands to the existing entry point. See [contracts/cli.md](contracts/cli.md).
Preserve explicit CLI > process environment > local `.env` > default precedence.
Use explicit/environment asset/species paths; no built-in candidate list.
Use a full database URL with no credential default and finite [0,1] threshold
default 0.5. Existing `POSTGRES_*` variables remain Compose configuration, not an
implicit competing connection-string source.

Lazy feature imports ensure ingest/extract-frame/help need no new assets or live
DB. DB-only inspection/evaluation must not instantiate BioCLIP, read crops, or
validate a current species file. Persist canonical candidate/model/config content
so inspection does not depend on local file availability. Never echo connection
URLs/passwords in logs, run settings, exception traces, reports or JSON.

Exit 0 for complete/no-input; 1 for processing/operational failures; 2 for
preflight/usage errors. Strict JSON output is versioned separately from human text.
Output reports and prepared labels follow existing external-destination/privacy
rules. Add every new environment variable to `.env.example` during implementation.

**Alternatives considered**: implicit latest decisions (ambiguous vocabulary);
automatic DB/model setup during indexing (violates preflight/offline boundaries);
copying `.env` secrets into saved settings (unsafe).

## 6. Quality evidence and validation layers

**Decision**: Evaluate persisted decisions for an explicit run against prepared
labels keyed by crop ID. Emit day (`daylight` label in documentation), night and
unknown-lighting groups separately. Count correct/incorrect assigned tags,
unknowns and processing failures; precision = correct/assigned, coverage =
assigned/completed labeled decisions. State labeled/selected/completed/failed
denominators explicitly so failures cannot inflate coverage unnoticed. Missing
decisions count as unavailable, not unknown. Empty groups or zero denominators
produce JSON null / human `unavailable`, never 100%.

Include model/candidate/scoring/threshold identifiers, per-example failure cases
(wrong assignment, unknown reason, out-of-list label, read/inference failure), and
notes about candidate-relative confidence. Labels may mark truth out of list or
unidentifiable; any assignment to these examples is incorrect. A label must be a
nonblank species identifier or null for those non-assignable examples.
Skipped successful items evaluate through their referenced stored decision.

Unit/contract tests use fake inference and store with known vectors. Real database
tests are opt-in, use a dedicated disposable DB and prove pgvector roundtrip,
atomic rollback, unique keys, recovery and loss behavior. Standard pytest never
needs a DB/model/network. Real-model smoke tests require explicit local assets;
real quality reports need >=10 labeled day and >=10 labeled night crops before
publication. Do not invent quality results if those examples are unavailable.

**Alternatives considered**: evaluating on fake scores as accuracy evidence;
dropping unknowns/night examples; scoring empty groups as perfect; treating unknown
as an inference failure. All would hide feature limitations.
