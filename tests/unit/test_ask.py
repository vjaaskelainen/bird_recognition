from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from bird_recognition.ask import (
    AskOutcome,
    AskOutcomeStatus,
    AskRequest,
    AskValidationError,
    Citation,
    EvidenceItem,
    GeneratedClaim,
    SupportedClaim,
)
from bird_recognition.embed.config import AskServiceConfiguration
from bird_recognition.embed.models import Lighting


def _request() -> AskRequest:
    return AskRequest(
        question="Which bird appears?",
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        database_url="postgresql://bird@localhost/bird",
        model_dir=Path("models"),
        service_config=AskServiceConfiguration("test-key"),
    )


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_index=0,
        crop_id="crop-1",
        snapshot_id="a" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        source_id="source-1",
        source_video="camera.mp4",
        frame_number=10,
        elapsed_seconds=1.5,
        capture_time=None,
        capture_timezone=None,
        lighting=Lighting.NIGHT,
        species_id=None,
        species_confidence=None,
        detection_confidence=0.8,
        similarity=0.7,
        image_status="available",
        image_bytes=b"crop-image",
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("question", " ", "question must not be blank"),
        ("run_id", "not-a-uuid", "run ID must be a UUID"),
        ("start_date", datetime(2026, 1, 1), "start date must be a date"),
        ("lighting", Lighting.UNKNOWN, "lighting filter must be day or night"),
        ("species_id", " ", "species ID filter must not be blank"),
        ("evidence_limit", True, "evidence limit must be a positive whole number"),
        ("evidence_limit", 0, "evidence limit must be a positive whole number"),
        ("output_format", "xml", "output format must be text or json"),
    ],
)
def test_ask_request_rejects_invalid_fields(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(AskValidationError, match=message):
        replace(_request(), **{field: value})


def test_ask_request_rejects_reversed_date_bounds() -> None:
    with pytest.raises(
        AskValidationError, match="start date must not be after end date"
    ):
        replace(_request(), start_date=date(2026, 2, 1), end_date=date(2026, 1, 1))


def test_ask_request_repr_does_not_expose_credentials_or_database_url() -> None:
    request = _request()

    assert "test-key" not in repr(request)
    assert request.database_url not in repr(request)


def test_ask_request_rejects_remote_database_without_echoing_host() -> None:
    with pytest.raises(
        AskValidationError,
        match="database URL must target a local PostgreSQL service",
    ) as error:
        replace(_request(), database_url="postgresql://bird@remote.example/bird")

    assert "remote.example" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("evidence_index", True, "evidence index must be a non-negative integer"),
        ("frame_number", -1, "frame number must be a non-negative integer"),
        ("elapsed_seconds", float("nan"), "elapsed time must be finite"),
        ("similarity", float("inf"), "similarity must be finite"),
        ("detection_confidence", 1.1, "detection confidence must be within"),
        ("image_bytes", None, "available evidence must include image bytes"),
        (
            "image_status",
            "unavailable",
            "unavailable evidence cannot include image bytes",
        ),
    ],
)
def test_evidence_item_rejects_invalid_values(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(AskValidationError, match=message):
        replace(_evidence(), **{field: value})


def test_generated_claim_rejects_empty_or_invalid_evidence_indices() -> None:
    with pytest.raises(
        AskValidationError, match="must cite at least one evidence item"
    ):
        GeneratedClaim("A bird appears", ())

    with pytest.raises(AskValidationError, match="non-negative integers"):
        GeneratedClaim("A bird appears", (True,))


def test_supported_outcome_requires_authoritative_citations() -> None:
    request = _request()
    evidence = _evidence()
    citation = Citation.from_evidence(evidence)
    claim = SupportedClaim("A bird appears", (citation,))

    outcome = AskOutcome(
        status=AskOutcomeStatus.SUPPORTED,
        request=request,
        evidence=(evidence,),
        claims=(claim,),
    )

    assert outcome.claims[0].citations[0] == citation

    fabricated = replace(citation, crop_id="other-crop")
    with pytest.raises(
        AskValidationError, match="citation does not match selected evidence"
    ):
        AskOutcome(
            status=AskOutcomeStatus.SUPPORTED,
            request=request,
            evidence=(evidence,),
            claims=(SupportedClaim("A bird appears", (fabricated,)),),
        )


def test_ask_outcome_rejects_supported_claim_without_citations() -> None:
    with pytest.raises(AskValidationError, match="must include at least one claim"):
        AskOutcome(
            status=AskOutcomeStatus.SUPPORTED,
            request=_request(),
            evidence=(_evidence(),),
        )

    with pytest.raises(AskValidationError, match="must include a nonblank reason"):
        AskOutcome(
            status=AskOutcomeStatus.INSUFFICIENT_EVIDENCE,
            request=_request(),
            evidence=(_evidence(),),
        )
