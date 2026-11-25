# Quickstart: Validating the Web Frontend

Run from the repository root. Contracts: [api.md](contracts/api.md), [ui.md](contracts/ui.md);
entities: [data-model.md](data-model.md). Footage, models, caches and manifests stay outside
the repository.

## Prerequisites

- Python environment synced; Node 26 LTS and npm (`node --version` must report v26 in a new terminal) (`frontend/.nvmrc`); frontend dependencies
  approved and installed (`npm ci` in `frontend`).
- ffmpeg on PATH or `BIRD_RECOGNITION_FFMPEG` (only for playback of non-browser formats).
- An ingested footage set (see the [ingestion quickstart](../001-ingest-videos/quickstart.md))
  with at least one video with zero animals, one with animals, and one failing file.
- In `.env` (see `.env.example`): `BIRD_RECOGNITION_API_KEY`,
  `BIRD_RECOGNITION_API_ALLOWED_ROOTS`, `BIRD_RECOGNITION_API_MANIFEST`,
  `BIRD_RECOGNITION_API_CACHE_DIR`, `BIRD_RECOGNITION_DATABASE_URL`.

## 1. Automated checks (offline)

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\uv.exe run bird-recognition-api export-openapi --check
cd frontend
npm run lint
npm run typecheck
npm run api:check
npm test
npm run e2e
```

Expected: all pass without network, model or LLM access; `api:check` fails if
`docs/api/openapi.json` changed without regenerating the client types (FR-017); `e2e` runs
the browser smoke test against the stub service (FR-018, SC-007).

## 2. Database tests (opt-in, disposable database only)

```powershell
.\.venv\Scripts\python.exe -m pytest tests\integration\test_review_store.py
```

Expected: review/undo/history and crop correction invariants hold; migration `005` applies.

## 3. Build and serve (US5, FR-015)

```powershell
cd frontend; npm run build; cd ..
.\.venv\Scripts\uv.exe run bird-recognition-api serve
```

Open `http://127.0.0.1:8000/`. Expected: key prompt, no data; wrong key shows an error;
correct key lands on the review queue (or Videos if nothing is unreviewed). In a private
window, requesting `/v1/videos/<id>/contact-sheet` returns 401.

## 4. Triage scenario (US1, US2)

1. Videos view shows only unreviewed no-animal videos; change a filter, reload: same view.
2. Review queue: Confirm one, Correct one as "animal missed" at a time (click a frame),
   Skip one. Reload: confirmed/corrected persist with times and notes; the skipped one is
   still unreviewed; the automatic result is still shown.
3. Undo the last decision: the video returns to the queue.
4. Set a crop truth in the queue; confirm it is stored apart from the video review.
5. Bulk-confirm from the Videos view: a sample appears first.
6. Time check: stopwatch a confirmation (SC-001 < 10 s) and next-video latency (SC-002).

## 5. Playback (US3)

Open the player for an AVI: status moves `converting → ready`, playback and seeking work.
Run the server with `BIRD_RECOGNITION_FFMPEG` pointing to a missing file: the video shows
"playback unavailable", while sheet and review still work.

## 6. Measure conversion time (decides lazy vs ingest-time conversion)

Convert a representative 30-second clip and record the time in the PR description:

```powershell
ffmpeg -i <clip.avi> -an -c:v libx264 -preset veryfast -crf 26 -movflags +faststart <out.mp4>
```

If conversion exceeds ~3 s (SC-005 applies to *already converted* clips) lazily is still
adequate; if the owner expects to open most videos, revisit ingest-time generation.

## 7. Search (US4)

Search for a species name on `/search`: crop grid with similarity and "not a probability"
caveat; selecting a crop opens its video at the frame time. Stop the database: an
understandable error state appears.

## 8. Performance (SC-003)

With a 10,000-video manifest (synthetic fixture generator in `tests/`), `GET /v1/videos`
first page returns in under 2 s.
