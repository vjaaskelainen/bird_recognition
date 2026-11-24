# Feature Specification: HTTP Service for Bird Recognition

**Feature Branch**: `006-fastapi-service`

**Created**: 2026-11-24

**Status**: Draft

**Input**: User description: "fastapi service" (see `.github/exploration/fastapi-service.md`)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Search and browse crops over HTTP (Priority: P1)

A local tool or script owner starts the service and, from another program, searches the indexed bird crops, views a crop's details and image, lists indexing runs and aggregates visits, with results equivalent to the existing command-line `search`, `inspect` and `aggregate-visits` commands.

**Why this priority**: Read-only access is the lowest-risk, highest-value slice: it lets other programs consume existing results without any new processing or transmission of data.

**Independent Test**: Start the service against a database indexed in a prior feature, request a search, a crop and a visit list, and compare each result with the corresponding command-line output.

**Acceptance Scenarios**:

1. **Given** an indexed database, **When** a client submits a search request with the same inputs as the command-line `search`, **Then** it receives the same matches, ordering and caveats as the command line would print.
2. **Given** a known crop identifier, **When** a client requests its details and image, **Then** it receives the crop's metadata and the privacy-screened crop image only.
3. **Given** an unknown crop identifier, **When** a client requests it, **Then** it receives a structured "not found" error.
4. **Given** the service is running, **When** a client checks health, **Then** it learns whether the service and its database are ready.

---

### User Story 2 - Discoverable, validated API description (Priority: P1)

A developer integrating with the service reads a standards-based, machine-readable API description that is always current, to generate clients and understand request, response and error shapes.

**Why this priority**: The description is the contract; without it, other stories cannot be consumed or verified reliably.

**Independent Test**: Export the API description, validate it against the standard, and confirm it matches the committed copy.

**Acceptance Scenarios**:

1. **Given** the service source, **When** the API description is exported, **Then** it is valid and identical to the committed copy.
2. **Given** a change to an endpoint without updating the committed description, **When** continuous checks run, **Then** they fail.
3. **Given** any failed request, **When** the client reads the response, **Then** it is a standard problem-details error with a stable error code, and contains no sensitive paths or secrets.

---

### User Story 3 - Ask questions about footage (Priority: P2)

An owner submits a natural-language question over HTTP and receives an answer, with the same explicit opt-in and notice about external transmission of crops that the command-line `ask` requires.

**Why this priority**: Valuable, but it sends crops to an external provider, so it must preserve the existing consent semantics.

**Independent Test**: Submit a question with and without the opt-in; verify nothing is transmitted without it and that the notice and answer match the command-line behavior.

**Acceptance Scenarios**:

1. **Given** no explicit opt-in, **When** a client submits a question, **Then** the request is refused and nothing is sent externally.
2. **Given** explicit opt-in, **When** a client submits a question, **Then** the response includes the answer and a transmission notice equivalent to the command line.

---

### User Story 4 - Run long jobs and track them (Priority: P3)

An owner starts ingestion or indexing over HTTP, receives a job identifier immediately, and later polls it for status and the run report.

**Why this priority**: Useful for automation, but these are long, resource-heavy operations that already work from the command line.

**Independent Test**: Start a job, confirm an immediate acknowledgement, poll until completion, and compare the report with a command-line run of the same inputs.

**Acceptance Scenarios**:

1. **Given** valid inputs, **When** a client starts a job, **Then** it immediately receives a job identifier and can poll its status.
2. **Given** a finished job, **When** a client polls, **Then** it receives the same outcome category (success, partial, failure) and report as the command line.
3. **Given** a job is already running that would conflict, **When** another is requested, **Then** the request is rejected or queued with a clear message.
4. **Given** input or output paths outside permitted locations, **When** a job is requested, **Then** it is refused.

---

### Edge Cases

