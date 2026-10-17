# CLI Contract: Video Ingestion

This contract defines the user-facing local command for feature 001. The proposed installed entry point is `bird-recognition`; the command is `ingest`.

## Invocation

```text
bird-recognition ingest --input DIR --output DIR [OPTIONS]
```

Run from a synced project environment as `uv run bird-recognition ingest ...`.

### Required arguments

- `--input DIR`: existing directory to scan recursively for supported video formats.
- `--output DIR`: persistent destination for the SQLite manifest and animal crops. Must be outside Git-tracked content (including version-controlled data) and disjoint from the input tree.

### Options

| Option | Default | Contract |
|---|---:|---|
| `--interval SECONDS` | `1.0` | Positive finite target sampling period. Targets start at elapsed zero. |
| `--animal-threshold VALUE` | `0.2` | Finite confidence in `[0,1]`; animal boxes qualify at or above this value. |
| `--person-threshold VALUE` | `0.2` | Finite confidence in `[0,1]`; one qualifying person excludes the whole frame. |
| `--model PATH` | configured local model path | Local `MDV6-mit-yolov9-c` `.ckpt` weights; default is `BIRD_RECOGNITION_MEGADETECTOR_MODEL` when set. |
| `--model-config PATH` | `config_v9c.yaml` beside `--model` | Local MIT YOLOv9-C architecture config; override the path or set `BIRD_RECOGNITION_MEGADETECTOR_CONFIG`. |
| `--extensions LIST` | documented built-in allowlist | Optional explicit comma-separated supported extensions; default allowlist is `.mp4`, `.mov`, `.m4v`, `.mkv`, `.avi`, `.mpeg`, `.mpg` (case-insensitive). |
| `--help` | — | Print usage and available supported formats/settings. |

The fixed model variant (`MDV6-mit-yolov9-c`), threshold defaults, supported-format allowlist, local model/config identity, and lighting classifier rule/version must be printed in help and recorded in every run's effective settings. No positional ambiguity: paths are passed as arguments and may contain spaces.

## Processing contract

1. Validate all numeric values, input/output paths, destination safety, and both local model/config files before publishing any result. No model or config downloads are allowed.
2. Enumerate supported videos recursively in deterministic canonical-path order. An empty directory produces a clear no-input summary and no fabricated failures.
3. For each video, compute content identity, skip an unchanged completed source/settings pair, otherwise sample against presentation timestamps and run full-frame detection.
4. Exclude a frame if any person meets threshold. Store separate crops for every valid qualifying animal only on safe frames. Do not retain intermediate/full stills.
5. Persist crop images and complete metadata per frame or publish none for that frame. Continue across isolated video/frame errors when safe.
6. Print a final summary containing source counts (processed, skipped, failed), sampled frames, person-excluded, no-animal, retained, failed frames, and crops, plus actionable source/frame errors. Frame outcome counts reconcile to sampled frames.

## Exit status

| Code | Meaning |
|---:|---|
| `0` | Complete success or no supported input videos. |
| `1` | Partial or total processing failure after valid preflight. |
| `2` | Invalid CLI values, unsafe/invalid paths, or unavailable model/configuration detected before processing. |

## Privacy and output contract

- The command processes local files only and makes no network calls or external image publication.
- It never changes source videos and never substitutes filesystem modification time for capture time.
- The output manifest and crop tree are private artifacts and must be located outside version control. Excluded/failed frames and temporary full-frame stills are not published.
- See [data-model.md](../data-model.md) for persistent field meanings, identity, outcome, and atomicity constraints.
