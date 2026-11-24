"""Transient request, evidence, and outcome contracts for footage questions."""

from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from bird_recognition.embed.config import (
    AskServiceConfiguration,
    validate_local_database_url,
)
from bird_recognition.embed.models import (
    EmbedError,
    EmbedValidationError,
    Lighting,
    SearchContext,
    SearchRequest,
)
from bird_recognition.embed.search import SearchCandidate, SearchModel, SearchStore

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class AskValidationError(ValueError):
    """Raised when a transient Ask request, evidence item, or outcome is invalid."""


class AskOperationalError(EmbedError):
    """Raised when search or answer generation cannot complete safely."""


class AskOutcomeStatus(StrEnum):
    """The four externally meaningful Ask outcomes."""

    SUPPORTED = "supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INPUT_ERROR = "input_error"
    OPERATIONAL_FAILURE = "operational_failure"


@dataclass(frozen=True, slots=True)
class AskRequest:
    """Validated single-turn question and its selected local/service settings."""

    question: str
    run_id: UUID
    database_url: str = field(repr=False)
    model_dir: Path
    service_config: AskServiceConfiguration = field(repr=False)
    start_date: date | None = None
    end_date: date | None = None
    lighting: Lighting | None = None
    species_id: str | None = None
    evidence_limit: int = 5
    output_format: Literal["text", "json"] = "text"

    def __post_init__(self) -> None:
        if not isinstance(self.question, str) or not self.question.strip():
            raise AskValidationError("question must not be blank")
        if not isinstance(self.run_id, UUID):
            raise AskValidationError("run ID must be a UUID")
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise AskValidationError("database URL must not be blank")
        database_url = self.database_url.strip()
        try:
            validate_local_database_url(database_url)
        except EmbedValidationError:
            raise AskValidationError(
                "database URL must target a local PostgreSQL service"
            ) from None
        object.__setattr__(self, "database_url", database_url)
        if not isinstance(self.model_dir, Path):
            raise AskValidationError("model directory must be a local path")
        if not isinstance(self.service_config, AskServiceConfiguration):
            raise AskValidationError("answer-service configuration is required")
        for name in ("start_date", "end_date"):
            value = getattr(self, name)
            if value is not None and type(value) is not date:
                raise AskValidationError(f"{name.replace('_', ' ')} must be a date")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise AskValidationError("start date must not be after end date")
        if self.lighting is not None and (
            not isinstance(self.lighting, Lighting) or self.lighting is Lighting.UNKNOWN
        ):
            raise AskValidationError("lighting filter must be day or night")
        if self.species_id is not None and (
            not isinstance(self.species_id, str) or not self.species_id.strip()
        ):
            raise AskValidationError("species ID filter must not be blank")
        if type(self.evidence_limit) is not int or self.evidence_limit <= 0:
            raise AskValidationError("evidence limit must be a positive whole number")
        if self.output_format not in ("text", "json"):
            raise AskValidationError("output format must be text or json")


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """One selected crop with request-local identity and authoritative provenance."""

    evidence_index: int
    crop_id: str
    snapshot_id: str
    representation_id: UUID
    decision_id: UUID
    source_id: str
    source_video: str
    frame_number: int
    elapsed_seconds: float
    capture_time: str | None
    capture_timezone: str | None
    lighting: Lighting
    species_id: str | None
    species_confidence: float | None
    detection_confidence: float
    similarity: float
    image_status: Literal["available", "unavailable"]
    image_bytes: bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.evidence_index) is not int or self.evidence_index < 0:
            raise AskValidationError("evidence index must be a non-negative integer")
        for name in ("crop_id", "source_id", "source_video"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise AskValidationError(f"{name.replace('_', ' ')} must not be blank")
        if not isinstance(self.snapshot_id, str) or not _SHA256_PATTERN.fullmatch(
            self.snapshot_id
        ):
            raise AskValidationError("snapshot ID must be a lowercase SHA-256 digest")
        if not isinstance(self.representation_id, UUID) or not isinstance(
            self.decision_id, UUID
        ):
            raise AskValidationError("representation and decision IDs must be UUIDs")
        if type(self.frame_number) is not int or self.frame_number < 0:
            raise AskValidationError("frame number must be a non-negative integer")
        if (
            isinstance(self.elapsed_seconds, bool)
            or not isinstance(self.elapsed_seconds, (int, float))
            or not math.isfinite(self.elapsed_seconds)
            or self.elapsed_seconds < 0
        ):
            raise AskValidationError("elapsed time must be finite and non-negative")
        for name in ("capture_time", "capture_timezone"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise AskValidationError(f"{name.replace('_', ' ')} must not be blank")
        if not isinstance(self.lighting, Lighting):
            raise AskValidationError("lighting must be a Lighting value")
        if self.species_id is not None and (
            not isinstance(self.species_id, str) or not self.species_id.strip()
        ):
            raise AskValidationError("species ID must not be blank")
        if self.species_confidence is not None and (
            isinstance(self.species_confidence, bool)
            or not isinstance(self.species_confidence, (int, float))
            or not math.isfinite(self.species_confidence)
            or not 0 <= self.species_confidence <= 1
        ):
            raise AskValidationError("species confidence must be within [0, 1]")
        if (
            isinstance(self.detection_confidence, bool)
            or not isinstance(self.detection_confidence, (int, float))
            or not math.isfinite(self.detection_confidence)
            or not 0 <= self.detection_confidence <= 1
        ):
            raise AskValidationError("detection confidence must be within [0, 1]")
        if (
            isinstance(self.similarity, bool)
            or not isinstance(self.similarity, (int, float))
            or not math.isfinite(self.similarity)
            or not -1 <= self.similarity <= 1
        ):
            raise AskValidationError("similarity must be finite and within [-1, 1]")
        if self.image_status not in ("available", "unavailable"):
            raise AskValidationError("image status must be available or unavailable")
        if self.image_status == "available" and (
            not isinstance(self.image_bytes, bytes) or not self.image_bytes
        ):
            raise AskValidationError("available evidence must include image bytes")
        if self.image_status == "unavailable" and self.image_bytes is not None:
            raise AskValidationError("unavailable evidence cannot include image bytes")


@dataclass(frozen=True, slots=True)
class GeneratedClaim:
    """Untrusted model claim with request-local evidence indices."""

    text: str
    evidence_indices: tuple[int, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise AskValidationError("claim text must not be blank")
        if not isinstance(self.evidence_indices, tuple) or not self.evidence_indices:
            raise AskValidationError("claim must cite at least one evidence item")
        if any(type(index) is not int or index < 0 for index in self.evidence_indices):
            raise AskValidationError("evidence indices must be non-negative integers")
        if len(set(self.evidence_indices)) != len(self.evidence_indices):
            raise AskValidationError("evidence indices must be unique")


@dataclass(frozen=True, slots=True)
class Citation:
    """Application-resolved citation to selected crop provenance."""

    evidence_index: int
    crop_id: str
    source_video: str
    frame_number: int
    capture_time: str | None

    def __post_init__(self) -> None:
        if type(self.evidence_index) is not int or self.evidence_index < 0:
            raise AskValidationError("citation evidence index must be non-negative")
        if not isinstance(self.crop_id, str) or not self.crop_id.strip():
            raise AskValidationError("citation crop ID must not be blank")
        if not isinstance(self.source_video, str) or not self.source_video.strip():
            raise AskValidationError("citation source video must not be blank")
        if type(self.frame_number) is not int or self.frame_number < 0:
            raise AskValidationError("citation frame number must be non-negative")
        if self.capture_time is not None and (
            not isinstance(self.capture_time, str) or not self.capture_time.strip()
        ):
            raise AskValidationError("citation capture time must not be blank")

    @classmethod
    def from_evidence(cls, evidence: EvidenceItem) -> Citation:
        """Resolve public citation fields from one authoritative evidence item."""
        return cls(
            evidence_index=evidence.evidence_index,
            crop_id=evidence.crop_id,
            source_video=evidence.source_video,
            frame_number=evidence.frame_number,
            capture_time=evidence.capture_time,
        )


@dataclass(frozen=True, slots=True)
class SupportedClaim:
    """Claim ready for display with locally resolved citations."""

    text: str
    citations: tuple[Citation, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise AskValidationError("claim text must not be blank")
        if not isinstance(self.citations, tuple) or not self.citations:
            raise AskValidationError(
                "supported claim must include at least one citation"
            )
        if any(not isinstance(citation, Citation) for citation in self.citations):
            raise AskValidationError("supported claim citations are invalid")
        indices = tuple(citation.evidence_index for citation in self.citations)
        if len(set(indices)) != len(indices):
            raise AskValidationError("claim citations must be unique")


@dataclass(frozen=True, slots=True)
class AskOutcome:
    """Validated transient result that distinguishes support, decline, and failures."""

    status: AskOutcomeStatus
    request: AskRequest | None
    evidence: tuple[EvidenceItem, ...] = ()
    claims: tuple[SupportedClaim, ...] = ()
    reason: str | None = None
    context: SearchContext | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, AskOutcomeStatus):
            raise AskValidationError("outcome status is invalid")
        if self.request is not None and not isinstance(self.request, AskRequest):
            raise AskValidationError("outcome request is invalid")
        if self.context is not None and not isinstance(self.context, SearchContext):
            raise AskValidationError("outcome search context is invalid")
        if (
            self.context is not None
            and self.request is not None
            and self.context.run_id != self.request.run_id
        ):
            raise AskValidationError("outcome context does not match its request")
        if not isinstance(self.evidence, tuple) or any(
            not isinstance(item, EvidenceItem) for item in self.evidence
        ):
            raise AskValidationError("outcome evidence items are invalid")
        if not isinstance(self.claims, tuple) or any(
            not isinstance(claim, SupportedClaim) for claim in self.claims
        ):
            raise AskValidationError("outcome claims are invalid")
        expected_indices = tuple(range(len(self.evidence)))
        actual_indices = tuple(item.evidence_index for item in self.evidence)
        if actual_indices != expected_indices:
            raise AskValidationError(
                "outcome evidence indices must be ordered from zero"
            )
        if self.evidence and self.request is None:
            raise AskValidationError("outcome evidence requires its request")
        if self.status is AskOutcomeStatus.SUPPORTED:
            if self.request is None:
                raise AskValidationError("supported outcome requires its request")
            if not self.claims:
                raise AskValidationError(
                    "supported outcome must include at least one claim"
                )
            if self.reason is not None:
                raise AskValidationError(
                    "supported outcome cannot include a decline reason"
                )
            evidence_by_index = {item.evidence_index: item for item in self.evidence}
            for claim in self.claims:
                for citation in claim.citations:
                    item = evidence_by_index.get(citation.evidence_index)
                    if item is None or citation != Citation.from_evidence(item):
                        raise AskValidationError(
                            "citation does not match selected evidence"
                        )
        else:
            if self.claims:
                raise AskValidationError("non-supported outcome cannot include claims")
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise AskValidationError("outcome must include a nonblank reason")
            if (
                self.status is AskOutcomeStatus.INSUFFICIENT_EVIDENCE
                and self.request is None
            ):
                raise AskValidationError(
                    "insufficient-evidence outcome requires its request"
                )


class AskAnswerClient(Protocol):
    """Boundary for one structured answer-service request."""

    def generate(self, question: str, evidence: tuple[EvidenceItem, ...]) -> str:
        """Return the service's structured JSON response."""


class OpenAIAnswerClient:
    """Structured vision answer adapter for the OpenAI Responses API."""

    def __init__(self, configuration: AskServiceConfiguration) -> None:
        self._configuration = configuration

    def generate(self, question: str, evidence: tuple[EvidenceItem, ...]) -> str:
        from openai import OpenAI

        try:
            client = OpenAI(
                api_key=self._configuration.api_key,
                timeout=self._configuration.timeout_seconds,
                max_retries=0,
            )
            response = client.responses.create(
                model=self._configuration.model,
                input=build_answer_input_values(question, evidence),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "grounded_footage_answer",
                        "strict": True,
                        "schema": _ANSWER_SCHEMA,
                    }
                },
                timeout=self._configuration.timeout_seconds,
            )
            output = response.output_text
        except AskOperationalError:
            raise
        except Exception:
            raise AskOperationalError("answer service request failed") from None
        if not isinstance(output, str) or not output.strip():
            raise AskOperationalError("answer service returned no structured output")
        return output


_SYSTEM_PROMPT = (
    "Answer only from the supplied image pixels and metadata. Do not use general "
    "knowledge to fill gaps, and decline questions unrelated to the footage. Return "
    "distinct checkable claims and cite every claim with one or more supplied "
    "evidence indices. If the evidence does not support an answer, state that it is "
    "insufficient. Do not make claims of universal absence; report only what was or "
    "was not found in the supplied evidence, and never claim that an event never "
    "occurred anywhere in the footage. Do not provide exact counts or visit frequency "
    "from a limited crop set; decline and explain this limitation when asked. Species "
    "decisions, confidence, and similarity are suggestions or relevance signals, not "
    "proof of identity or occurrence. Do not describe metadata-only evidence as "
    "visually inspected."
)
_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "sufficient_evidence": {"type": "boolean"},
        "answer": {"type": ["string", "null"]},
        "insufficient_reason": {"type": ["string", "null"]},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence_indices": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["text", "evidence_indices"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "sufficient_evidence",
        "answer",
        "insufficient_reason",
        "claims",
    ],
    "additionalProperties": False,
}


