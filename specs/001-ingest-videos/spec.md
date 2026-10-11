# Feature Specification: Ingest Trail-Camera Videos

**Feature Branch**: `main` (existing branch; no branch-creation hook configured)

**Created**: 2026-10-11

**Status**: Draft

**Input**: User description: "Ingest — Extract stills from trail-camera videos, detect animals with MegaDetector, drop empty frames and frames containing people, store crops with metadata (timestamp, source video, frame, day/night, bounding box)."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Produce Privacy-Filtered Animal Crops (Priority: P1)

As the footage owner, I want to ingest local trail-camera videos and retain only animal crops from sampled frames without detected people, so I can prepare wildlife evidence without manually reviewing every frame.

**Why this priority**: Usable animal images and person exclusion are the essential ingestion outcome and privacy boundary.

**Independent Test**: Ingest a small video with controlled detection results covering animals, empty scenes, people, and mixed animal/person scenes. Inspect the retained crops and rejection counts without indexing or search.

**Acceptance Scenarios**:

1. **Given** a readable video and a sampling interval, **When** ingestion runs, **Then** it samples from the start at the requested interval, records each sampled frame's original frame number and elapsed time, and evaluates the entire sampled frame before retaining crops.
2. **Given** a sampled frame with two qualifying animal detections and no qualifying person detection, **When** filtering completes, **Then** two separate crops are stored, each linked to its own detection and the same source frame.
3. **Given** a frame with no qualifying animal detection, including a vehicle-only frame, **When** filtering completes, **Then** no crop is stored and the frame is counted as having no qualifying animal.
4. **Given** a frame with a qualifying person detection, whether or not animals are also detected, **When** filtering completes, **Then** the whole frame is excluded, no crop or retained still from it is stored, and the frame is counted as excluded for people.
5. **Given** a detection confidence equal to the configured category threshold, **When** filtering runs, **Then** it qualifies; a confidence below the threshold does not qualify.

---

### User Story 2 - Trace Every Crop to Its Source (Priority: P2)

As the footage owner, I want each retained crop to carry its original frame, timing, lighting, and bounding-box information, so later search and answers can cite the source and distinguish day and night footage.

**Why this priority**: Images without reliable provenance cannot support grounded answers or useful metadata filters.

**Independent Test**: Inspect stored crop records from known source frames, including daytime, infrared night, and missing-time examples, and reconstruct each crop's position and timing in its source video.

**Acceptance Scenarios**:

1. **Given** a retained animal crop, **When** its record is inspected, **Then** it identifies the crop, original source video, zero-based original frame number, elapsed seconds, capture timestamp or explicit unknown value, day/night/unknown designation, and original-frame bounding box.
2. **Given** a reliable video start timestamp with a known timezone, **When** a sampled frame is retained, **Then** its capture timestamp equals the start timestamp plus the frame's elapsed time, with timezone information preserved.
3. **Given** a video without a reliable capture start time or timezone, **When** ingestion runs, **Then** the unavailable timing fields are explicitly marked unknown, elapsed time remains available, and file modification time is not substituted as capture time.
4. **Given** verified daylight-color and infrared-night examples, **When** their crops are retained, **Then** lighting is recorded as day and night respectively; ambiguous evidence is recorded as unknown.
5. **Given** an animal box partly outside the frame, **When** a crop is stored, **Then** its box is clipped to the frame edges and describes exactly the saved image region; boxes with no positive-area region are rejected and reported.

---

### User Story 3 - Complete and Review a Local Batch (Priority: P3)

As the footage owner, I want to run ingestion over a local video directory, see what was retained or rejected, and repeat a run safely, so I can prepare a collection without duplicate records or hidden failures.

**Why this priority**: Batch visibility and safe repetition make the core workflow practical without expanding into a service or user interface.

**Independent Test**: Process a directory with a valid video, an unreadable video, and colliding filenames in different subdirectories; repeat unchanged successful inputs and inspect the results and run summary.

**Acceptance Scenarios**:

