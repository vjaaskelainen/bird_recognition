# Research: Ingest Trail-Camera Videos

**Feature**: [spec.md](spec.md)  
**Research date**: 2026-10-13

## Decisions

### Frame decoding and sampling

- **Decision**: Use PyAV/FFmpeg decoding and each decoded frame's presentation timestamp (PTS) and time base. Schedule elapsed-time targets from zero at the configured interval and select the first decoded frame at or after each target; retain the decoded frame ordinal as the zero-based frame number and calculate elapsed seconds from PTS relative to the stream's first valid presentation time.
- **Rationale**: PTS handles variable-frame-rate media without treating nominal average FPS as the actual timeline. Decoding once is simpler and more memory-efficient than seeking independently to each target. The first readable frame is still considered for a short clip.
- **Alternatives considered**: OpenCV `VideoCapture` with `frame_index / FPS` was rejected because the reported FPS is nominal and cannot reliably represent variable rates. Extraction via an external `ffmpeg` subprocess was rejected for core operation because it complicates per-frame failure handling, portability, and tests.
- **Failure policy**: A frame with corrupt pixel data, missing/non-monotonic PTS, or decode error is a failed sampled frame and cannot pass privacy filtering. Frames are not labeled empty or safe from missing results.

### MegaDetector integration

- **Decision**: Keep detection behind a typed detector protocol and implement a thin adapter around the official MegaDetector inference implementation. Require an explicit, already-present model file/configuration and local runtime; never download weights during an ingest command. Initialize once per run and run complete sampled images through it. Map detector outputs into `animal`, `person`, and `other`; use independently configured inclusive confidence thresholds in the pipeline.
- **Rationale**: This retains MegaDetector as the pretrained detector while keeping filtering deterministic and fixture-testable. Injected fake detections test category mapping-independent workflow without expensive model initialization or network access.
- **Alternatives considered**: Training/fine-tuning is disallowed by the project constitution. Requiring a hosted inference service violates the local/offline privacy boundary. Tightly coupling policy to vendor output categories was rejected in favor of an adapter.
- **Compatibility constraint**: Pin a tested official inference revision and compatible PyTorch/runtime only after confirming Python 3.14 platform wheels. Keep the adapter narrow so a packaging/API compatibility issue can be resolved without changing the persisted data contract. Record detector name, implementation version/revision, model identifier, and model-file SHA-256 in effective run settings.

### Persistence, stable IDs, and interruption handling

- **Decision**: Persist metadata in a SQLite database under the output root and images in a private crop directory under that root. A source fingerprint includes normalized absolute path and full content digest; a settings fingerprint includes every effective sampling, threshold, model, and lighting setting. If both match a completed source record in the same destination, skip it. Changed content/settings produces a new result identity and never overwrites old results. Use a destination lock to prevent concurrent writers.
- **Rationale**: SQLite and ordinary files work without requiring the project's optional PostgreSQL Compose service, match a single-owner local workflow, and can later be read for indexing. Full content hashing catches same-size or same-timestamp changes and basename collisions.
- **Atomic publication protocol**: Build all crop files for one frame in a temporary directory on the same filesystem; complete image encoding and metadata validation before renaming that directory to its deterministic final location. Then commit all crop rows and the retained-frame outcome in one SQLite transaction. If any step fails, remove staged/final files when possible and leave no crop records. On startup, remove stale staging directories and reconcile final crop directories that lack committed manifest records. SQLite transactions prevent partial frame records. Retain the completed source/run status only after processing and summary persistence finish.
- **Alternatives considered**: PostgreSQL was rejected for this feature because it adds a required server and does not simplify atomic local image-file publication. JSON-per-crop was rejected because transactional batch updates and safe idempotence are harder. A basename-only output layout was rejected because distinct source paths collide.

### Capture time provenance

- **Decision**: Parse only documented video/container metadata fields that explicitly represent recording creation/capture time. Preserve timestamps with an explicit UTC offset. A recognized local date-time without zone may be retained as local time with `timezone=unknown`; missing, conflicting, malformed, or ambiguous values become `capture_time=unknown`. Never use file modification time, filename guesses, or ingest time.
- **Rationale**: This gives reproducible metadata and meets the spec's explicit non-fabrication rule. Elapsed PTS-derived seconds remains independently available.
- **Alternatives considered**: File metadata timestamps and filename patterns were rejected because they are not guaranteed to describe camera capture time. Treating naive timestamps as UTC was rejected because it invents timezone information.

### Day/night classification

- **Decision**: Implement a versioned, deterministic image-evidence heuristic independent of wall-clock time. High-confidence daylight-color evidence yields `day`; clear infrared/low-light monochrome evidence yields `night`; weak or conflicting evidence yields `unknown`. A conservative initial rule may use chroma/saturation plus luminance/contrast statistics and must keep thresholds centralized and captured in run settings.
- **Rationale**: The project has no labeled general-purpose lighting model and this feature must remain small/offline. Explicit unknown is preferable to guessing. Verifiable representative examples are acceptance fixtures, not a claim that a heuristic works for every camera.
- **Alternatives considered**: Classifying by capture hour was rejected because night-vision is unrelated to local clock time. A newly trained classifier is outside scope and constitution constraints. A pretrained visual classifier adds model, network, and quality risks without a spec requirement.

### CLI, validation, and outcomes

- **Decision**: Expose an `ingest` subcommand through an installed `bird-recognition` console script. Validate paths, output/input disjointness and that output is not Git-tracked, positive finite interval, thresholds in `[0,1]`, and local model readiness before creating/publishing output. Discover supported videos recursively and deterministically; initial case-insensitive suffix allowlist: `.mp4`, `.mov`, `.m4v`, `.mkv`, `.avi`, `.mpeg`, `.mpg`. An empty directory produces a clear no-input summary and no fabricated failures. Report per-source status, run settings, mutually exclusive sampled-frame outcomes, and crop count. Exit 0 on complete success or no input; 1 on partial/total processing failure; 2 on invalid invocation/preflight.
- **Rationale**: The project is CLI-first and users need actionable review of partial batches. Preflight checks prevent invalid settings from producing output. Extension allowlist and model configuration must be documented in CLI help.
- **Alternatives considered**: A UI, web service, and implicit external publishing are out of scope. `argparse` avoids a dependency until command complexity justifies one.

## Dependencies and test approach

- Use PyAV for decode/timestamps and Pillow for RGB conversion, pixel crops, and fixture image creation. Use Python standard library SQLite and filesystem APIs for persistence and atomic rename/transactions.
- Use pytest with tiny generated local video clips plus in-memory fake detector results. Include controlled animal/person/vehicle/empty/mixed scenes, equal/below thresholds, bad boxes, short/VFR clips, missing time, lighting examples, storage faults, and rerun/collision cases.
- **Version resolution**: PyAV and MegaDetector/PyTorch compatibility with Python 3.14 must be tested before adding pins. At the research date, the project declared Python 3.14 and had no runtime dependencies, CLI, models, or persistence layer; this is historical context, not the current implementation state. Do not promise platform support for a dependency combination until CI/local install verifies it. Follow the current [AGENTS.md](../../AGENTS.md) dependency approval and synchronization policy; uv generates the lockfile rather than manual edits.