def build_search_request(request: AskRequest) -> SearchRequest:
    """Translate an Ask request into the existing search contract."""
    if not isinstance(request, AskRequest):
        raise AskValidationError("ask request is invalid")
    return SearchRequest(
        query=request.question,
        run_id=request.run_id,
        start_date=request.start_date,
        end_date=request.end_date,
        lighting=request.lighting,
        species_id=request.species_id,
        limit=request.evidence_limit,
    )


def build_answer_input(
    request: AskRequest, evidence: tuple[EvidenceItem, ...]
) -> list[dict[str, object]]:
    """Build the system and user messages sent for one selected evidence set."""
    return build_answer_input_values(request.question, evidence)


def build_answer_input_values(
    question: str, evidence: tuple[EvidenceItem, ...]
) -> list[dict[str, object]]:
    """Build Responses API input messages without adding unselected local data."""
    content: list[dict[str, object]] = [
        {
            "type": "input_text",
            "text": f"Question: {question}",
        }
    ]
    for item in evidence:
        metadata = {
            "evidence_index": item.evidence_index,
            "crop_id": item.crop_id,
            "source_video": item.source_video,
            "frame_number": item.frame_number,
            "elapsed_seconds": item.elapsed_seconds,
            "capture_time": item.capture_time,
            "capture_timezone": item.capture_timezone,
            "lighting": item.lighting.value,
            "species_id": item.species_id or "unknown",
            "species_confidence": item.species_confidence,
            "detection_confidence": item.detection_confidence,
            "similarity": item.similarity,
            "image_status": item.image_status,
        }
        content.append(
            {
                "type": "input_text",
                "text": (
                    "Selected evidence metadata (indices are request-local):\n"
                    f"{json.dumps(metadata, ensure_ascii=False, sort_keys=True)}"
                ),
            }
        )
        if item.image_bytes is None:
            continue
        media_type = _image_media_type(item.image_bytes)
        encoded = base64.b64encode(item.image_bytes).decode("ascii")
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:{media_type};base64,{encoded}",
            }
        )
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def execute_ask(
    request: AskRequest,
    model: SearchModel,
    store: SearchStore,
    answer_client: AskAnswerClient | None = None,
    *,
    context: SearchContext | None = None,
    candidates: tuple[SearchCandidate, ...] | None = None,
) -> AskOutcome:
    """Retrieve selected crops, generate structured claims, and resolve citations."""
    from bird_recognition.embed.search import execute_search

    if not isinstance(request, AskRequest):
        raise AskValidationError("ask request is invalid")
    search_request = build_search_request(request)
    search_outcome = execute_search(
        search_request,
        model,
        store,
        context=context,
        candidates=candidates,
    )

    evidence = tuple(
        _evidence_from_result(index, result)
        for index, result in enumerate(search_outcome.results)
    )
    if not evidence:
        return AskOutcome(
            status=AskOutcomeStatus.INSUFFICIENT_EVIDENCE,
            request=request,
            reason="No eligible crops were retrieved for this question.",
            context=search_outcome.context,
        )

    client = answer_client or OpenAIAnswerClient(request.service_config)
    response_text = client.generate(request.question, evidence)
    response = _decode_answer_response(response_text)
    if not response["sufficient_evidence"]:
        reason = response["insufficient_reason"]
        return AskOutcome(
            status=AskOutcomeStatus.INSUFFICIENT_EVIDENCE,
            request=request,
            evidence=evidence,
            reason=(
                reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "The selected evidence is insufficient to answer this question."
            ),
            context=search_outcome.context,
        )

    evidence_by_index = {item.evidence_index: item for item in evidence}
    claims: list[SupportedClaim] = []
    for claim_value in response["claims"]:
        claim_text, claim_indices = _decode_claim(claim_value)
        citations = tuple(
            Citation.from_evidence(evidence_by_index[index])
            for index in dict.fromkeys(claim_indices)
            if index in evidence_by_index
        )
        if not citations:
            return AskOutcome(
                status=AskOutcomeStatus.INSUFFICIENT_EVIDENCE,
                request=request,
                evidence=evidence,
                reason=(
                    "The answer included a claim without a valid citation to "
                    "selected evidence."
                ),
                context=search_outcome.context,
            )
        claims.append(SupportedClaim(text=claim_text, citations=citations))
    if not claims:
        return AskOutcome(
            status=AskOutcomeStatus.INSUFFICIENT_EVIDENCE,
            request=request,
            evidence=evidence,
            reason="The answer did not include any cited claims.",
            context=search_outcome.context,
        )
    return AskOutcome(
        status=AskOutcomeStatus.SUPPORTED,
        request=request,
        evidence=evidence,
        claims=tuple(claims),
        context=search_outcome.context,
    )