1. **Given** a directory containing readable and unreadable videos, **When** ingestion runs, **Then** it processes readable videos, reports unreadable sources with reasons, and clearly reports partial failure rather than an unqualified success.
2. **Given** previously completed videos with unchanged contents and effective settings, **When** ingestion is repeated into the same destination, **Then** it does not create duplicate crop records or files and reports those sources as already processed.
3. **Given** two distinct source videos with the same filename, **When** both are processed, **Then** their crops and source records remain distinguishable and neither overwrites the other's output.
4. **Given** a completed run, **When** the owner reviews its summary, **Then** it reports processed, skipped, and failed videos; sampled frames; person exclusions; no-animal exclusions; frame processing failures; and stored crops.
5. **Given** a detection or storage failure, **When** it occurs, **Then** the affected frame yields no newly published crops unless all its crops and metadata are complete, the failure is reported, and no incomplete result is presented as successful.

### Edge Cases

- A video shorter than the sampling interval yields its first readable frame; zero-duration or entirely unreadable videos are reported as failures.
- An empty input directory completes with zero counts and a clear no-input message.
- Invalid sampling intervals or confidence thresholds are rejected before any outputs are produced.
- Variable frame rates use actual frame timing rather than an assumed constant frame rate.
- A corrupt sampled frame or failed detection is not treated as empty or safe; it is excluded and reported as a processing failure.
- Person exclusion takes precedence over animal retention and every other rejection category.
- Partial, overlapping, or small animal detections produce separate crops when they qualify and have valid boxes; this feature does not merge animals or track visits.
- Interrupted runs can be repeated without duplicate successful results or crop records pointing to missing images; recovery does not publish unchecked frames.
- Changing source contents or ingestion settings is not treated as an unchanged rerun and must not silently overwrite existing results.
- Detection can miss people. Filtering is not a guarantee of anonymity; publishing a sample still requires manual privacy review.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The owner MUST be able to initiate local ingestion through the command line for a video directory and choose an output destination outside version-controlled data.
- **FR-002**: The system MUST accept a positive sampling interval in seconds, defaulting to one second, sample from elapsed time zero while frames are available, and preserve the actual original frame number and elapsed time of every sampled frame.
- **FR-003**: The system MUST evaluate complete sampled frames for animals and people using pretrained detection. Animal and person confidence thresholds MUST be separately configurable within [0, 1], have documented defaults, and qualify detections at or above the respective threshold. The effective sampling and detection settings MUST be recorded with each run.
- **FR-004**: The system MUST exclude an entire sampled frame when any person detection qualifies, even when an animal qualifies. No derived image from an excluded frame MUST remain in the retained output; failed or incomplete detection MUST also prevent retention. Source videos MUST remain unmodified.
- **FR-005**: The system MUST discard frames with no qualifying animal detections and MUST store one crop per qualifying, positive-area animal box in frames that pass person filtering. Vehicle detections alone MUST NOT produce crops.
- **FR-006**: The system MUST clip boxes to the source frame bounds, reject malformed or zero-area boxes, and store each saved crop's box as original-frame pixel coordinates (left, top, right, bottom), with right and bottom exclusive, together with source frame width and height.
- **FR-007**: Every stored crop MUST have a stable identity, a retrievable image location, an unambiguous source-video identity and original location, a zero-based original frame number, elapsed seconds, capture timestamp and timezone when reliable (explicit unknowns otherwise), day/night/unknown designation, bounding box, and animal detection confidence. Records MUST link to their ingestion run and effective settings.
- **FR-008**: Capture timestamps MUST be derived only from a reliable video capture start time plus elapsed time. Missing or timezone-ambiguous values MUST NOT be fabricated or replaced with ingestion time or file modification time. Available local capture times MAY be retained with an explicitly unknown timezone.
- **FR-009**: Each retained frame MUST receive a day, night, or unknown designation based on its lighting evidence. All crops from that frame MUST share the designation; the rule used MUST be documented and recorded with the run.
- **FR-010**: Crop images and metadata MUST persist after the run and remain available for later indexing without repeating ingestion. Successful publication of a frame's results MUST require all its crop images and corresponding records to be complete; failed publication MUST NOT leave partial successful results.
- **FR-011**: Repeating unchanged source contents with unchanged effective settings into the same destination MUST NOT create duplicate outputs. Distinct videos sharing a filename MUST NOT collide. Changed inputs or settings MUST be identified as different work, without silently replacing prior outputs.
- **FR-012**: The system MUST report input validation errors before processing, isolate individual video or frame failures where continued processing is safe, and distinguish complete success, no input, and partial or total failure. Sampled-frame totals MUST reconcile into mutually exclusive person-excluded, no-animal, retained, and failed outcomes; crop counts MUST be separate from retained-frame counts.
- **FR-013**: Raw footage, extracted stills, and crops MUST remain outside version control, except for deliberately prepared, manually privacy-checked samples. Ingestion MUST NOT publish images externally. Any intermediate stills MUST be temporary and excluded frames MUST NOT enter retained image storage.
- **FR-014**: Sampling, filtering, cropping, metadata, rerun, and failure behavior MUST be verifiable with small local fixtures and controlled detection results without live external services or credentials.

