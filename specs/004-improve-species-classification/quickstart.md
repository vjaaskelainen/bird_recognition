# Quickstart: Validate Wildlife Species Classification Improvements

**Status**: Validation guide for implemented classification interfaces. Existing crop review and CSV conversion scripts support shared labels/case identity; no replacement review interface is introduced. These procedures are not a record of completed private-data validation or measured biological quality.

Run from `C:\code\bird_recognition` in Windows PowerShell. Use the existing `.venv`; if it is absent, stop and ask the developer. Do not activate the environment. This guide does not authorize database resets/services, private model or footage access, or use of private labels/reports; obtain explicit approval for those separate actions.

Keep footage, ingestion outputs, crops, model assets, taxonomy/review CSVs, labels, references, and generated reports outside Git. Classification runs locally; no assets are downloaded and no data is uploaded. See the [CLI contract](contracts/cli.md), [data model](data-model.md), and [research decisions](research.md) for exact versioning, validation, and formulas.

## 1. Establish blind labels from the existing workflow

1. Choose a representative baseline crop sample spanning day, night, and unknown lighting, including out-of-list and difficult examples. Use source-video IDs not used to tune candidates/prompts/crop settings. Use the existing `inspect --json` output and `tools/review_csv.py create` to create a shuffled, lighting-stratified sample CSV. Do not include model predictions in the review CSV.
2. Use the existing local browser tool to label images one at a time. Select a stable reviewed taxon ID/common name from the owner-maintained review vocabulary, optionally record a known coarse bird/mammal category, or explicitly mark not-in-list, unidentifiable, or unusable. Lighting is shown from source provenance and is not a review label. Preserve the existing autosave workflow.
3. Convert the completed CSV with `tools/review_csv.py to-labels` to the shared label-set schema. The converter retains labels independent of the baseline run/candidate list and emits each `case_id` plus the actual reviewed crop ID. Keep the input CSV and exported labels external.

Illustrative PowerShell workflow (paths must be adapted to private external locations):

```powershell
$runId = '<baseline-run-id>'
$private = 'D:\bird-eval'
$ingested = 'D:\trail-camera\ingested'
$holdoutSourceIds = @('<held-out-source-id-1>', '<held-out-source-id-2>')
New-Item -ItemType Directory -Force $private, "$private\reports" | Out-Null
$sourceArgs = @()
foreach ($sourceId in $holdoutSourceIds) { $sourceArgs += @('--source-id', $sourceId) }

$inspectJson = .\.venv\Scripts\uv.exe run bird-recognition inspect --run-id $runId --json
[System.IO.File]::WriteAllText(
  "$private\baseline-inspect.json",
  ($inspectJson -join [Environment]::NewLine),
  [System.Text.UTF8Encoding]::new($false)
)
.\.venv\Scripts\uv.exe run python tools/review_csv.py create `
  --inspect "$private\baseline-inspect.json" `
  --crop-root $ingested `
  @sourceArgs `
  --output "$private\blind-review.csv" `
  --per-lighting 40 --seed 23
.\.venv\Scripts\uv.exe run python tools/review_crops.py `
  --csv "$private\blind-review.csv" `
  --species "$private\review-taxonomy.json"
.\.venv\Scripts\uv.exe run python tools/review_csv.py to-labels `
  --csv "$private\blind-review.csv" `
  --label-role held_out_evaluation `
  --split-mode source_video `
  --output "$private\reviewed-labels.json"
```

Expected: shuffled blind review is completed before inspecting predictions; each row retains a stable crop/event identity, and label conversion does not bind the cohort to one classification candidate list. Keep all source-video/day split keys disjoint from any tuning label set. The review CSV's legacy single-run export remains usable by historical evaluation. Do not treat human review of an expanded crop as proof that a different view has identical visibility; each setup's observed input quality remains reportable.

## 2. Compare baseline and candidate/prompt revisions

Evaluate the baseline run created in section 1 against the shared held-out labels. Then run a second setup with the owner-reviewed local species vocabulary plus typed broad bird/mammal candidates and versioned common-name/taxonomic descriptions. Keep model and all other settings unchanged for this comparison. Compare both explicit run IDs against the same shared labels:

```powershell
.\.venv\Scripts\uv.exe run bird-recognition evaluate-species `
  --run-id '<baseline-run-id>' `
  --labels "$private\reviewed-labels.json" `
  --output "$private\reports\baseline-quality.json" --json
.\.venv\Scripts\uv.exe run bird-recognition index `
  --manifest "$ingested\manifest.sqlite3" `
  --species-list 'D:\bird-config\species-baseline.json' --json
.\.venv\Scripts\uv.exe run bird-recognition index `
  --manifest "$ingested\manifest.sqlite3" `
  --species-list 'D:\bird-config\species-local-v2.json' --json
.\.venv\Scripts\uv.exe run bird-recognition compare-species `
  --run-id '<baseline-run-id>' --run-id '<expanded-vocabulary-run-id>' `
  --labels "$private\reviewed-labels.json" `
  --output "$private\reports\vocabulary-comparison.json" --json
