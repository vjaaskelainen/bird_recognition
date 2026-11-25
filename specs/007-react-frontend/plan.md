# Implementation Plan: Web Frontend for Video Triage and Review

**Branch**: `007-react-frontend` | **Date**: 2026-11-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/007-react-frontend/spec.md`

## Summary

Add an owner-only React single-page app (`frontend/`) served by the existing FastAPI service,
plus the backend additions it needs: a video listing built from the ingestion manifest
(including zero-crop videos), contact sheets and browser-playable playback copies (both
unfiltered, behind sign-in), append-only video reviews and crop corrections in PostgreSQL,
and a same-origin session cookie exchanged once for the shared API key. The typed client is
generated from the committed OpenAPI file and checked in CI. Constitution 1.2.0 already
permits the unfiltered owner-review media and the session exchange, so no amendment task
remains.

## Technical Context

**Language/Version**: Python 3.14+ (backend, uv-managed); TypeScript 5 strict, React 19,
Node 26 LTS (installed locally via winget `OpenJS.NodeJS.LTS`; pinned in `frontend/.nvmrc`
and `engines` as `>=24`, and used by CI through `actions/setup-node` with `node-version-file`)

**Primary Dependencies**: backend: existing `fastapi`, `av`, `Pillow`, `psycopg` (no new
Python dependency; ffmpeg is a documented external runtime tool). Frontend (new, need owner
approval): Vite, React Router, TanStack Query v5, Tailwind CSS v4, shadcn/ui,
`openapi-typescript` + `openapi-fetch`, Vitest, Testing Library, Playwright, ESLint,
Prettier

**Storage**: ingestion SQLite manifest (read-only from the API); PostgreSQL `bird_embed`
schema gains review and correction tables (migration `005`); derived media cache in a
directory outside the repository and source folders

**Testing**: pytest (unit with fakes, opt-in PostgreSQL integration); Vitest + Testing
Library; Playwright smoke test against a stub service

**Target Platform**: desktop browser (Chromium, Firefox) on the owner's machine, loopback

**Project Type**: web application: FastAPI backend (`src/bird_recognition/api`) +
`frontend/` SPA

**Performance Goals**: SC-002 next video < 0.5 s (prefetch); SC-003 first page of 10,000
videos < 2 s; SC-005 converted clip starts < 3 s, seek < 1 s

**Constraints**: no file delete/move/rename; unfiltered media only behind sign-in and
allowed roots and never used for search/ask/export; key never in the JS bundle; single
worker; no CORS (same origin, Vite proxy in development)

**Scale/Scope**: one owner, ~10,000 videos, one conversion at a time

## Constitution Check

*GATE: pass before Phase 0; re-checked after Phase 1.*

| Principle | Status | Notes |
|---|---|---|
| I. Evidence-grounded answers | Pass | `ask` is not surfaced in the MVP; search keeps provenance and links to video/frame. |
| II. Privacy-preserving | Pass (permitted exception) | Contact sheets and playback are the exception: key required (disabled when no key is configured), allowed roots only, marked unfiltered in the UI and OpenAPI, excluded from search/ask/export, caches outside repo and sources. |
| III. Pretrained models, measured quality | Pass | No training. Corrections are stored only; export is a later spec. |
| IV. Testable, offline core | Pass | Backend tested with fakes and a fake ffmpeg runner; browser smoke test uses a stub service; PostgreSQL tests stay opt-in. Shared contract changes get boundary tests (OpenAPI currency, client drift). |
| V. CLI-first, small scope | Pass (permitted exception) | CLI unchanged and complete; UI is additive, single-owner, same-origin session only, no accounts/roles, never acts on source files. |

**Post-design re-check**: unchanged. The design adds no accounts or roles (one in-memory
session set), no write access to source files, and no cloud components.

## Project Structure

### Documentation (this feature)

```text
specs/007-react-frontend/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── api.md           # new/changed HTTP endpoints, session and media rules
│   └── ui.md            # routes, URL state, shortcuts, state model
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
src/bird_recognition/
├── api/
│   ├── app.py                 # + routers, SPA static mount
│   ├── security.py            # + cookie session acceptance, media auth rules
│   ├── settings.py            # + manifest, cache dir, UI dir, ffmpeg path
│   ├── sessions.py            # in-memory session store (new)
│   ├── routers/
│   │   ├── session.py         # POST/DELETE /v1/session (new)
│   │   ├── videos.py          # list, detail, crops, crop image (new)
│   │   ├── media.py           # contact sheet, playback status/stream (new)
│   │   └── reviews.py         # reviews, undo, bulk, crop corrections (new)
│   └── ui.py                  # static bundle + SPA fallback (new)
├── review/                    # domain code shared by API, no FastAPI imports (new)
│   ├── catalog.py             # manifest queries, status, settings drift, discovery scan
│   ├── contact_sheet.py       # PyAV frame grab + Pillow grid + layout metadata
│   ├── playback.py            # ffmpeg conversion worker, cache keys, status
│   └── store.py               # PostgreSQL review/correction persistence
└── embed/migrations/005_video_review.sql

frontend/
├── package.json, .nvmrc, vite.config.ts, tsconfig*.json, eslint/prettier config
├── src/
│   ├── api/                   # generated types (committed) + fetch client + query hooks
│   ├── routes/                # review, videos, search, sign-in
│   ├── components/            # contact sheet, crop strip, player, status badge, shell
│   └── lib/                   # URL filter state, shortcuts, prefetch
├── e2e/                       # Playwright smoke test + stub service
└── tests/                     # Vitest component tests

tests/unit/{api,review}/ , tests/integration/test_review_store.py
docs/api/openapi.json          # regenerated
docs/{usage,development}.md    # updated; .env.example gets new variables
.github/workflows/ci.yml       # + frontend job
```

**Structure Decision**: web-application layout. Domain logic lives in a framework-free
`bird_recognition.review` package (testable offline, like `payloads.py`); routers stay thin.
The SPA is a plain Vite build served by FastAPI; `frontend/dist` is not committed.

## Complexity Tracking

No constitution violations. New required operator inputs (all optional features degrade to a
per-feature status, never to a server failure): `BIRD_RECOGNITION_API_MANIFEST`,
`BIRD_RECOGNITION_API_CACHE_DIR`, `BIRD_RECOGNITION_API_UI_DIR`, `BIRD_RECOGNITION_FFMPEG`.
