# Quickstart: Validate Video Ingestion

This guide defines local end-to-end validation for [spec.md](spec.md). Ingestion does not contact external services. Keep all real source footage and output directories outside Git-tracked content and disjoint from one another; manually privacy-review any image before sharing.

## Prerequisites

- Python 3.14+ and `uv` installed.
- Project environment synchronized after runtime dependencies are approved and pinned:

  ```powershell
  uv sync
  ```

- A local copy of the supported pretrained MegaDetector model and its configuration/runtime, provisioned separately. Set the documented model setting or pass `--model`; ingestion must not download it.
- A temporary input directory containing local videos in documented supported formats. Tests use generated miniature fixtures and fake detections rather than private footage or a real model.

## Validate the test workflow

Run focused tests, then the full offline test suite:

```powershell
uv run pytest tests/ingest
uv run pytest
```

The fixtures/fake detector should validate:

- first-frame and interval sampling, original frame ordinal, elapsed PTS time, variable frame timing, and short clips;
- qualifying animal crops, vehicles/empty frames, inclusive thresholds, and whole-frame person exclusion including mixed scenes;
- box clipping, exclusive right/bottom coordinates, invalid boxes, and frame dimensions;
- capture-time unknowns/timezone retention and verified day/night/ambiguous lighting outcomes;
- per-frame all-or-none crop publication, injected failures, totals reconciliation, rerun idempotence, changed settings/content, and same-basename source separation.

Tests must not download weights, require credentials, or call external services.

## Run a local batch

Choose a dedicated destination that is not under the repository or input tree, then:

```powershell
uv run bird-recognition ingest `
  --input "D:\trail-camera\videos" `
  --output "D:\trail-camera\ingested" `
  --interval 1.0 `
  --animal-threshold 0.2 `
  --person-threshold 0.2 `
  --model "D:\models\megadetector-model-file"
```

Use `uv run bird-recognition ingest --help` to inspect supported options, formats, defaults, and lighting rule. No PostgreSQL/Compose service is required.

## Expected result and review

- Exit `0`: all discovered sources completed, or no supported videos were found (explicit no-input message).
- Exit `1`: one or more video/frame processing failures; safe sources may still have completed. Review reported source/frame and reason.
- Exit `2`: preflight rejected the invocation before processing output.
- The summary reports processed/skipped/failed sources; sampled, person-excluded, no-animal, retained, and failed frames; and number of crops. The four frame outcomes sum to sampled frames; crop count may be greater than retained-frame count.
- The destination contains a SQLite manifest and retained animal crops. No excluded or failed full-frame still is retained. Re-running unchanged successful input with unchanged effective settings reports it skipped and adds no image/record duplicates.

Inspect the persistent schema and invariants in [data-model.md](data-model.md), and the command/exit contract in [contracts/cli.md](contracts/cli.md). Before sharing any crop, manually review it for people or other sensitive content; model filtering is not a guarantee of anonymity.
