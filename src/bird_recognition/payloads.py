"""Stable JSON payload and error helpers shared by the CLI and HTTP service."""

from __future__ import annotations

from typing import Any


def _sanitize_ask_error(message: str, api_key: str | None) -> str:
    from bird_recognition.embed.config import sanitize_error

    sanitized = sanitize_error(message)
    if api_key:
        sanitized = sanitized.replace(api_key, "[credential redacted]")
    return sanitized


def ask_transmission_notice(evidence: tuple[object, ...]) -> str:
    """Return the disclosure text for the exact evidence selected for transmission."""
    items = ", ".join(
        (
            f"{item.crop_id} ("
            f"{'image and selected metadata' if item.image_bytes else 'metadata only'})"
        )
        for item in evidence
    )
    return (
        "Transmission notice: the question and selected evidence will be sent to "
        "the configured external "
        f"answer service: {items}. Full source videos and unselected crops "
        "are not sent."
    )


def _preflight_code(error: Exception) -> str:
    message = str(error).casefold()
    if "writer_busy" in message or "writer busy" in message:
        return "writer_busy"
    if "vector" in message:
        return "vector_unavailable"
    if "schema" in message:
        return "schema_mismatch"
    if "database" in message or "postgres" in message:
        return "database_unavailable"
    if "threshold" in message:
        return "invalid_threshold"
    if "model" in message or "bioclip" in message:
        return "invalid_model"
    if "species" in message or "candidate" in message:
        return "invalid_species"
    if "manifest" in message:
        return "invalid_manifest"
    return "invalid_selection"


def _search_failure_code(error: Exception) -> str:
    message = str(error).casefold()
    if "query must" in message or "search query" in message:
        return "invalid_query"
    if "limit" in message:
        return "invalid_limit"
    if "date" in message:
        return "invalid_date"
    if "lighting" in message:
        return "invalid_lighting"
    if "query embedding" in message:
        return "query_embedding_failed"
    if "model fingerprint" in message:
        return "model_mismatch"
    if "representation" in message:
        return "incompatible_representation"
    if "vector" in message or "similarity" in message:
        return "invalid_numeric_result"
    if "schema" in message:
        return "schema_mismatch"
    if "database" in message or "postgres" in message:
        return "database_unavailable"
    if "model" in message or "bioclip" in message:
        return "model_unavailable"
    if "species" in message or "candidate" in message:
        return "invalid_species"
    if "run" in message or "context" in message:
        return "invalid_selection"
    return "invalid_search"


def _search_payload(outcome: Any) -> dict[str, object]:
    request = outcome.request
    context = outcome.context
    return {
        "schema_version": 1,
        "status": "searched",
        "query": request.query,
        "filters": {
            "start_date": (
                request.start_date.isoformat()
                if request.start_date is not None
                else None
            ),
            "end_date": request.end_date.isoformat() if request.end_date else None,
            "lighting": request.lighting.value
            if request.lighting is not None
            else None,
            "species_id": request.species_id,
        },
        "requested_limit": request.limit,
        "returned_count": outcome.returned_count,
        "context": {
            "run_id": str(context.run_id),
            "model_fingerprint": context.model_fingerprint,
            "config_fingerprint": context.config_fingerprint,
            "candidate_set_fingerprint": context.candidate_set_fingerprint,
        },
        "score": {
            "name": "cosine_similarity",
            "range": [-1, 1],
            "higher_is_more_similar": True,
            "interpretation": "relative retrieval relevance; not a probability",
        },
        "warnings": list(outcome.warnings),
        "results": [
            {
                "rank": result.rank,
                "similarity": result.similarity,
                "crop_id": result.crop_id,
                "snapshot_id": result.snapshot_id,
                "representation_id": str(result.representation_id),
                "decision_id": str(result.decision_id),
                "crop_path": str(result.crop_path),
                "image_status": result.image_status,
                "capture": {
                    "time": result.capture_time,
                    "timezone": result.capture_timezone,
                },
                "lighting": result.lighting.value,
                "detection": {
                    "id": result.detection_id,
                    "category": result.detection_category,
                    "confidence": result.detection_confidence,
                    "box_normalized": list(result.detection_box_normalized),
                    "crop_box_pixels": list(result.crop_box_pixels),
                    "frame_width": result.frame_width,
                    "frame_height": result.frame_height,
                },
                "species": {
                    "assigned_species_id": result.assigned_species_id or "unknown",
                    "confidence": result.species_confidence,
                    "config_fingerprint": result.config_fingerprint,
                },
                "source": {
                    "source_id": result.source_id,
                    "video": result.source_video,
                    "original_path": result.source_original_path,
                    "frame_number": result.frame_number,
                    "elapsed_seconds": result.elapsed_seconds,
                },
            }
            for result in outcome.results
        ],
    }


def _ask_payload(outcome: Any) -> dict[str, object]:
    request = outcome.request
    context = outcome.context
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": (
            "answered"
            if outcome.status.value == "supported"
            else "insufficient_evidence"
        ),
        "question": request.question,
        "filters": {
            "start_date": (
                request.start_date.isoformat()
                if request.start_date is not None
                else None
            ),
            "end_date": request.end_date.isoformat() if request.end_date else None,
            "lighting": request.lighting.value
            if request.lighting is not None
            else None,
            "species_id": request.species_id,
        },
        "requested_limit": request.evidence_limit,
        "evidence_count": len(outcome.evidence),
        "context": {
            "run_id": str(request.run_id),
            "model_fingerprint": (
                context.model_fingerprint if context is not None else None
            ),
            "config_fingerprint": (
                context.config_fingerprint if context is not None else None
            ),
            "candidate_set_fingerprint": (
                context.candidate_set_fingerprint if context is not None else None
            ),
        },
        "claims": [
            {
                "text": claim.text,
                "citations": [
                    {
                        "evidence_index": citation.evidence_index,
                        "crop_id": citation.crop_id,
                        "source_video": citation.source_video,
                        "frame_number": citation.frame_number,
                        "capture_time": citation.capture_time,
                    }
                    for citation in claim.citations
                ],
            }
            for claim in outcome.claims
        ],
        "evidence": [
            {
                "evidence_index": item.evidence_index,
                "crop_id": item.crop_id,
                "source_id": item.source_id,
                "support": (
                    "retrieved_not_supporting"
                    if outcome.status.value == "insufficient_evidence"
                    else "selected"
                ),
                "image_status": item.image_status,
                "source_video": item.source_video,
                "frame_number": item.frame_number,
                "elapsed_seconds": item.elapsed_seconds,
                "capture_time": item.capture_time,
                "capture_timezone": item.capture_timezone,
                "lighting": item.lighting.value,
                "similarity": item.similarity,
                "species": {
                    "id": item.species_id or "unknown",
                    "confidence": item.species_confidence,
                },
                "detection_confidence": item.detection_confidence,
            }
            for item in outcome.evidence
        ],
    }
    if outcome.reason is not None:
        payload["reason"] = outcome.reason
    return payload
