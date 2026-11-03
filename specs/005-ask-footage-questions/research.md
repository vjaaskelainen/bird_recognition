# Research: Ask Questions About Footage

**Date**: 2026-11-03 | **Related**: [spec.md](spec.md), [plan.md](plan.md)

## Decisions

### 1. Reuse deterministic search as the sole evidence selector

- **Decision**: Build an Ask request from the question, selected run, existing
  optional date/lighting/species filters, and an evidence limit defaulting to 5.
  Use the existing search service and its deterministic score-descending,
  crop-ID-ascending result order. Do not implement a second retrieval path or
  alter stored vectors.
- **Rationale**: Search already selects a single compatible run/tagging context,
  applies all filters before limiting, validates stored representations, and
  retains crop/source/frame provenance. Reusing these guarantees keeps Ask
  consistent with the search contract and makes unchanged requests repeatable.
- **Alternatives considered**: Retrieving a top-N set then filtering it would
  omit eligible crops outside that truncated set. A new search or database query
  would duplicate established rules and risk mixing collection contexts.

### 2. Use OpenAI Responses API with bounded selected images

- **Decision**: Use the official OpenAI Python SDK and Responses API with a
  vision-capable model, defaulting to `gpt-4o-mini` and allowing the model to be
  overridden through `BIRD_RECOGNITION_ASK_MODEL`. Pass available selected crops
  as base64 data URLs and pair them with their stable evidence indices and
  selected metadata in the same request. The API key is resolved only from
  `BIRD_RECOGNITION_ASK_API_KEY` in process environment or ignored local `.env`;
  there is no CLI flag for secrets.
- **Rationale**: The Responses API accepts image content parts, supports multiple
  images in one request, and supports strict JSON-schema output for a typed
  response. Inline data URLs avoid extra upload lifecycle and ensure only the
  selected local crop bytes are transmitted. An explicit key variable fits the
  repository's namespaced configuration convention and avoids shell-history
  exposure.
- **Alternatives considered**: Ollama settings already present in `.env.example`
  are for local vision-language testing and do not satisfy the spec's external
  service assumption. A vendor-neutral API layer or multiple providers would add
  configuration and unneeded scope. Direct HTTP via `urllib` avoids a dependency
  but requires duplicating SDK request and response handling.
- **Implementation note**: This plan does not modify dependency manifests.
  Adding the OpenAI SDK and synchronizing the lockfile requires separate
  dependency-change approval. Verify the configured model is available for the
  account when implementing; service rejection is an operational failure, not a
  decline.

### 3. Use a strict claim schema and local citation validation

- **Decision**: Require a JSON object containing an explicit sufficiency flag,
  nullable answer/decline fields, and a list of claims. Each claim contains text
  and evidence indices. Resolve each index only against the exact ordered
  evidence set supplied in that request. Remove invalid references, and do not
  present any claim with no valid citation as supported; an invalid, empty, or
  malformed supported response becomes an unsupported/insufficient outcome.
- **Rationale**: Model-generated IDs or free-form provenance could cite a crop
  from another run or invent a source. Request-local indices are easy to validate
  and then map back to authoritative crop/source/frame/time fields from the
  retrieved result. Strict structured output reduces parsing ambiguity but does
  not replace in-process validation.
- **Alternatives considered**: Treating model prose citations as authoritative
  cannot guarantee that references were supplied. Returning a plain generated
  paragraph and a separate list would not attribute evidence to individual
  claims.

### 4. Distinguish declines from operational failures and restrict claims

- **Decision**: Use four explicit outcome categories: supported answer,
  insufficient evidence, input error, and operational failure. Empty retrieval
  returns insufficient evidence without calling the answer service. An explicit
  model insufficiency is a decline; service refusal, incomplete response,
  malformed response, timeout, or transport failure is operational. Instruct the
  model not to assert universal absence or exact counts/frequency and to treat
  species decisions and scores as suggestions, not proof.
- **Rationale**: This matches the feature's outcome contract and avoids
  disguising infrastructure failures as safe declines. Explicit limits are
  necessary because a small crop sample cannot establish all events or visits.
- **Alternatives considered**: Converting every bad response into a decline
  misleads users about service health. Inferring absence or counts from retrieved
  examples exceeds the evidence available.

### 5. Keep unavailable images visible, but mark what the model received

- **Decision**: Preserve all retrieved evidence and provenance in the result.
  Include metadata for each selected item and image bytes only when the local
  crop is readable; mark image availability in the output and tell the generator
  when it received metadata without pixels. If retrieval is empty, do not call
  the model. The UI/JSON must not imply that an unavailable image was visually
  inspected.
- **Rationale**: Search keeps missing crop files in ranked results to preserve
  provenance. Ask should not erase those records but must accurately report the
  evidence actually transmitted.
- **Alternatives considered**: Dropping unavailable crops would change displayed
  retrieval evidence and lose citations. Reconstructing images from full frames
  would violate the scope and privacy boundary.

### 6. Keep the core offline-testable and avoid persistence changes

- **Decision**: Define a small answer-client protocol and inject it into Ask
  orchestration. Unit tests use fake search results and fake structured
  responses; integration tests remain opt-in for the existing database boundary.
  Add no migration, answer history, model download, or external test call.
- **Rationale**: The constitution requires standard tests to run without network,
  API credentials, or private footage. The feature has no need for durable state.
- **Alternatives considered**: Live API tests in the standard suite would be
  nondeterministic and expose private data. Persisting answers would add schema,
  privacy, and lifecycle requirements absent from the feature.

## Official API references

- [OpenAI Images and vision guide](https://developers.openai.com/api/docs/guides/images-vision):
  image content parts support base64 data URLs and multiple images in one input.
- [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs):
  Responses API supports JSON-schema output; strict schemas require closed
  objects and required properties, with nullable types for optional values.

## Repository findings

- `src/bird_recognition/cli.py` defines argparse commands, dotenv resolution, and
  shared search dispatch/output conventions.
- `src/bird_recognition/embed/search.py` provides deterministic, offline-testable
  `execute_search` and filters before ranking/limit.
- `src/bird_recognition/embed/models.py` defines immutable `SearchRequest`,
  `SearchContext`, `SearchResult`, and `SearchOutcome` records.
- `src/bird_recognition/embed/storage.py` loads a selected run in a read-only
  transaction and retains selected crop paths and provenance.
- `src/bird_recognition/embed/config.py` resolves settings in CLI, process
  environment, `.env`, then default order and sanitizes storage errors.
- `.env.example` is the complete configuration inventory. Any new model/key
  settings must be added there without a real secret.
- `specs/003-search-crops/contracts/cli.md` documents filter semantics, run
  selection, provenance, image availability, and failure/exit distinctions.
- The relevant existing offline tests are under `tests/unit/embed/`; opt-in
  search storage coverage is under `tests/integration/embed/`.
