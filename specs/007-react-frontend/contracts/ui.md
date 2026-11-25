# Contract: UI behaviour

## Routes

| Path | View | Notes |
|---|---|---|
| `/sign-in` | key prompt | shown whenever `GET /v1/session` is 401; the key lives only in the form until exchanged |
| `/` | redirect | to `/review` if any unreviewed video exists, else `/videos` |
| `/review` | review queue | optional `?video=<source_id>` to start at a video |
| `/videos` | videos list | default URL params: `status=no_animals&review=unreviewed` |
| `/search` | crop search | `?q=` |

Filters, sort and page are URL search params (`status`, `review`, `folder`, `from`, `to`,
`sort`, `order`, `page`); reloading or reopening a URL reproduces the view (US1).

## Persistent chrome

- Badge "Local · privacy-screened crops"; contact sheet and player areas carry a distinct
  "Unfiltered footage" marker (FR-012, FR-014).
- Search and any similarity/confidence value always show "Not a probability".
- No control deletes, moves or renames files.

## Review queue

- Contact sheet with SVG detection boxes and timestamps, automatic result, crop strip,
  effective threshold/interval (drift warning when `settings_differ`).
- Actions: **Confirm** `C`, **Correct** `E`, **Skip** `S`, **Undo** `Z`, **Open player**
  `P`, **Next/Previous** `→`/`←`. Shortcuts are disabled while typing in an input.
- *Correct* dialog: "No animal here" / "Animal missed" (time prefilled from the player
  position or a clicked contact-sheet frame, editable, several allowed) / "Species or category
  present" (multi-select), optional note.
- Per-crop controls: species, "not in list", "unidentifiable"; saved immediately, independent
  of the video decision.
- Prefetch: after loading video *n*, the contact sheet image, layout and crop images of the
  next two queue items are fetched into the Query/HTTP cache. Skipped ids are excluded for the
  session.
- Bulk confirm: from the Videos list with the default filter; shows a sample (≤ 12 sheets) and
  the total count before the final confirmation is enabled.
- Unsaved review input survives a failed request (error banner with retry) and re-sign-in.

## Player

Native `<video>` on `/v1/videos/{id}/playback/stream`. Polls every 2 s while `converting`;
`failed`/`unavailable`/`source_missing` shows a per-video message and leaves sheet and review
usable. Current time feeds the "animal missed" field.

## Error states

| Condition | UI |
|---|---|
| 401 on any call | redirect to `/sign-in`, preserving the return URL |
| 503 `manifest_unavailable` | Videos view explains how to configure it |
| network error | non-blocking banner with retry; local input kept |
| empty result sets | explicit empty states (no videos, no matches, nothing to review) |

## Test hooks

Stable `data-testid` values for the smoke test: `video-row`, `contact-sheet`,
`action-confirm`, `action-correct`, `action-skip`, `action-undo`, `status-badge`.
