# Contract: HTTP API additions

Extends [006 API contract](../../006-fastapi-service/contracts/api.md). All routes are under
`/v1`, errors are `application/problem+json`, lists are `{items, limit, offset, total}`.
The published description is `docs/api/openapi.json`, regenerated and checked in CI
(FR-017). Unless noted, routes accept `X-API-Key` **or** the session cookie.

## Authentication changes

| Route | Behaviour |
|---|---|
| `POST /session` body `{"key": "..."}` | 204 + `Set-Cookie: br_session=<token>; HttpOnly; SameSite=Strict; Path=/`. 401 `unauthorized` for a wrong key (no cookie). 403 `key_not_configured` if the service has no API key. Needs no prior authentication. |
| `GET /session` | 204 when authenticated, else 401; lets the UI decide whether to show the key prompt. |
| `DELETE /session` | 204; invalidates the token and clears the cookie. |
| Cookie-authenticated non-GET | additionally requires `Origin` equal to the request host; otherwise 403 `bad_origin`. |
| Unfiltered media routes (marked ⚠) | 403 `media_disabled` when no API key is configured; 401 without a valid key/session. |

## Videos

`GET /videos` — query: `status` (repeatable: `not_ingested|no_animals|animals|failed`),
`review` (`unreviewed|confirmed|corrected`), `folder` (relative path prefix), `from`, `to`
(capture date, ISO), `sort` (`capture_start|basename|ingested_at|crop_count`), `order`,
`limit` (≤ 200, default 50), `offset`. Defaults for triage (no animals, unreviewed) are
applied by the **UI**; the API returns everything unless filtered. Item: `VideoSummary`
(ids, path, status, failure_reason, crop_count, top_label, run_id, settings,
settings_differ, review_state, playback_status, source_available). Error: 503
`manifest_unavailable`.

`GET /videos/{source_id}` — `VideoDetail`: `VideoSummary` + detection counts, `crops[]`
(`crop_id`, `frame_number`, `elapsed_seconds`, `confidence`, `lighting`, `image_url`,
`current_correction`), `current_review`, `review_history[]`. 404 `not_found`.

`GET /videos/queue?limit=3&exclude=<id>&exclude=<id>` — next unreviewed videos in triage
order (no-animal first, then oldest capture) as `VideoDetail`; `exclude` carries ids skipped
in the session so the client can prefetch.

`GET /videos/{source_id}/crops/{crop_id}/image` — privacy-screened crop file from the
manifest output root; same containment checks as `/crops/{id}/image`.

## Media ⚠ (unfiltered, owner review only)

`GET /videos/{source_id}/contact-sheet` — `200 image/jpeg`; headers
`X-Unfiltered-Media: true`, `Cache-Control: private, max-age=3600`. 404 `not_found`,
409 `source_missing`, 503 `cache_unavailable`.

`GET /videos/{source_id}/contact-sheet/layout` — JSON layout (see data model); same
authorization and errors.

`GET /videos/{source_id}/playback` — `{status, reason?, url?}`, `status` ∈
`ready|converting|failed|unavailable|source_missing|not_started`. A first request enqueues
conversion (idempotent). `unavailable` = ffmpeg not configured.

`GET /videos/{source_id}/playback/stream` — `200/206 video/mp4`, honours `Range`, only when
`ready`; otherwise 409 `playback_not_ready`. Header `X-Unfiltered-Media: true`.

## Reviews

`POST /videos/{source_id}/reviews` — body `{outcome: confirmed|corrected, correction_kind?,
species?, missed_times?, note?}` validated per the data model → `201 Review`. 404 unknown
source; 422 invalid combinations.

`GET /videos/{source_id}/reviews` — history, newest first.

`POST /reviews/{review_id}/undo` → `204`; 404 unknown; 409 `already_undone`.

`POST /reviews/bulk` — body `{source_ids: [...], outcome: "confirmed"}`; every video must
have automatic status `no_animals`, else 422 listing offenders. → `201 {bulk_id, reviews[]}`.
Maximum 500 ids.

## Crop corrections

`PUT /crops/{crop_id}/correction` — body `{source_id, truth_kind, species_id?}` →
`201 CropCorrection` (appends a row). `DELETE /crops/{crop_id}/correction` undoes the current
one, `204`; 404 if none.

## Unchanged routes

`/search` is used as is; its crop results must let the UI link to the source video and frame
time (`source_id`, `elapsed_seconds`; added as optional fields if absent). `/ask` and
`/visits` are not used by the UI in this slice.

## Static UI

`GET /` and any non-`/v1` path serve the built SPA (`index.html` fallback) with
`X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`; no CORS headers.

## New settings (also listed in `.env.example`)

| Variable | Purpose |
|---|---|
| `BIRD_RECOGNITION_API_MANIFEST` | ingestion manifest path (inside allowed roots) |
| `BIRD_RECOGNITION_API_CACHE_DIR` | contact sheet and playback cache (outside repo and source folders) |
| `BIRD_RECOGNITION_API_UI_DIR` | built SPA directory |
| `BIRD_RECOGNITION_FFMPEG` | ffmpeg executable (default: `ffmpeg` from PATH) |

Missing manifest → `/videos*` return 503 `manifest_unavailable`; missing cache dir → media
routes return 503 `cache_unavailable`; missing ffmpeg → playback `unavailable`.
