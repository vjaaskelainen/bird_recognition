# Research: Text Search over Wildlife Crops

**Date**: 2026-10-25 | **Related**: [spec.md](spec.md), [plan.md](plan.md)

## Decisions

### 1. Use the existing BioCLIP representation contract and raw cosine similarity

- **Decision**: Load the existing local BioCLIP adapter, require its complete model fingerprint to match the selected indexed run, and embed the query once. Compute cosine similarity using float64 accumulation and the measured norms of query and stored 512-vectors, clamping only floating-point drift to `[-1, 1]`. Validate vector dimensions, norms, query output, and every eligible score for finiteness before truncating results. Order descending by score, then ascending stable `crop_id`.
- **Rationale**: `BioClipModel.encode_texts()` and the stored representations both use normalized vectors; model fingerprints include checkpoint, tokenizer, preprocessing, adapter, and runtime identity. Raw cosine avoids confusing a scaled model logit with a probability and has an explicit, bounded range. The persisted logit scale is part of species-tagging scoring, not required for cosine ranking.
- **Alternatives considered**: Scaled BioCLIP logits preserve the same order but have model-dependent magnitude and can be misread as calibrated confidence. Re-encoding crop files violates the stored-representation/search-only requirement. Approximate vector-index search is unnecessary here and could change exact, tie-boundary behavior.

### 2. Select one complete indexed collection/context by explicit index run ID

- **Decision**: Require `--run-id` to select a successful indexing run. Treat its selected crop IDs as the collection and its persisted `config_fingerprint` as the single tagging context; that config identifies the candidate set and model. Search only completed/skipped run items joined to their exact persisted decisions, representations, and snapshots. Accept `complete` runs and valid `no_input` runs; reject partial, failed, interrupted, missing, or incompatible runs. Use the loaded local model only when its fingerprint exactly matches the run's model fingerprint. Existing `inspect --list-runs` and `inspect --run-id ...` provide context discovery and details.
- **Rationale**: The schema has no first-class collection table, but `processing_run` records a stable selected set via its run items and selection fingerprint and pins a config. `run_item` has one row per crop, including skipped items linked to the actual compatible decision. Requiring explicit run selection avoids silently mixing model/tagging versions and avoids interpreting partial indexing as a complete collection. `no_input` is a verified empty collection.
- **Alternatives considered**: Implicitly selecting the latest run is unstable and obscures user choice. Combining all snapshots or all distinct configs would duplicate crops and mix model/tagging contexts. A new collection table/migration is outside scope.

### 3. Apply metadata predicates before ranking/limit and use stored assigned decisions

- **Decision**: Filter the complete run-scoped eligible set using stored `capture_time` calendar dates (inclusive, parsed without timezone conversion), exact `day`/`night` lighting, and the selected context's `assigned_species_id` (`NULL` maps to `unknown`). Validate requested species IDs against the selected candidate set, with `unknown` reserved for null decisions. Apply every predicate before scoring/ranking and apply the limit only after all eligible scores have been validated.
- **Rationale**: This meets FR-004–FR-007 and prevents filtering an already truncated top-N. Ingestion derives capture values with ISO-8601 parsing and preserves local text plus an optional timezone separately. The date filter uses the recorded text date; missing dates never qualify when a date bound exists.
- **Alternatives considered**: Filesystem/index timestamps, elapsed video time, timezone assumptions, best-candidate fallback, and candidate score thresholds contradict the specification.

### 4. Preserve provenance while representing image availability separately

- **Decision**: Return ranked stored matches independently from local image availability. Use the selected run item's resolved input locator for a read-only local-file availability/readability check; never use image contents to score, replace a missing image, or drop its result. Return stable crop ID, snapshot ID, representation UUID, decision/config identity, source/frame/capture/lighting/detection provenance, and nullable fields explicitly.
- **Rationale**: `run_item.resolved_input_locator` captures the effective crop path used for that selected run, including relocated roots; crop images are not needed once vectors are indexed. Existing snapshot rows retain original provenance. Availability is inspection metadata, not a ranking prerequisite.
- **Alternatives considered**: Reconstructing frames or reopening source video is out of scope. Dropping unreadable files would alter the ranking and hide evidence.

### 5. Extend the existing local CLI/configuration and read-only store; add no dependency/schema changes

- **Decision**: Add a `search` argparse subcommand and a search service/storage read path under `src/bird_recognition/embed`. Reuse database URL and BioCLIP model-dir settings, with explicit CLI > process environment > `.env` > defaults. Require model-dir and database URL; require explicit run ID. Use read-only preflight and SQL. No new environment variables, package dependencies, schema migrations, output files, or model downloads are planned.
- **Rationale**: The project already provides the local-only CLI, dotenv precedence, sanitized database errors, model loader, and storage/query patterns. Search can query existing tables without altering the contract.
- **Alternatives considered**: A new DB schema, external API, auto-downloaded model, standalone service, or duplicate configuration path adds risk and conflicts with FR-011–FR-013 and the constitution.

### 6. Test deterministic correctness separately from retrieval quality

- **Decision**: Unit-test query/limit/date/species/context validation, exact ordering/ties, all-filter-before-limit behavior, unavailable image/provenance, invalid/non-finite scores, empty outcomes, and CLI JSON/exit codes with controlled substitutes. Add opt-in PostgreSQL tests for the read-only joins, context boundaries, filters, and exact result set. Use no network or private data in the normal test suite. Document an owner-reviewed, external 10-query top-five hit-rate evaluation procedure; do not claim measured quality until it is run and failures are recorded.
- **Rationale**: Existing tests use fake model/store implementations offline and separate real database integration tests. Controlled tests establish correctness but cannot demonstrate semantic relevance.
- **Alternatives considered**: Network-backed model tests or presenting fixture correctness as quality evidence violate offline/privacy and measured-quality requirements.

## Repository findings

- CLI is `src/bird_recognition/cli.py`; command parsing is in `_build_parser()` and embedding commands share `_dispatch_embed_command()`.
- Configuration and precedence are in `embed/config.py`; the existing DB/model settings are `BIRD_RECOGNITION_DATABASE_URL` and `BIRD_RECOGNITION_BIOCLIP_MODEL_DIR`.
- `PgVectorStore.preflight(read_only=True)` validates schema, pgvector dimension, and SELECT grants. Existing search needs a new SELECT-only query method; current storage helpers focus on indexing and inspection.
- `embedding_model`, `tagging_config`, `candidate_set`, `crop_snapshot`, `crop_representation`, `species_decision`, `processing_run`, and `run_item` are defined in migration `001_initial.sql`. Context selection must join a run to its one config/model and run-item decisions.
- BioCLIP text/image output is finite, normalized, float32, 512-dimensional. Existing species-tagging logit is `effective_logit_scale * dot(normalized_image, normalized_text)`; its confidence is candidate-relative, not a calibrated probability.
- Ingestion capture times are produced as ISO-8601 text, with timezone retained separately. Stored DB fields are text, so search should validate/parse values before calendar comparison rather than ask PostgreSQL to infer a timezone.
- Crop paths in provenance are relative POSIX paths; each index run item also retains its resolved input locator. Do not disclose DB URLs or credentials in diagnostics.
- Unit tests live under `tests/unit/embed`; real-DB tests are opt-in under `tests/integration/embed`. Runtime/dependency and runbook conventions are documented in `AGENTS.md`, `.env.example`, `specs/002-embed-species-tags/contracts/cli.md`, and the corresponding quickstart.