def _evidence_from_result(index: int, result: object) -> EvidenceItem:
    image_bytes: bytes | None = None
    image_status: Literal["available", "unavailable"] = "unavailable"
    if result.image_status == "available":
        try:
            image_bytes = result.crop_path.read_bytes()
        except OSError:
            image_bytes = None
        if image_bytes:
            image_status = "available"
        else:
            image_bytes = None
    return EvidenceItem(
        evidence_index=index,
        crop_id=result.crop_id,
        snapshot_id=result.snapshot_id,
        representation_id=result.representation_id,
        decision_id=result.decision_id,
        source_id=result.source_id,
        source_video=result.source_video,
        frame_number=result.frame_number,
        elapsed_seconds=result.elapsed_seconds,
        capture_time=result.capture_time,
        capture_timezone=result.capture_timezone,
        lighting=result.lighting,
        species_id=result.assigned_species_id,
        species_confidence=result.species_confidence,
        detection_confidence=result.detection_confidence,
        similarity=result.similarity,
        image_status=image_status,
        image_bytes=image_bytes,
    )


def _image_media_type(image: bytes) -> str:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        return "image/webp"
    raise AskOperationalError("selected crop image has an unsupported format")


def _decode_answer_response(value: object) -> dict[str, object]:
    try:
        response = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError, TypeError:
        raise AskOperationalError(
            "answer service returned malformed structured output"
        ) from None
    if (
        not isinstance(response, dict)
        or set(response)
        != {"sufficient_evidence", "answer", "insufficient_reason", "claims"}
        or type(response["sufficient_evidence"]) is not bool
        or response["answer"] is not None
        and not isinstance(response["answer"], str)
        or response["insufficient_reason"] is not None
        and not isinstance(response["insufficient_reason"], str)
        or not isinstance(response["claims"], list)
    ):
        raise AskOperationalError("answer service returned malformed structured output")
    return response


def _decode_claim(value: object) -> tuple[str, tuple[int, ...]]:
    if (
        not isinstance(value, dict)
        or set(value) != {"text", "evidence_indices"}
        or not isinstance(value["text"], str)
        or not value["text"].strip()
        or not isinstance(value["evidence_indices"], list)
        or any(type(index) is not int for index in value["evidence_indices"])
    ):
        raise AskOperationalError("answer service returned malformed structured output")
    return value["text"], tuple(value["evidence_indices"])
