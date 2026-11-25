# Tasks: Web Frontend for Video Triage and Review

**Input**: Design documents from `/specs/007-react-frontend/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, contracts/ui.md, quickstart.md

**Tests**: Requested (FR-018, SC-007, constitution IV): pytest with fakes, Vitest, one Playwright smoke test against a stub service. Write each test before its implementation and see it fail.

**Approvals**: Frontend dependencies (Vite, React, React Router, TanStack Query, Tailwind, shadcn/ui, openapi-typescript/openapi-fetch, Vitest, Testing Library, Playwright, ESLint, Prettier) and Node install need owner approval before T002. No new Python dependency.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: parallelizable (different files, no dependency on incomplete tasks)
- **[Story]**: US1 videos list, US2 review queue, US3 playback, US4 search, US5 sign-in

## Phase 1: Setup

- [X] T001 Create the `frontend/` skeleton, `frontend/.nvmrc` (Node 26) and `engines` (`>=24`) in `frontend/package.json`
- [X] T002 Install frontend dependencies listed in plan.md (after owner approval) and configure Vite + dev proxy of `/v1` in `frontend/vite.config.ts`, strict TypeScript in `frontend/tsconfig.json`, `frontend/tsconfig.node.json`
- [X] T003 [P] Configure ESLint and Prettier in `frontend/eslint.config.js`, `frontend/.prettierrc`
- [X] T004 [P] Configure Tailwind v4 and shadcn/ui in `frontend/src/index.css`, `frontend/components.json`
- [X] T005 [P] Configure Vitest + Testing Library in `frontend/vitest.config.ts`, `frontend/tests/setup.ts`
- [X] T006 [P] Add new variables (`BIRD_RECOGNITION_API_MANIFEST`, `BIRD_RECOGNITION_API_CACHE_DIR`, `BIRD_RECOGNITION_API_UI_DIR`, `BIRD_RECOGNITION_FFMPEG`) to `.env.example`
- [X] T007 [P] Ignore `frontend/node_modules` and `frontend/dist` in `.gitignore`

## Phase 2: Foundational (blocks all stories)

- [X] T008 Add manifest, cache dir, UI dir and ffmpeg settings in `src/bird_recognition/api/settings.py`
- [X] T009 Write migration `src/bird_recognition/embed/migrations/005_video_review.sql`: `video_review` (outcome in `confirmed|corrected`, `correction_kind` NOT NULL iff corrected, `species` jsonb, `missed_times` jsonb, `note` ≤ 2000 chars, `auto_result` jsonb NOT NULL, `bulk_id`), `video_review_undo`, `crop_correction` (`truth_kind` in `species|out_of_list|unidentifiable`, `species_id` NOT NULL iff species), `crop_correction_undo`; append-only
- [X] T010 [P] Unit tests for catalog status derivation, zero-crop videos, failed videos, latest run wins, settings drift, not-ingested discovery scan in `tests/unit/review/test_catalog.py`
- [X] T011 Implement manifest queries and discovery scan (read-only, allowed-root-relative `path_id`) in `src/bird_recognition/review/catalog.py` (+ `src/bird_recognition/review/__init__.py`)
- [X] T012 [P] Unit tests for in-memory session store (hashed token, 12 h idle expiry, revoke) in `tests/unit/api/test_sessions.py`
- [X] T013 Implement session store in `src/bird_recognition/api/sessions.py`
- [X] T014 [P] Unit tests for cookie acceptance, `bad_origin` on cookie non-GET, `media_disabled` without key, X-API-Key still accepted in `tests/unit/api/test_security_session.py`
- [X] T015 Extend `src/bird_recognition/api/security.py` with cookie session acceptance and media auth rules
- [X] T016 [P] Unit tests for review/correction validation rules, current-review resolution, undo fallback to previous review in `tests/unit/review/test_store.py`
- [X] T017 Implement review/correction persistence in `src/bird_recognition/review/store.py`
- [X] T018 [P] Opt-in integration test for the store and migration `005` in `tests/integration/test_review_store.py`
- [X] T019 Wire new routers, settings and dependencies in `src/bird_recognition/api/app.py`; regenerate `docs/api/openapi.json` (repeat after each API story)
- [X] T020 [P] Add CI check that `docs/api/openapi.json` is current and that `frontend/src/api/schema.d.ts` regenerates without diff (`openapi-typescript`) in `.github/workflows/ci.yml`
- [X] T021 Frontend shell: router, `QueryClientProvider`, typed `openapi-fetch` client with 401 → `/sign-in?return=` handling, error banner, privacy badge "Local · privacy-screened crops" in `frontend/src/api/client.ts`, `frontend/src/main.tsx`, `frontend/src/components/Shell.tsx`

**Checkpoint**: foundation ready.

## Phase 3: User Story 5 - Sign in once (P1)

**Goal**: key exchanged once for a session cookie; media protected.

**Independent Test**: signed out shows key prompt; correct key loads media; direct media request without session is refused.

- [X] T022 [P] [US5] API tests for `POST/GET/DELETE /v1/session` (204, 401 wrong key, 403 `key_not_configured`, cookie flags HttpOnly/SameSite=Strict) in `tests/unit/api/test_session_router.py`
- [X] T023 [US5] Implement `src/bird_recognition/api/routers/session.py`
- [X] T024 [P] [US5] Automated test that every unfiltered media route refuses unauthenticated requests (SC-007) in `tests/unit/api/test_media_auth.py`
- [X] T025 [P] [US5] Vitest for sign-in form (wrong key error, success redirect to return URL, key not persisted) in `frontend/tests/sign-in.test.tsx`
- [X] T026 [US5] Implement `frontend/src/routes/SignIn.tsx` and session guard in `frontend/src/api/session.ts`

## Phase 4: User Story 1 - Find videos with no animals (P1) 🎯 MVP

**Goal**: filterable, sortable, paginated video list with URL-held state.

**Independent Test**: default filter lists exactly unreviewed no-animal videos; filters survive reload.

- [X] T027 [P] [US1] API tests for `GET /v1/videos` filters, sort, pagination (limit ≤ 200), 503 `manifest_unavailable`, and `GET /v1/videos/{source_id}` (404 `not_found`) in `tests/unit/api/test_videos_router.py`
- [X] T028 [US1] Implement `src/bird_recognition/api/routers/videos.py` (list, detail, crop image with containment checks, `VideoSummary`/`VideoDetail` models)
- [X] T029 [P] [US1] Vitest for URL filter state (`status`, `review`, `folder`, `from`, `to`, `sort`, `order`, `page`; defaults `status=no_animals&review=unreviewed`) in `frontend/tests/filters.test.ts`
- [X] T030 [P] [US1] Implement URL filter state in `frontend/src/lib/filters.ts`
- [X] T031 [P] [US1] Status badge component (`data-testid="status-badge"`) and settings-drift flag in `frontend/src/components/StatusBadge.tsx`
- [X] T032 [US1] Videos route with rows (`data-testid="video-row"`), pagination, empty and `manifest_unavailable` states in `frontend/src/routes/Videos.tsx` and `frontend/src/api/videos.ts`
- [X] T033 [US1] Regenerate `frontend/src/api/schema.d.ts` and `docs/api/openapi.json`

## Phase 5: User Story 2 - Review videos in a queue (P1)

**Goal**: contact sheet, Confirm/Correct/Skip/Undo, crop corrections, prefetch, bulk confirm.

**Independent Test**: confirm one, correct one as "animal missed" at a time, skip one; reload; decisions persist with the automatic result intact.

- [X] T034 [P] [US2] Unit tests for contact sheet (≤ 12 evenly spaced tiles, normalized boxes, cache key `<sha256>-<fingerprint>-12-v1.jpg`) with a fake frame source in `tests/unit/review/test_contact_sheet.py`
- [X] T035 [US2] Implement PyAV + Pillow contact sheet and layout in `src/bird_recognition/review/contact_sheet.py`
- [X] T036 [P] [US2] API tests for contact sheet and layout routes (`X-Unfiltered-Media`, 404, 409 `source_missing`, 503 `cache_unavailable`) in `tests/unit/api/test_media_router.py`
- [X] T037 [US2] Implement contact sheet routes in `src/bird_recognition/api/routers/media.py`
- [X] T038 [P] [US2] API tests for reviews (create, history, undo, `already_undone`, bulk ≤ 500 only for `no_animals`, 422 combos), crop corrections (PUT/DELETE), and `GET /v1/videos/queue` with `exclude` in `tests/unit/api/test_reviews_router.py`
- [X] T039 [US2] Implement `src/bird_recognition/api/routers/reviews.py` and the queue endpoint in `src/bird_recognition/api/routers/videos.py`
- [X] T040 [P] [US2] Vitest for keyboard shortcuts (C, E, S, Z, P, ←/→; disabled while typing) in `frontend/tests/shortcuts.test.tsx`
- [X] T041 [P] [US2] Implement shortcuts in `frontend/src/lib/shortcuts.ts`
- [X] T042 [P] [US2] Contact sheet component with SVG boxes, timestamps, "Unfiltered footage" marker, `data-testid="contact-sheet"` in `frontend/src/components/ContactSheet.tsx`
- [X] T043 [P] [US2] Crop strip with per-crop species / not in list / unidentifiable controls in `frontend/src/components/CropStrip.tsx`
- [X] T044 [P] [US2] Correct dialog (no animal / animal missed with editable times / species present, note) in `frontend/src/components/CorrectDialog.tsx`
- [X] T045 [US2] Prefetch next two queue items (sheet, layout, crops) with skipped-id exclusion in `frontend/src/lib/prefetch.ts`
- [X] T046 [US2] Review route with actions (`action-confirm`, `action-correct`, `action-skip`, `action-undo`), history and auto result display, retained input on failure, effective settings and drift warning in `frontend/src/routes/Review.tsx`
- [X] T047 [US2] Bulk confirm flow (sample ≤ 12 sheets, total count, gated confirm) in `frontend/src/components/BulkConfirm.tsx`, wired into `frontend/src/routes/Videos.tsx`
- [X] T048 [US2] Index redirect (`/` to `/review` if unreviewed exist, else `/videos`) in `frontend/src/routes/Index.tsx`
- [X] T049 [US2] Regenerate OpenAPI file and `frontend/src/api/schema.d.ts`

## Phase 6: User Story 3 - Play the original video (P2)

**Goal**: seekable playback, converting unsupported formats; per-video failure status.

**Independent Test**: unsupported source plays and seeks; failed conversion shows status while sheet and review still work.

- [X] T050 [P] [US3] Unit tests for playback worker with a fake ffmpeg runner (enqueue idempotent, one at a time, `.failed` marker, `unavailable` without ffmpeg, directly playable source skipped) in `tests/unit/review/test_playback.py`
- [X] T051 [US3] Implement conversion worker, cache keys (`<sha256>-v1.mp4`, H.264, no audio, `+faststart`) and status in `src/bird_recognition/review/playback.py`
- [X] T052 [P] [US3] API tests for `/playback` and `/playback/stream` (Range/206, 409 `playback_not_ready`) in `tests/unit/api/test_playback_router.py`
- [X] T053 [US3] Add playback routes to `src/bird_recognition/api/routers/media.py`
- [X] T054 [P] [US3] Player component polling every 2 s while `converting`, per-video status messages, exposes current time in `frontend/src/components/Player.tsx`
- [X] T055 [US3] Integrate player and "animal missed" time capture (player position or clicked frame) into `frontend/src/routes/Review.tsx` and `frontend/src/components/CorrectDialog.tsx`
- [X] T056 [US3] Regenerate OpenAPI file and `frontend/src/api/schema.d.ts`

## Phase 7: User Story 4 - Search crops (P2)

**Goal**: text search grid linking to source video and frame.

**Independent Test**: search for a species; grid appears; selecting a crop opens its video at the right place.

- [X] T057 [P] [US4] Test that `/v1/search` crop results include optional `source_id` and `elapsed_seconds` in `tests/unit/api/test_search_links.py`
- [X] T058 [US4] Add optional `source_id` and `elapsed_seconds` to search results (existing search router/models under `src/bird_recognition/api/`)
- [X] T059 [P] [US4] Vitest for search states (results, empty, error) and the permanent "Not a probability" caveat in `frontend/tests/search.test.tsx`
- [X] T060 [US4] Implement `frontend/src/routes/Search.tsx` (`?q=`), linking each crop to `/review?video=<source_id>`
- [X] T061 [US4] Regenerate OpenAPI file and `frontend/src/api/schema.d.ts`

## Phase 8: Polish and cross-cutting

- [X] T062 [P] Static SPA serving with `index.html` fallback, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, no CORS, with tests in `src/bird_recognition/api/ui.py` and `tests/unit/api/test_ui.py`
- [X] T063 [P] Playwright smoke test (sign in, list, confirm, correct, skip, undo) against a stub service in `frontend/e2e/smoke.spec.ts` and `frontend/e2e/stub-server.ts`
- [X] T064 Add frontend CI job (`actions/setup-node` with `node-version-file`, actions pinned to full SHAs; lint, typecheck, Vitest, build, Playwright, client drift check) in `.github/workflows/ci.yml`
- [X] T065 [P] Update `docs/usage.md` (sign-in, new env variables, ffmpeg, unfiltered-media caveat) and `docs/development.md` (Node setup, frontend checks, client regeneration)
- [X] T066 [P] Update root `README.md` component diagram with the web UI and link to docs
- [X] T067 Run `specs/007-react-frontend/quickstart.md` validation end to end, including SC-007 check
- [X] T068 Run pre-commit (Ruff hooks), `.\.venv\Scripts\python.exe -m pytest`, and frontend lint/tests as the final step

## Dependencies and Execution Order

- Setup → Foundational → stories. US5 first (media and API need session); US1 next (MVP); US2 depends on US1 list/detail and US5; US3 depends on US2 media router and Review route; US4 depends only on Foundational + US5 (independent of US2/US3, may run in parallel with them).
- Within a story: tests → backend → frontend → regenerate client.
- T019/T033/T049/T056/T061 touch `docs/api/openapi.json` and `schema.d.ts`; do not run in parallel.
- `media.py` (T037, T053), `Review.tsx` (T046, T055) and `videos.py` (T028, T039) are shared files: sequential edits.

## Parallel Examples

- Foundational tests: T010, T012, T014, T016, T018 together.
- US2 frontend components: T042, T043, T044 together, alongside backend T034/T036/T038.

## Implementation Strategy

- **MVP**: Phases 1–4 (sign-in plus no-animal video list), then Phase 5 for the review loop (the owner's main job).
- Then US3 and US4 incrementally (independent), then Polish.