### Key Entities *(include if feature involves data)*

- **Source Video**: An original local recording, identified independently of its basename; includes original location, content identity, capture start time and timezone when available.
- **Sampled Frame**: A full-frame still at an original frame number and elapsed time, with dimensions, capture timing, lighting designation, and a mutually exclusive processing outcome. Its image need not be retained.
- **Detection**: An animal or person finding associated with a sampled frame, including category, confidence, and bounding box; used to determine exclusion or crop creation.
- **Animal Crop**: A retained image and metadata record linked to one animal detection, its source frame and video, and the run that produced it.
- **Ingestion Run**: A local batch operation with effective sampling, detection, and lighting settings, destination, source statuses, outcome counts, and actionable failures. Rejection records do not require retaining rejected images.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a fixture set with controlled detections covering animals, empty scenes, vehicles, people, and mixed scenes, 100% of expected qualifying animal crops from safe frames are retained, and zero crops or retained stills originate from person-excluded or failed-detection frames.
- **SC-002**: 100% of stored fixture crops have all required provenance fields, correct original frame numbers and elapsed times, and boxes matching their image regions; unavailable absolute timing is explicitly unknown rather than invented.
- **SC-003**: Verified daylight and infrared-night fixtures receive their expected lighting designation in 100% of cases, and the ambiguous fixture receives unknown.
- **SC-004**: A repeated unchanged run adds zero duplicate images or records; two sources with identical basenames retain distinct provenance and outputs.
- **SC-005**: A mixed readable/unreadable fixture batch retains the expected safe crops from readable sources, identifies every induced failure, leaves zero incomplete published crop records, and reports frame totals that reconcile exactly.
- **SC-006**: The owner can turn a prepared directory into a persistent, inspectable crop collection in one command-line invocation without manually selecting individual frames or using indexing, search, or external services.

## Assumptions

- This feature serves one owner processing locally held trail-camera videos. Recursive directory discovery includes supported videos in subdirectories; supported formats and detection defaults will be documented during planning.
- One-second sampling is a small-project default, not a promise to capture every wildlife appearance. Detection thresholds and sampling can be adjusted without training or fine-tuning models.
- MegaDetector is the requested pretrained detector and a project constraint; compatibility, model setup, storage format, and dependency choices belong in the implementation plan rather than this specification.
- Day/night refers to daylight-color versus low-light/infrared-night imagery, not an inference from clock time alone. An unknown value is permitted when evidence is insufficient; the initial classification rule will be specified in planning and checked against representative fixtures.
- Capture start times and timezones may be unavailable. Relative frame timing always remains usable; filenames and file modification times are not assumed to provide trustworthy capture times.
- Person filtering operates on detected people at the configured threshold, not guaranteed ground truth. Raw source videos may contain people and remain under the owner's control; manual review is required before sharing samples.
- Ingestion ends with stored crops and provenance. Embeddings, species tagging, vector indexing, search, question answering, visit tracking, cloud services, authentication, and UI work are out of scope.
- Detection quality and throughput on real footage require later measured evaluation. Fixture outcomes validate workflow correctness, not an unmeasured model-accuracy or processing-speed claim.
