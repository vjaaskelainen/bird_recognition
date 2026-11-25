# Research: Web Frontend for Video Triage and Review

Resolves the open items from the spec and the [exploration notes](../../.github/exploration/react-frontend-v2.md).

## 1. Source of the video list

- **Decision**: read the ingestion SQLite manifest (`source_video`, `run_source`,
  `sampled_frame`, `detection`, `animal_crop`, `ingestion_run`) through a read-only
  connection; configured with `BIRD_RECOGNITION_API_MANIFEST` (must be inside allowed roots).
  `not_ingested` videos come from scanning the recorded `input_root` with the existing
  `discover_videos`, matched by path, cached for 60 s and refreshable.
- **Rationale**: the manifest already records zero-crop videos (`run_source.crop_count = 0`,
  `no_animal_count`), so FR-002 needs no ingest change; PostgreSQL only holds crops after
  `index`, so it cannot list unprocessed or empty videos.
- **Alternatives**: copy videos into PostgreSQL (needs a writer and sync); require `index`
  before listing (hides the main use case).
- **Caveat**: path matching cannot see content changes until re-ingest; documented.

## 2. Joining manifest and reviews across two databases

- **Decision**: load the set of source ids with a current review from PostgreSQL (tens of
  thousands of short strings at most) into a temporary table on the read-only SQLite
  connection, then filter/sort/page in SQL.
- **Rationale**: keeps SC-003 with one query; no cross-database transaction needed because
  reviews only reference `source_id`.
- **Alternatives**: filter in Python after loading everything (slow at 10k); mirror manifest
  into PostgreSQL.

## 3. Top category or species

- **Decision**: species from the newest `species_decision` for the video's crops when an
  `index` run exists (fetched for the page only); otherwise the detection category `animal`.

## 4. Settings drift (FR-004)

- **Decision**: each run's `settings_json` yields effective `interval` and `animal_threshold`;
  compared with the current values resolved exactly as the CLI does
  (`BIRD_RECOGNITION_INTERVAL`, `BIRD_RECOGNITION_ANIMAL_THRESHOLD`, defaults 1.0 / 0.2).
  A video carries `settings_differ` and both value pairs; nothing is re-ingested.

## 5. Media authentication (spec: session sign-in)

- **Decision**: `POST /v1/session` with the key sets a random 256-bit token in an
  `HttpOnly; SameSite=Strict; Path=/` cookie (no `Secure` on loopback http; `Secure` when the
  request scheme is https). Tokens live in an in-memory set with 12 h idle expiry and are lost
  on restart. Existing `X-API-Key` keeps working on every route. The cookie is accepted on
  all `/v1` routes; cookie-authenticated non-GET requests must also pass an `Origin` check
  equal to the request host.   Unfiltered media endpoints are disabled (`403 media_disabled`) when no key
    is configured, because unfiltered media must sit behind sign-in (FR-012); other routes keep
    their current no-key loopback behaviour.
- **Rationale**: `<img>`/`<video>` cannot send headers, including range requests. Server-held
  tokens avoid putting the key in a cookie.
- **Alternatives**: signed `?token=` URLs (leak via history/logs, need expiry plumbing); fetch
  as blob (breaks seeking).

## 6. Playback copy generation timing

- **Decision**: lazily on first playback request, by a single background worker thread
  running `ffmpeg` (H.264 `libx264 -preset veryfast -crf 26`, `-an`, `+faststart`), one
  conversion at a time. `GET /v1/videos/{id}/playback` returns `ready | converting | failed |
  unavailable | source_missing`; the player polls. Already browser-playable sources (`.mp4`
  with H.264, probed with PyAV) are streamed directly without conversion. Cache key:
  `<source content sha256>-v1.mp4` in `BIRD_RECOGNITION_API_CACHE_DIR/playback`. Retention:
  keep; no pruning in this slice.
- **Rationale**: ingest stays fast and nothing is converted for the (many) videos that are
  confirmed from the contact sheet alone. The spec asks to decide after measuring; ffmpeg is
  not installed on the development machine, so measurement is a quickstart step (§6) and the
  `-v1` suffix plus a single settings constant allow switching to ingest-time generation
  later without touching the API.
- **Alternatives**: convert during ingest (slows the main job, converts videos nobody
  opens); PyAV-only transcoding (works but ffmpeg is the documented dependency in the spec
  and handles MJPEG/AVI more predictably).
- **Range requests**: `FileResponse` in the pinned Starlette must be verified to honour
  `Range`; if not, a small range-aware response helper is added (task).

