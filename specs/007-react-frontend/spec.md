# Feature Specification: Web Frontend for Video Triage and Review

**Feature Branch**: `007-react-frontend`

**Created**: 2026-11-25

**Status**: Draft

**Input**: User description: "react frontend" (see [exploration notes](../../.github/exploration/react-frontend-v2.md))

## User Scenarios & Testing *(mandatory)*

The owner is the only user and works locally. The main job is to triage many trail-camera
videos and find those with no birds or other animals so they can be discarded outside the
tool. A secondary purpose is a portfolio demonstration, so the first release must be a
complete slice that also shows the AI parts (detection, embeddings, search).

This specification covers the MVP slice. Later phases are listed under Assumptions.

### User Story 1 - Find videos with no animals (Priority: P1)

The owner opens the Videos view and sees every known video with a status (`not ingested`,
`no animals`, `animals`, `failed`), crop counts and top category or species for videos with
animals. The default filter shows videos with no animals that have not yet been reviewed.
Filters (status, date, folder, review state) and sorting are available and kept in the
address so a view can be bookmarked or returned to.

**Why this priority**: This is the owner's main job and the entry point to everything else.

**Independent Test**: With a mix of ingested videos (including some with zero detected
animals), open the Videos view and confirm that the default filter lists exactly the
unreviewed no-animal videos, and that changing filters and reloading preserves the view.

**Acceptance Scenarios**:

1. **Given** ingested videos with and without detections, **When** the owner opens the Videos
   view, **Then** only unreviewed no-animal videos are listed and each shows its status badge.
2. **Given** a filtered and sorted list, **When** the page is reloaded or the address is
   reopened, **Then** the same filters and sort are applied.
3. **Given** thousands of videos, **When** the owner scrolls or pages, **Then** the list stays
   responsive.
4. **Given** a video ingested with a threshold or sampling interval that differs from the
   current settings, **Then** it is flagged, and the effective values used are shown.

---

### User Story 2 - Review videos in a queue (Priority: P1)

The owner steps through videos one at a time. Each shows a contact sheet (a grid of the
sampled frames with timestamps and detection boxes), the automatic result, the detected crops,
and the effective animal threshold and sampling interval. The owner can open a player when the
sheet is unclear. The owner chooses *Confirm*, *Correct* or *Skip* using the keyboard or
mouse, and can undo the last decision. *Correct* offers: no animal here; animal missed (with an
approximate time, taken from the player position or a clicked frame); set the species or
category present. The next video's sheet and crops are loaded ahead of time so moving forward
feels instant. Bulk-confirming no-animal results first shows a sample.

**Why this priority**: Triage is only trustworthy if the owner can verify the result quickly,
and corrections are the data that later improves the system.

**Independent Test**: Review three videos (one confirmed, one corrected as "animal missed" at a
given time, one skipped); reload and confirm the decisions, notes and times persisted and the
original automatic result is still visible.

**Acceptance Scenarios**:

1. **Given** unreviewed videos exist, **When** the owner opens the app, **Then** it lands on
   the review queue; otherwise on the Videos view.
2. **Given** a video in the queue, **When** the owner confirms it, **Then** the review is
   stored, the next video appears without visible loading, and the video is no longer in the
   unreviewed filter.
3. **Given** a video with a "no animals" result, **When** the owner marks "animal missed" at a
   time, **Then** that time is stored with the review.
4. **Given** a decision just made, **When** the owner undoes it, **Then** the video returns to
   unreviewed in the queue.
5. **Given** a crop shown in the queue, **When** the owner sets its truth (species, not in
   list, unidentifiable), **Then** the per-crop correction is stored separately from the
   video-level review.
6. **Given** a corrected video, **Then** the original automatic result and the full review
   history remain visible.

---

### User Story 3 - Play the original video in the browser (Priority: P2)

For unclear cases the owner opens a player with seeking. Source videos that browsers cannot
play are played through a converted copy. If conversion is unavailable or fails for a video,
that video shows a clear per-video status and the rest of the app is unaffected.

**Why this priority**: The contact sheet resolves most cases; playback resolves the rest.

**Independent Test**: Open a trail-camera video in the player, seek to the middle, and confirm
playback continues; for a video whose conversion fails, confirm a status message appears.

**Acceptance Scenarios**:

1. **Given** a video in a format browsers cannot play, **When** the owner opens the player,
   **Then** it plays and seeks.
2. **Given** conversion is unavailable, **When** the owner opens the player, **Then** a per-video
   "playback unavailable" status is shown and contact sheet and review still work.

---

### User Story 4 - Search crops (Priority: P2)

The owner types a text query and sees a grid of matching crops with similarity shown, each
linking to its video and frame position. The caveat that similarity is not a probability is
always visible.

**Why this priority**: Demonstrates the embedding and search capabilities for the portfolio.

**Independent Test**: Search for a species name and confirm a crop grid appears, and selecting
a crop opens its video at the right place.

**Acceptance Scenarios**:

1. **Given** indexed crops, **When** the owner searches by text, **Then** matching crops are
   shown with similarity and a link to the source video.
2. **Given** no matches or an unreachable service, **Then** an understandable empty or error
   state is shown.

---

### User Story 5 - Sign in once (Priority: P1)

The owner enters the service key once. Afterwards images and videos load in the app without
further prompts, and the key is never embedded in the published application files.

**Why this priority**: Without this, protected images and playback cannot work.

**Independent Test**: Open the app signed out and confirm a key prompt; enter the key and
confirm crops, contact sheets and video load; confirm media URLs fail when requested without
signing in.