```

Expected: report identifies candidate and prompt versions, displays day/night/unknown sample counts, separates exact species success from broad-category outcomes, and exposes paired changes in correct assignments, unassigned decisions, and coverage. An absent or ambiguous `case_id`, failed input, or candidate-ineligible crop is reported rather than silently dropped. Less than ten completed reviewed day or night examples is insufficient for publication-ready sample claims. A broad category never counts as an exact species match.

## 3. Compare crop preparation without overwriting history

Re-ingest the same approved video selection with the default `context-v1` crop policy into the same external ingestion output. The changed effective settings must create new crop files/IDs/manifest rows and preserve old results. Index the new manifest using the same model and candidate/prompt setup, and explicitly choose the fit/pad image view; then compare it against the original using the `case_id` mapping.

```powershell
.\.venv\Scripts\uv.exe run bird-recognition ingest `
  --input 'D:\trail-camera\videos' `
  --output $ingested `
  --model 'D:\models\MDV6-mit-yolov9-c.ckpt' `
  --model-config 'D:\models\config_v9s.yaml' `
  --crop-policy context-v1
.\.venv\Scripts\uv.exe run bird-recognition index `
  --manifest "$ingested\manifest.sqlite3" `
  --species-list 'D:\bird-config\species-local-v2.json' `
  --input-view fit-pad-v1 `
  --minimum-crop-width 32 --minimum-crop-height 32 --json
```

Expected geometry checks: a crop near a frame edge remains entirely inside frame dimensions and includes all available animal pixels; an elongated rectangular crop remains rectangular and the model input fit/pad transform preserves the whole image; undersized crops are recorded as low quality and not treated as reliable tags. Historical crop hashes and decisions remain inspectable and unchanged. The comparison identifies each setup-specific crop ID and reports ambiguous/unpaired cases.

Use synthetic generated image tests for these geometry and resize/pad checks. Do not access private footage or modify an existing database/output tree without separate explicit approval.

## 4. Validate thresholds, reference fallback, visit grouping, and benchmark reporting

- **Margin**: Use controlled score maps for a unique clear lead, narrow lead above threshold, below-threshold lead, and exact tie. Configure `index --minimum-margin <score-gap>` independently of `--threshold`; below-threshold, below-margin, and tied decisions remain unassigned with reason and competing scores inspectable. Confirm threshold-only/margin-only changes preserve compatible vectors and old decisions.
- **Reference mode**: Create generated reference/evaluation fixtures with distinct source IDs and days. The external version-1 reference manifest records exact model/input-view fingerprints, reviewed species IDs, image SHA-256 values, source/day provenance, and local image locators. Enable it explicitly with `index --reference-set <manifest> --reference-min-similarity 0.8 --reference-min-agreement 0.75`; choose `--reference-split-mode recording_day` only when source-video identity cannot be verified and every day is known. Confirm overlap is rejected before encoding; an adequate same-label match may suggest a species; weak or inconsistent references use and identify `zero_shot_fallback`. Inspect the saved run to verify reference-set and per-decision provenance. Confirm no network/live service is needed.
- **Visit mode**: Provide an external version-1 group file, explicitly marking each owner-reviewed association as confident:

  ```json
  {
    "schema_version": 1,
    "groups": [
      {
        "visit_id": "visit-1",
        "source_video_id": "source-video-1",
        "crop_ids": ["crop-1", "crop-2"],
        "association_confident": true
      }
    ]
  }
  ```

  Run `aggregate-visits --run-id <run-id> --groups <external-groups.json> --output <external-report.json> --json`. Confirm arithmetic-mean logits are rechecked using threshold/margin, every contributor crop/decision is linked, and per-crop decisions are unchanged. Reject cross-video or uncertain groups; same-video membership alone is insufficient.
- **Benchmark**: Select a held-out shared label cohort and an explicitly selected supported local BioCLIP asset directory. Run `benchmark-species --run-id <run-id> --labels <external-labels.json> --model-dir <local-assets> --max-crops 40 --output <external-report.json> --json`. Confirm the deterministic sample cap, sample/setup identity, quality measures, and elapsed time are reported, and that selected/default configuration remains unchanged. No unsupported model is fetched or silently substituted.

These are controlled correctness checks, not biological-quality evidence. Quality claims require a reviewed real cohort held out by source video/day from setup selection/tuning and must separately report day and night. Held-out evaluation labels must be marked `held_out_evaluation`; tuning labels cannot support publication-quality claims.

## 5. Validate persistence and privacy boundaries

Run unit tests with the standard project command:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Expected: no model download, network access, private data, or database requirement for controlled unit coverage. Tests include candidate validation/prompt fingerprints, label comparison/group denominators, broad category accounting, crop geometry/quality, score margin, reference split/fallback, visit provenance, output privacy, and historical setup compatibility.

Against an explicitly approved disposable local database only, run integration tests using `BIRD_RECOGNITION_TEST_DATABASE_URL` as documented in `AGENTS.md`. Verify migrations upgrade an existing schema without deleting old decisions, database constraints match pure validation, and historical records remain inspectable. A skipped integration suite is not database evidence.

Write all comparison/benchmark/visit reports to an existing external folder. Empty metric denominators are unavailable/null; publication readiness is only a minimum-sample marker, never an accuracy guarantee. Document measured real-label results and observed failure cases separately from offline correctness.








