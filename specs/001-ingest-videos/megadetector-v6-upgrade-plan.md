# MegaDetector V6 Upgrade Plan

**Status**: Implementation in progress; real-model smoke pending  
**Reviewed**: 2026-10-16  
**Scope**: Replace the ingestion adapter's legacy MegaDetector integration with the current V6 integration while preserving the local, privacy-first video workflow.

## Objective

Upgrade detector inference to MegaDetector V6 without changing the ingestion feature's user-visible filtering or storage guarantees. Keep inference local, require weights to be provisioned separately, and retain an injectable detector interface so the normal test suite does not need model downloads or network access.

This is an integration upgrade, not a species-classification feature. MegaDetector still reports animal/person/vehicle detections; it does not identify species.

## Why an upgrade is needed

- [`pyproject.toml`](../../pyproject.toml) pins `megadetector==10.0.27`. This is a Python package version, not the model's generation.
- [`detection.py`](../../src/bird_recognition/ingest/detection.py) imports `megadetector.detection.run_detector`, loads a file through `load_detector`, and calls `generate_detections_one_image`. This is the older inference API.
- The [current MegaDetector guide](https://microsoft.github.io/MegaDetector/) documents V6 through PyTorch-Wildlife. The selected MIT model is exposed as `PytorchWildlife.models.detection.MegaDetectorV6MIT`; its default loader downloads the YAML config and model weights unless the integration explicitly bypasses those paths.
- The current adapter expects a legacy list of dictionaries with category IDs and normalized `xywh` boxes. The upstream V6 implementation returns `supervision.Detections` with class IDs and pixel `xyxy` boxes, plus normalized coordinates. The adapter therefore needs an explicit output conversion, not just a dependency rename.
- The feature [quickstart](quickstart.md) still blocks real-video use on the compatibility verification task. The dependency pin alone is not evidence that the model/API/runtime combination was validated.

## Invariants to preserve

1. Run inference on each complete sampled frame before producing any crop.
2. Exclude the entire frame when a qualifying person detection is present, even if the frame also contains animals.
3. Keep animal and person thresholds independently configurable and inclusive. Request detections down to zero confidence from the model so the application, not the backend default, applies those thresholds.
4. Treat model-load and inference errors as failures; never treat missing or malformed detections as a safe/empty frame.
5. Do not download weights during ingestion. Keep footage, weights, and output artifacts outside Git.
6. Keep normal tests offline and injected/fake-detector based.
7. Preserve existing records and make results from a changed model distinguishable through the effective-settings fingerprint.

## Selected decisions and remaining compatibility gates

The model/variant decision is made; the following runtime and data-quality gates remain before real-video use:

- **V6 variant and license (selected)**: Use `MDV6-mit-yolov9-c`, the MIT-licensed compact model. The official model zoo lists 9.7M parameters and 74.8% animal recall on its benchmark. PyTorch-Wildlife 1.3.0 exposes this exact choice through `MegaDetectorV6MIT`. Revisit it if controlled local evaluation shows it misses acceptance criteria.
- **Supported platforms and runtime**: The Python 3.14 Windows dependency resolver dry run succeeded; installation and inference still need demonstration. Do not claim support for other platforms until those are tested.
- **Offline weight loading**: The adapter supplies explicit local checkpoint/config paths and bypasses the package's download-backed config/weight loader. Verify missing/invalid file and no-network behavior in tests and smoke validation.
- **Input image representation**: PyTorch-Wildlife's MIT API accepts RGB HWC arrays; the adapter converts decoded PIL frames to contiguous uint8 RGB arrays and unit tests verify dimensions and pixel values.
- **Model quality**: On a small, manually reviewed and labeled sample, measure animal recall and person detection against pre-set absolute acceptance criteria. A V5 comparison is not required. Do not claim local accuracy from published model-zoo metrics.

If runtime or smoke validation fails, block real-video use and adapt or revert the integration. Never permit an implicit download or weaken person-first filtering to make a run succeed.

## Gate evaluation (2026-10-16)

Implementation is in progress; these source and resolver checks are not a substitute for a real installation and inference smoke test:

- PyPI's PyTorch-Wildlife 1.3.0 wheel contains `MegaDetectorV6MIT` and the `MDV6-mit-yolov9-c` choice. Its MIT loader normally fetches `config_v9c.yaml`, fetches weights from its configured URL/cache, and reloads model state from single-image inference. The adapter overrides those paths to load the explicit local config/checkpoint and reuse the model within a run.
- A resolver dry run completed for the selected package on Python 3.14 Windows. No dependency installation or inference has yet been performed, and Linux/macOS support is not established.
- No model checkpoint, config, or labeled sample is present in the repository workspace. The opt-in real-model smoke test and local quality acceptance evaluation remain pending owner-provisioned local artifacts.

## Proposed implementation

### 1. Pin a tested V6 runtime

- Replace the legacy `megadetector` dependency with the official PyTorch-Wildlife package and the exact compatible dependency bounds established by the compatibility gate.
- Keep dependency changes limited to `pyproject.toml`. Per [`AGENTS.md`](../../AGENTS.md), do not edit `uv.lock` or synchronize dependencies; ask the repository owner to run `uv sync` after approving the manifest change.
- Record the exact package release, model variant, model license, supported Python/platform combination, and source used to verify the API.

### 2. Update the MegaDetector adapter

- Keep the `Detector` protocol and pipeline call site stable.
- Load `MegaDetectorV6MIT` once per ingestion run, using the explicit local `.ckpt`, `config_v9c.yaml`, and `MDV6-mit-yolov9-c` variant. Fail preflight if either file is absent or unreadable; never initialize a download-backed default implicitly.
- Pass each complete decoded frame in the verified RGB representation. Configure model inference to return detections regardless of the app's animal/person thresholds, then apply the existing thresholds in the pipeline.
- Normalize upstream output into the existing `Detection` type:
  - V6 animal, person, and vehicle classes map to the app's `ANIMAL`, `PERSON`, and `OTHER` categories.
  - Convert V6 pixel `xyxy` coordinates, or its documented normalized equivalent, to the normalized `xyxy` coordinates expected by crop handling.
  - Preserve confidence and deterministic per-frame detection IDs.
  - Reject unexpected class IDs, malformed boxes, non-finite values, and incomplete results through the existing fail-closed error path.
- Keep any class-ID mapping and coordinate conversion tied to the tested API/version; do not assume legacy numeric category IDs have the same meaning in V6.

### 3. Record model identity in settings and CLI

- Continue recording digests of the local weight and config files.
- Include the V6 implementation/package version, exact model variant, and both local-file digests in effective run settings and CLI help/output.
- Retain `--model` and add `--model-config`; keep the variant fixed and explicit in settings/help as `MDV6-mit-yolov9-c`.
- Ensure the settings fingerprint changes when the implementation version, model variant, weight digest, or other inference-affecting setting changes. Existing V5-era results remain intact; a V6 run must not overwrite or be incorrectly skipped as an unchanged V5 run.

### 4. Tests and measured validation

- Rewrite adapter unit tests around the pinned V6 output type, while retaining fake weights/injected inference so tests never load a real model.
- Cover at least:
  - V6 class mapping for animal/person/vehicle and unknown classes;
  - normalized and pixel-coordinate conversion, including image boundaries and invalid boxes;
  - confidence `0.0` passed to inference and inclusive application thresholds;
  - malformed, empty, or failed inference results becoming errors rather than safe frames;
  - explicit local-weight preflight and no implicit weight download;
  - persisted settings/fingerprint changes when package version, variant, or weight digest changes.
- Run existing ingestion pipeline/storage tests to verify whole-frame person exclusion, crop generation, idempotence, and failure recovery remain unchanged.
- With separately provisioned V6 weights/config, run an opt-in smoke test on a controlled local image/video fixture. Measure against reviewed labels and the absolute acceptance criteria; a V5 comparison is not required. Never add private footage or weights to Git.

### 5. Update user documentation

- Update the ingestion [quickstart](quickstart.md) and root [README](../../README.md) to identify the selected V6 variant, exact package/runtime prerequisites, where to provision the local `.ckpt` and YAML config, how to pass their paths, and the no-download guarantee.
- Update the [CLI contract](contracts/cli.md) and [data model](data-model.md) if option semantics or recorded model identity change.
- Remove the obsolete compatibility-gate wording only after the Python/platform install, offline model load, and controlled end-to-end smoke test have passed.

## Suggested execution order and completion criteria

1. Resolve variant/license, package API, Python 3.14/platform compatibility, and offline weight-loading gates.
2. Update `pyproject.toml`; have the owner synchronize the environment; record the tested package and variant.
3. Implement the V6 adapter and model identity/settings changes.
4. Update and run targeted adapter/pipeline/storage tests, then the repository's Ruff and pytest checks.
5. Run the opt-in controlled V6 smoke and labeled-sample acceptance evaluation; report measured results without overstating accuracy.
6. Update quickstart, CLI contract, and README; remove the real-run gate only when all required checks are documented as passing.

The upgrade is complete only when the selected V6 model loads from explicit local weights without an ingestion-time download, produces correctly normalized detections, preserves person-first filtering and output provenance, passes offline tests, and has a documented controlled smoke-test result.

## References

- [MegaDetector V6 user guide](https://microsoft.github.io/MegaDetector/)
- [MegaDetector installation](https://microsoft.github.io/MegaDetector/installation/)
- [MegaDetector model zoo and variant licenses](https://microsoft.github.io/MegaDetector/model_zoo/)
- [PyTorch-Wildlife MegaDetectorV6 implementation](https://github.com/microsoft/Biodiversity/blob/main/PytorchWildlife/models/detection/ultralytics_based/megadetectorv6.py)
- [PyTorch-Wildlife inference/output implementation](https://github.com/microsoft/Biodiversity/blob/main/PytorchWildlife/models/detection/ultralytics_based/yolov8_base.py)
- [PyTorch-Wildlife MIT V6 implementation](https://github.com/microsoft/Biodiversity/blob/main/PytorchWildlife/models/detection/yolo_mit/megadetectorv6_mit.py)
- [PyTorch-Wildlife MIT config, model loading, and inference](https://github.com/microsoft/Biodiversity/blob/main/PytorchWildlife/models/detection/yolo_mit/yolo_mit_base.py)