## 7. Contact sheet

- **Decision**: up to 12 evenly spaced sampled frames (by `sampled_frame` order), decoded
  with PyAV at the recorded frame numbers/timestamps, scaled to 480 px wide, composed into a
  grid with Pillow (4 columns), cached as JPEG in `<cache>/sheets`, key
  `<sha256>-<settings_fingerprint>-12-v1.jpg`. Response also gives layout JSON (tile
  rectangles, frame number, elapsed seconds, normalized detection boxes, qualifies flag).
  Boxes and timestamps are drawn by the UI as an SVG overlay, not baked in, so frames stay
  clickable (missed-animal time) and boxes can toggle.
- **Rationale**: a bounded size for any video length; frames are not stored by ingest, so
  they are re-decoded once and cached.
- **Alternatives**: bake boxes into the image (loses interactivity); store frames at ingest
  (privacy and disk cost).

## 8. Persistence of reviews

- **Decision**: migration `005_video_review.sql` in the existing `bird_embed` chain adds
  `video_review`, `video_review_undo`, `crop_correction`, `crop_correction_undo`. Rows are
  immutable; the current review is the latest row without an undo. *Skip* stores nothing (the
  video stays unreviewed; the queue moves it to the end for the session). The automatic result
  is snapshotted as JSON in every review row so it survives re-ingest.
- **Rationale**: append-only history with no UPDATE path; reuses migration machinery and
  integration test setup. Crop corrections key on `crop_id` without a foreign key because
  crops exist in the manifest before `index` creates snapshots.
- **Alternatives**: separate schema (extra migrator); SQLite review file (second writer,
  weaker integrity).

## 9. Crop images before indexing

- **Decision**: new `GET /v1/videos/{source_id}/crops/{crop_id}/image` resolves the file
  from the manifest under the run's output root and allowed roots (same containment checks as
  the existing endpoint). The existing `/crops/{id}/image` remains for search results.
- **Rationale**: the review queue must work before `index`.

## 10. Bulk confirm (FR-016)

- **Decision**: `POST /v1/reviews/bulk` accepts source ids whose automatic status is
  `no_animals`, writes one review row each in one transaction and returns the review ids so
  each can be undone. The UI first shows a deterministic random sample (up to 12 contact
  sheets) and requires an explicit confirmation of the total count.

## 11. Serving the SPA and CORS

- **Decision**: FastAPI mounts `BIRD_RECOGNITION_API_UI_DIR` (default `frontend/dist` when it
  exists) at `/` with fallback to `index.html` for non-`/v1` paths. Development uses the Vite
  proxy to `127.0.0.1:8000`, so the cookie stays same-origin and no CORS is configured.

## 12. Frontend stack

- **Decision**: Vite + React 19 + strict TypeScript; React Router (library mode) with
  filters in URL search params; TanStack Query v5 for server state, polling and next-video
  prefetching; Tailwind v4 + shadcn/ui; paged table (limit 50, server paging) instead of
  virtualization because SC-003 targets first-page latency; `openapi-typescript` types
  generated from `docs/api/openapi.json`, committed, and checked with a `git diff --exit-code`
  after regeneration in CI.
- **Alternatives**: Next.js/React Router framework mode (SSR unneeded); Mantine (heavier);
  TanStack Table virtualization (deferred until paging proves insufficient).

## 13. Testing and CI

- **Decision**: new CI job `frontend`: `npm ci`, ESLint, Prettier check, `tsc --noEmit`,
  client-drift check, Vitest, Playwright (Chromium) against `e2e/stub-server` that implements
  the contract with canned data, a protected image requiring the cookie, and a small
  H.264 MP4 fixture. Backend: unit tests with a fake ffmpeg runner and synthetic PyAV
  video; integration test for the review store. Actions are pinned by commit SHA
  (`actions/setup-node`, Playwright cache) when the job is written.
- **Alternatives**: Playwright with route mocking only (cannot prove cookie-authenticated
  `<img>`/`<video>` loading).

## 14. Open risks

- ffmpeg absence or failure is a per-video status (`unavailable`/`failed`), never a job error.
- Node 20.10 does not satisfy Vite's engine range. The developer machine now has Node 26 LTS
  (after removing the Nodist shim that shadowed it); the first task must verify that Vite,
  Playwright and the other approved dependencies install and run on it, and fall back to
  Node 24 LTS in `.nvmrc` if any do not.
- Unfiltered media routes need a dedicated test proving 401/403 without session (SC-007).