**Acceptance Scenarios**:

1. **Given** the owner is not signed in, **When** the app is opened, **Then** a key prompt is
   shown and no data is displayed.
2. **Given** a wrong key, **Then** a clear error is shown and no session starts.
3. **Given** a signed-in session, **When** media is requested directly from outside the app
   session, **Then** it is refused.

---

### Edge Cases

- Videos with zero crops must still appear (as `no animals`), not be missing.
- Failed ingests appear as `failed` with their reason, distinct from `no animals`.
- Very short or very long videos: the contact sheet shows a bounded number of evenly spaced
  frames.
- Two reviews of the same video: the latest is current; earlier ones stay in history.
- Service unreachable or key rejected mid-session: the app shows a recoverable error and keeps
  unsaved review input.
- Source video moved or removed after ingest: shown as unavailable; stored reviews remain.
- The app must never delete, move or rename files.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST list all known videos with status, crop count, top category or
  species, ingest run and review state, with filtering, sorting and pagination.
- **FR-002**: The system MUST record videos with zero detected animals so they appear as
  `no animals`.
- **FR-003**: The Videos view MUST default to unreviewed no-animal videos and keep filters in
  the address.
- **FR-004**: The system MUST show the effective animal threshold and sampling interval for each
  video's ingest run and flag runs that differ from current settings, without re-ingesting.
- **FR-005**: The system MUST provide a per-video contact sheet with timestamps and detection
  boxes drawn on frames.
- **FR-006**: The system MUST provide a review queue with Confirm, Correct, Skip and undo,
  keyboard shortcuts, and preloading of the next video.
- **FR-007**: The system MUST store one current owner review per video (outcome, corrected
  species or category list, note, timestamp) while keeping the original automatic result and an
  append-only history.
- **FR-008**: The system MUST store approximate times for "animal missed" outcomes.
- **FR-009**: The system MUST store optional per-crop corrections using the same truth kinds as
  evaluation labels (species, not in list, unidentifiable), separate from video-level reviews.
- **FR-010**: The system MUST let the owner play videos with seeking in the browser, converting
  unsupported formats to a cached copy kept outside source folders and outside version control,
  with a per-video status when conversion is unavailable or fails.
- **FR-011**: The system MUST require the owner to sign in once with the service key and then
  allow media to load without exposing the key in published application files.
- **FR-012**: Contact sheets and playback are unfiltered (not privacy-screened); they MUST sit
  behind sign-in and the allowed folder roots, and the UI MUST mark them as unfiltered.
- **FR-013**: The system MUST provide a text search over crops with a crop grid linking to the
  source video, and always show that confidence and similarity are not probabilities.
- **FR-014**: The UI MUST show a visible "local / privacy-screened" indicator and MUST NOT
  delete, move or rename files.
- **FR-015**: The application MUST be served by the existing local service so no cross-origin
  setup is needed, and be usable in a desktop browser.
- **FR-016**: Bulk-confirming no-animal results MUST first show a sample of those videos.
- **FR-017**: Changes to the service contract MUST be reflected in the published API
  description, and the frontend's typed client MUST be checked against it in CI.
- **FR-018**: Frontend lint, tests and a browser smoke test against a stubbed service MUST run
  in CI, and usage and development documentation MUST be updated.

### Key Entities

- **Video**: A source file with status, ingest run, effective detection settings, playback
  status, contact sheet availability and review state.
- **Review**: The owner's decision for a video: outcome, corrected species or category list,
  note, missed-animal times, timestamp; the automatic result is kept alongside; history is
  append-only.
- **Crop correction**: The owner's truth for one crop.
- **Contact sheet**: A grid of sampled frames of one video with timestamps and detection boxes.
- **Playback copy**: A browser-playable converted version of a video.
- **Session**: The signed-in state created by entering the service key.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The owner can review a no-animal video (view sheet, confirm) in under 10 seconds
  on average.
- **SC-002**: Moving to the next video in the queue shows its contact sheet in under 0.5 seconds
  in at least 95% of cases.
- **SC-003**: The Videos view shows the first page of a 10,000-video library in under 2 seconds.
- **SC-004**: 100% of saved reviews, times and crop corrections are present after a restart,
  with the original automatic result intact.
- **SC-005**: Playback starts in under 3 seconds for an already converted 30-second clip, and
  seeking resumes in under 1 second.
- **SC-006**: A first-time owner can go from opening the app to a confirmed review within
  2 minutes without documentation beyond the on-screen guidance.
- **SC-007**: No protected media is retrievable without signing in, verified by an automated test.

## Assumptions

- Single owner, local use, loopback by default; no accounts or roles.
- Processing (ingest and embed) is still started from the command line or existing job
  endpoints in this slice; process selection, job views, folder tree, an Overview page,
  video detail with crop gallery, evaluation-label export, species tagging and visits UI are
  later phases.
- Required service additions: video listing with zero-crop videos, review and crop-correction
  storage, playback conversion, contact sheets, session sign-in for media and serving of the
  built application. These are planned together with this feature.
- Playback and contact sheets deliberately amend the current "no unfiltered frames" rule; the
  API contract and the constitution (which treats UI as optional, later work and limits
  authentication to a shared key) MUST be amended before implementation to permit this UI and
  the session sign-in.
- Conversion needs ffmpeg as a documented runtime dependency; timing (during ingest or on first
  request), contact sheet frame cap (default: 12 evenly spaced) and cache retention (default:
  keep) are decided during planning, after measuring conversion time.
- Missed-animal time is entered from the player position or by clicking a frame.
- Per-crop corrections are available in the review queue in this slice.