- Database unreachable or not initialized: health reports not ready; other requests return a structured error.
- Search or ask request with missing, oversized or malformed input: rejected with a validation error naming the field.
- Service restarted while a job was running: the job is reported as interrupted, not as running.
- Requests from non-local clients without credentials when exposed beyond localhost: rejected.
- Footage frames: full or unfiltered frames are never returned by any endpoint.
- Listing endpoints with many results: results are paginated with a bounded page size.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The service MUST expose search, crop details, crop image, run listing/inspection and visit aggregation with results equivalent to the existing commands.
- **FR-002**: The service MUST provide a health check indicating readiness.
- **FR-003**: The service MUST reuse existing domain behavior so command line and HTTP results stay identical, with no duplicated business rules.
- **FR-004**: The service MUST publish a machine-readable API description, keep a committed copy, and fail continuous checks when they differ or the description is invalid.
- **FR-005**: The service MUST return errors in a standard problem-details form with stable codes mapped from existing error codes, with sensitive details removed.
- **FR-006**: The service MUST NOT return full or unfiltered frames, and MUST only return privacy-screened crops.
- **FR-007**: The service MUST require the same explicit opt-in for `ask` as the command line and MUST never transmit crops externally without it.
- **FR-008**: The service MUST bind to the local machine only by default, and MUST require an API key for any non-local exposure.
- **FR-009**: The service MUST restrict file-system inputs and outputs to the same permitted locations and validation as the command line.
- **FR-010**: The service MUST support starting ingestion and indexing as background jobs that return a job identifier immediately and expose status and run report.
- **FR-011**: Job outcomes MUST use the same success/partial/failure categories as command-line exit codes.
- **FR-012**: The service MUST paginate list responses with a documented default and maximum page size.
- **FR-013**: The API MUST be versioned in its path so future breaking changes can coexist.
- **FR-014**: API documentation MUST state that species confidence and search similarity are not biological probabilities and that visits require owner-reviewed groups.
- **FR-015**: Configuration precedence MUST be request, then environment, then built-in default, with every new setting listed in the environment-variable inventory.
- **FR-016**: Models MUST be loaded once and reused across requests, and the service MUST run a single worker by default.

### Key Entities

- **Crop**: An indexed, privacy-screened bird image with metadata, species labels and similarity context.
- **Run**: A recorded ingestion, indexing or evaluation execution with its report.
- **Visit**: An aggregation of crops from explicit owner-reviewed groups.
- **Job**: A background execution of ingestion or indexing with identifier, status, timestamps and report.
- **Question / Answer**: A natural-language query about footage, its opt-in flag, answer and transmission notice.
- **API Key**: A credential required for non-local access.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a reference set of at least 10 search, inspect and visit inputs, 100% of HTTP results match command-line results.
- **SC-002**: A developer can generate a working client from the published description and complete a search in under 15 minutes.
- **SC-003**: 100% of failed requests in the test suite return a standard problem-details error with no filesystem paths or secrets.
- **SC-004**: Zero crops or frames are transmitted externally, and zero full frames returned, in tests without explicit opt-in or via any endpoint.
- **SC-005**: Starting a job acknowledges the client within 2 seconds regardless of job duration.
- **SC-006**: Typical search requests return within 3 seconds on the reference machine once the service is warmed up.
- **SC-007**: Continuous checks fail in 100% of cases where the committed API description is stale or invalid.

## Assumptions

- v1 includes read-only endpoints, `ask` (opt-in), and ingestion/indexing jobs; database initialization and evaluation/benchmark endpoints are out of scope for v1 and remain command-line only.
- The service is for a single trusted owner on a local machine or small LAN; multi-user accounts and roles are out of scope.
- A single shared API key is sufficient for non-local access.
- Job state is kept so that status survives a restart at the level of "interrupted" or final report; richer persistence is decided during planning.
- Whether long jobs run in-process or through the existing command line is decided per endpoint during planning, provided results match.
- Existing footage, model assets, labels and reports stay outside the repository.
- New dependencies require approval before being added.
- Related specs: 001 ingestion, 002 embedding, 003 search, 004 classification, 005 ask.
