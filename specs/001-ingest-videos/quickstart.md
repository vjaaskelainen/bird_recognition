# Quickstart: Validate Video Ingestion

This guide defines local end-to-end validation for [spec.md](spec.md). Ingestion does not contact external services. Keep all real source footage and output directories outside Git-tracked content and disjoint from one another; manually privacy-review any image before sharing.

## Prerequisites

- Python 3.14+ and `uv` installed.
- Project environment synchronized by the owner after reviewing the runtime dependency change:

  ```powershell
  uv sync
  ```

- **Compatibility gate**: PyTorch-Wildlife 1.3.0 exposes
  `MegaDetectorV6MIT` with the `MDV6-mit-yolov9-c` variant. The complete Python
  3.14 platform/runtime combination and real-model smoke test are not yet
  validated. Keep real-video operation opt-in until those checks pass and the
  owner synchronizes the dependency lockfile.

- Provision the **MIT-licensed `MDV6-mit-yolov9-c`** checkpoint (`.ckpt`) and
  its `config_v9c.yaml` separately, outside Git. By default the config must be
  beside the checkpoint; otherwise pass `--model-config` or set
  `BIRD_RECOGNITION_MEGADETECTOR_CONFIG`. Pass the checkpoint with `--model` or
  set `BIRD_RECOGNITION_MEGADETECTOR_MODEL`. Ingestion requires both local files
  and never downloads weights or configuration. The upstream files are the
  [MIT checkpoint](https://zenodo.org/records/15398270/files/MDV6-mit-yolov9-c.ckpt?download=1)
  and [YOLOv9-C config](https://zenodo.org/records/15178680/files/config_v9c.yaml?download=1);
  provision them manually and review the model's license before use.
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
  --model "D:\models\MDV6-mit-yolov9-c.ckpt" `
  --model-config "D:\models\config_v9c.yaml"
```

Use `uv run bird-recognition ingest --help` to inspect supported options,
formats, defaults, fixed model variant, and lighting rule. No PostgreSQL/Compose
service is required.

For an opt-in real-model smoke test, use only a controlled local image/video
fixture and separately provisioned files. Review labeled local examples against
absolute animal-recall and person-detection acceptance criteria; a V5 comparison
is not required. Record misses and false detections before using private batches.
Set the local paths in PowerShell and run the smoke test explicitly:

```powershell
$env:BIRD_RECOGNITION_SMOKE_MODEL = "D:\models\MDV6-mit-yolov9-c.ckpt"
$env:BIRD_RECOGNITION_SMOKE_CONFIG = "D:\models\config_v9c.yaml"
$env:BIRD_RECOGNITION_SMOKE_IMAGE = "D:\validation\controlled-image.jpg"
uv run pytest tests/ingest/test_detection_smoke.py -q
```

The test skips when these paths are not set; it is not part of normal offline
test execution.

## Expected result and review

- Exit `0`: all discovered sources completed, or no supported videos were found (explicit no-input message).
- Exit `1`: one or more video/frame processing failures; safe sources may still have completed. Review reported source/frame and reason.
- Exit `2`: preflight rejected the invocation before processing output.
- The summary reports processed/skipped/failed sources; sampled, person-excluded, no-animal, retained, and failed frames; and number of crops. The four frame outcomes sum to sampled frames; crop count may be greater than retained-frame count.
- The destination contains a SQLite manifest and retained animal crops. No excluded or failed full-frame still is retained. Re-running unchanged successful input with unchanged effective settings reports it skipped and adds no image/record duplicates.

Inspect the persistent schema and invariants in [data-model.md](data-model.md), and the command/exit contract in [contracts/cli.md](contracts/cli.md). Before sharing any crop, manually review it for people or other sensitive content; model filtering is not a guarantee of anonymity.
