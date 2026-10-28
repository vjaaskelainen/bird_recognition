# Implementation Plan: Ingest Trail-Camera Videos

**Branch**: `001-ingest-videos` | **Date**: 2026-10-13 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-ingest-videos/spec.md`

## Summary

Provide a local CLI workflow that recursively samples trail-camera videos, screens each complete frame with pretrained MegaDetector, excludes frames with people, and durably publishes one metadata-linked crop per qualifying animal. Use PyAV presentation timestamps for variable-frame-rate-aware sampling, a local SQLite manifest plus filesystem image storage for portable atomic/recoverable publication, and an injectable detector boundary so fixture tests need no model download or network service. Original videos remain untouched; intermediate full frames remain in memory only.

## Technical Context

**Language/Version**: Python >=3.14 (project requirement)

**Primary Dependencies**: PyAV for decoded frames and presentation timestamps; Pillow for crop encoding and image evidence; MegaDetector inference implementation and compatible pretrained PyTorch runtime/model file; stdlib `argparse`, `sqlite3`, `hashlib`, and `pathlib`. Confirm package/version and Python 3.14 wheel compatibility before dependency pinning.

**Storage**: Local SQLite manifest and local crop files under the explicitly selected output directory; PostgreSQL is not required for this feature. Input footage and output must be outside version-controlled data.

**Testing**: pytest with tiny generated video fixtures and a deterministic fake detector; no live model, credentials, or network required. An opt-in smoke test may validate configured MegaDetector/model compatibility.

**Target Platform**: Local Python 3.14+ on Windows, Linux, or macOS; CLI paths and model availability are user controlled.

**Project Type**: Single Python CLI/package.

**Performance Goals**: No throughput target is claimed. Decode each input once, retain only sampled frames in memory, and avoid keeping full videos or rejected frames in output storage.

**Constraints**: Full-frame person screening precedes crop publication; failed detection cannot imply safety. Use actual presentation timing where available, never invent capture timestamps. Model weights are local/user-provided and tests remain offline. Filesystem and SQLite publication must recover after interruption.

**Scale/Scope**: One owner, one local batch at a time, recursive discovery, per-video/frame isolation, persistent crops/provenance; no indexing, species tagging, tracking, API, or UI.

## Constitution Check

| Gate | Result | Evidence |
|---|---|---|
| CLI-first, smallest complete local workflow | PASS | One local command handles discovery, inference, crop persistence, and review summary. |
| Privacy-preserving data handling | PASS | Full frames screened before cropping; person or detector failure blocks publication; private data stays outside Git; no external publishing. |
| Pretrained models only | PASS | MegaDetector is used as an existing pretrained detector; no training or fine-tuning. |
| Offline testability | PASS | Detector is injected behind an interface; fake detections and local fixtures require no credentials/network. |
| Evidence/provenance readiness | PASS | Crop records link source identity, timing, lighting, box, confidence, run, and settings for later indexing. |
| Scope and constitution compatibility | PASS | No authentication, cloud service, LLM, indexing, or UI is introduced. |

## Project Structure

### Documentation (this feature)

```text
specs/001-ingest-videos/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cli.md
└── tasks.md                 # generated later by /speckit-tasks
```

### Source Code (repository root)

```text
src/
└── bird_recognition/
    ├── cli.py                 # command parsing and exit/status reporting
    └── ingest/
        ├── pipeline.py        # per-source and per-frame orchestration
        ├── video.py           # decode, timing, and capture metadata
        ├── detection.py       # detector protocol and MegaDetector adapter
        ├── lighting.py        # conservative image-evidence classifier
        ├── crops.py           # box validation and staged crop publication
        ├── manifest.py        # SQLite schema, records, fingerprints, recovery
        └── models.py          # typed internal records and settings

tests/
├── test_cli.py
└── ingest/
    ├── test_sampling.py
    ├── test_filtering.py
    ├── test_metadata.py
    ├── test_storage.py
    └── fixtures/              # tiny synthetic clips only; no private footage
```

**Structure Decision**: Keep the feature within the existing `src/bird_recognition` package and `tests` directory. Add an `ingest` subpackage with explicit boundaries for video timing, detector integration, privacy/filter logic, file/SQLite publication, and CLI reporting; do not add a separate service or database container.

## Design Decisions

- **Video timeline**: Decode with PyAV and schedule targets at elapsed times `0, interval, 2*interval, ...`; process the first frame at/after the first target, then advance to the first target strictly later than that frame's elapsed time so sparse timestamps cannot select the same frame repeatedly. Retain the zero-based decoded frame ordinal and PTS-derived elapsed seconds. Process the first readable frame for clips shorter than the interval. If sampled frames lack usable timing, fail those frame operations rather than inventing VFR timing from nominal FPS.
- **Detector contract**: Evaluate each sampled full frame once. The adapter translates MegaDetector category IDs into animal/person/other categories; pipeline thresholds are inclusive and separate. Model loading or incomplete inference fails closed. Record model identifier/version and local model-file SHA-256 in run settings; never fetch weights implicitly during ingestion.
- **Image and manifest persistence**: Keep SQLite manifest and crops within the chosen output root. Use content/settings fingerprints for rerun detection; derive source IDs from normalized absolute source path plus content digest (not basename). Stage all crops for a frame in a temporary directory, finish encoding, atomically rename the directory, then commit all frame crop records in one SQLite transaction. On errors/interruption, discard staged content and reconcile orphaned final directories on next invocation. Crop IDs derive from source fingerprint, settings fingerprint, frame index, and detection identity.
- **Timing metadata**: Read only recognized video capture-start metadata. Preserve timezone-aware values; retain unambiguous local wall time with timezone explicitly unknown when present; absent, malformed, or conflicting metadata becomes explicit unknown. Never consult filesystem modification time or ingestion time.
- **Lighting evidence**: Use a deterministic, conservative pixel-evidence classifier, independent of clock time: day only with clear daylight-color evidence, night only with clear infrared/low-light evidence, otherwise unknown. Record classifier name/version and thresholds with run settings. Tests exercise verified color-day, IR-night, and ambiguous fixture images; thresholds remain centralized and limitations explicit.
- **Batch outcome/reporting**: Count every attempted sample exactly once as person-excluded, no-animal, retained, or failed; count stored crops separately. Continue after isolated source/frame failures. CLI exits 0 for complete success or empty input, 1 for partial/total processing failure, and 2 for preflight validation errors.
- **Dependency decision**: Use PyAV rather than OpenCV for presentation timestamps and VFR behavior, Pillow for pixel crops and image fixtures, and stdlib SQLite rather than requiring the existing PostgreSQL service because ingestion is local/single-owner and should run without service setup. Implementation must first validate that the chosen official MegaDetector inference API, PyTorch runtime, model format, and PyAV/Pillow releases install and run on supported Python 3.14 platforms; then pin exact compatible ranges/revisions and document model provisioning. Do not silently substitute a different detector or claim unverified compatibility. Follow the current [AGENTS.md](../../AGENTS.md) dependency approval and synchronization policy; uv generates the lockfile.

## Post-Design Constitution Check

The design remains within the approved gates: private local artifacts and fail-closed person screening are retained; model inference is pretrained-only; offline fixtures cover behavior; and SQLite keeps the requested workflow local and service-free. No unexplained gate violations.

## Complexity Tracking

No constitution violations identified; no added complexity requires justification.
