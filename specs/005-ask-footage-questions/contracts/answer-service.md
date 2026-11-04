# Answer Service Contract

**Status**: Implemented OpenAI Responses API adapter. The provider interface is
internal to the CLI; the user's observable request/output contract is in
[cli.md](cli.md).

## Request boundary

The adapter receives only:

- The question and explicitly supplied filters/context.
- The ordered, limited evidence items returned by local search.
- Selected-item metadata required for provenance and interpretation.
- Image bytes for selected items whose local crop file is readable.

Each item receives a request-local integer index. The prompt labels that index
and states whether the corresponding image was actually supplied. An unavailable
image may retain its metadata, but must not be described as visually inspected.
No source video, full frame, unselected crop, credentials, or private collection
listing may be added to the request.

Images are sent as base64 data URLs in Responses API `input_image` content parts.
Use a finite request timeout. Any payload that exceeds the configured service
limits or timeout fails explicitly; do not silently drop evidence or shorten the
request.

## Structured response

Request a strict JSON-schema response with this logical shape:

```json
{
  "sufficient_evidence": true,
  "answer": "A short answer grounded only in supplied evidence.",
  "insufficient_reason": null,
  "claims": [
    {
      "text": "One independently checkable claim.",
      "evidence_indices": [0]
    }
  ]
}
```

All fields are required by the schema; `answer` and `insufficient_reason` are
nullable. Each claim has text and one or more request-local evidence indices.
For `sufficient_evidence: false`, the answer may be null or a concise statement
of limitation and claims must not be treated as supported.

The system prompt must require the model to:

- Answer only from the supplied image pixels and metadata; do not use general
  knowledge to fill gaps.
- Return explicit insufficiency instead of unsupported claims.
- Cite each distinct claim with one or more supplied evidence indices.
- Avoid asserting universal absence, exact counts, or visit frequency from a
  limited crop set.
- Treat species decisions, confidence, and similarity as suggestions/relevance
  indicators, not verified identity or proof of occurrence.
- Distinguish images actually supplied from metadata-only evidence.

## Response validation

The application validates the response independent of SDK parsing:

1. Require a completed, non-refusal response with valid structured output.
   Refused, incomplete, malformed, or timed-out calls are operational failures.
2. Check the response shape and required fields.
3. Check every evidence index is an integer (not a boolean) within the exact
   supplied evidence array.
4. Resolve valid indices to authoritative local crop/source/frame/capture
   provenance; never display a model-invented ID as a valid citation.
5. Require at least one valid citation for each claim presented as supported.
   If a supposedly supported response has no valid citation or an unsupported
   claim, downgrade the response to an insufficient/unsupported outcome and do
   not present uncited text as fact.
6. Treat `sufficient_evidence: false` as an insufficient-evidence outcome.

Semantic contradiction detection is not guaranteed by structured output. The
prompt and controlled tests must cover obvious safety constraints, while user
guidance must state that semantic accuracy is not established by controlled
contract tests.
