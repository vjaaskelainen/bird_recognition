from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from bird_recognition.ask import (
    AskOutcome,
    AskOutcomeStatus,
    AskRequest,
    Citation,
    EvidenceItem,
    SupportedClaim,
)
from bird_recognition.cli import (
    _ask_payload,
    _build_parser,
    _render_ask_outcome,
    main,
)
from bird_recognition.embed.config import AskServiceConfiguration
from bird_recognition.embed.models import Lighting, SearchContext, SearchRequest


def _outcome() -> AskOutcome:
    request = AskRequest(
        question="Which bird appears?",
        run_id=UUID("00000000-0000-0000-0000-000000000001"),
        database_url="postgresql://bird@localhost/bird",
        model_dir=Path("models"),
        service_config=AskServiceConfiguration("test-key"),
    )
    evidence = EvidenceItem(
        evidence_index=0,
        crop_id="crop-1",
        snapshot_id="a" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        source_id="source-1",
        source_video="camera.mp4",
        frame_number=10,
        elapsed_seconds=1.5,
        capture_time="2026-10-25T22:00:00",
        capture_timezone=None,
        lighting=Lighting.NIGHT,
        species_id="bird",
        species_confidence=0.8,
        detection_confidence=0.9,
        similarity=0.75,
        image_status="available",
        image_bytes=b"crop-image",
    )
    context = SearchContext(
        run_id=request.run_id,
        model_fingerprint="b" * 64,
        config_fingerprint="c" * 64,
        candidate_set_fingerprint="d" * 64,
        candidate_ids=("bird",),
        selected_crop_ids=("crop-1",),
    )
    return AskOutcome(
        status=AskOutcomeStatus.SUPPORTED,
        request=request,
        evidence=(evidence,),
        claims=(
            SupportedClaim(
                "A bird appears.",
                (Citation.from_evidence(evidence),),
            ),
        ),
        context=context,
    )


def _declined_outcome() -> AskOutcome:
    outcome = _outcome()
    return AskOutcome(
        status=AskOutcomeStatus.INSUFFICIENT_EVIDENCE,
        request=outcome.request,
        evidence=outcome.evidence,
        reason="The retrieved evidence does not establish an answer.",
        context=outcome.context,
    )


def _filtered_unavailable_outcome() -> AskOutcome:
    outcome = _outcome()
    request = replace(
        outcome.request,
        start_date=date(2026, 10, 25),
        end_date=date(2026, 10, 26),
        lighting=Lighting.NIGHT,
        species_id="bird",
        evidence_limit=2,
    )
    evidence = replace(
        outcome.evidence[0],
        capture_time=None,
        image_status="unavailable",
        image_bytes=None,
    )
    return AskOutcome(
        status=AskOutcomeStatus.SUPPORTED,
        request=request,
        evidence=(evidence,),
        claims=(
            SupportedClaim(
                outcome.claims[0].text,
                (Citation.from_evidence(evidence),),
            ),
        ),
        context=outcome.context,
    )


def test_ask_parser_accepts_story_one_question_and_run_options() -> None:
    arguments = _build_parser().parse_args(
        [
            "ask",
            "Which bird appears?",
            "--run-id",
            "00000000-0000-0000-0000-000000000001",
        ]
    )

    assert arguments.command == "ask"
    assert arguments.question == "Which bird appears?"
    assert arguments.run_id == "00000000-0000-0000-0000-000000000001"
    assert arguments.limit == 5


def test_ask_parser_accepts_story_three_metadata_filters() -> None:
    arguments = _build_parser().parse_args(
        [
            "ask",
            "Which bird appears?",
            "--run-id",
            "00000000-0000-0000-0000-000000000001",
            "--start-date",
            "2026-10-25",
            "--end-date",
            "2026-10-26",
            "--lighting",
            "night",
            "--species-id",
            "bird",
            "--limit",
            "2",
        ]
    )

    assert arguments.start_date == date(2026, 10, 25)
    assert arguments.end_date == date(2026, 10, 26)
    assert arguments.lighting == "night"
    assert arguments.species_id == "bird"
    assert arguments.limit == 2


@pytest.mark.parametrize("value", ["2026-2-01", "2026-02-30"])
def test_ask_parser_rejects_non_strict_or_invalid_filter_dates(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        _build_parser().parse_args(
            [
                "ask",
                "Which bird appears?",
                "--run-id",
                "00000000-0000-0000-0000-000000000001",
                "--start-date",
                value,
            ]
        )

    assert error.value.code == 2
    assert "date" in capsys.readouterr().err


def test_ask_json_output_includes_claim_citation_and_authoritative_provenance(
    capsys,
) -> None:
    outcome = _outcome()
    payload = _ask_payload(outcome)

    assert payload["schema_version"] == 1
    assert payload["status"] == "answered"
    assert payload["claims"][0]["citations"][0] == {
        "evidence_index": 0,
        "crop_id": "crop-1",
        "source_video": "camera.mp4",
        "frame_number": 10,
        "capture_time": "2026-10-25T22:00:00",
    }
    _render_ask_outcome(outcome, json_output=True)
    rendered = json.loads(capsys.readouterr().out)
    assert rendered == payload


def test_ask_json_output_includes_filter_and_evidence_metadata() -> None:
    payload = _ask_payload(_filtered_unavailable_outcome())

    assert payload["question"] == "Which bird appears?"
    assert payload["filters"] == {
        "start_date": "2026-10-25",
        "end_date": "2026-10-26",
        "lighting": "night",
        "species_id": "bird",
    }
    assert payload["requested_limit"] == 2
    assert payload["evidence_count"] == 1
    assert payload["context"] == {
        "run_id": "00000000-0000-0000-0000-000000000001",
        "model_fingerprint": "b" * 64,
        "config_fingerprint": "c" * 64,
        "candidate_set_fingerprint": "d" * 64,
    }
    evidence = payload["evidence"][0]
    assert evidence["similarity"] == 0.75
    assert evidence["species"] == {"id": "bird", "confidence": 0.8}
    assert evidence["detection_confidence"] == 0.9
    assert evidence["capture_time"] is None
    assert evidence["image_status"] == "unavailable"


def test_ask_human_output_renders_claim_and_source_frame(capsys) -> None:
    _render_ask_outcome(_outcome(), json_output=False)

    rendered = capsys.readouterr().out
    assert "A bird appears." in rendered
    assert "crop-1" in rendered
    assert "camera.mp4" in rendered
    assert "frame 10" in rendered
    assert "2026-10-25T22:00:00" in rendered


def test_ask_human_output_renders_filters_context_scores_and_missing_metadata(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _render_ask_outcome(_filtered_unavailable_outcome(), json_output=False)

    rendered = capsys.readouterr().out
    assert "Question: Which bird appears?" in rendered
    assert "start=2026-10-25" in rendered
    assert "end=2026-10-26" in rendered
    assert "lighting=night" in rendered
    assert "species=bird" in rendered
    assert "Evidence limit: 2" in rendered
    assert "Evidence items: 1" in rendered
    assert "Model fingerprint: " + "b" * 64 in rendered
    assert "Tagging config fingerprint: " + "c" * 64 in rendered
    assert "Candidate set fingerprint: " + "d" * 64 in rendered
    assert "capture time unknown" in rendered
    assert "image unavailable" in rendered
    assert "Similarity: 0.750000" in rendered
    assert "Species decision: bird; confidence: 0.800000" in rendered
    assert "Detection confidence: 0.900000" in rendered


def test_ask_json_decline_marks_evidence_as_retrieved_but_nonsupporting() -> None:
    payload = _ask_payload(_declined_outcome())

    assert payload["status"] == "insufficient_evidence"
    assert payload["reason"] == "The retrieved evidence does not establish an answer."
    assert payload["claims"] == []
    assert payload["evidence"][0]["support"] == "retrieved_not_supporting"
    assert "citations" not in payload["evidence"][0]


def test_ask_human_decline_lists_nonsupporting_evidence_without_citations(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _render_ask_outcome(_declined_outcome(), json_output=False)

    rendered = capsys.readouterr().out
    assert "The retrieved evidence does not establish an answer." in rendered
    assert "Retrieved evidence (not supporting an answer)" in rendered
    assert "crop-1" in rendered
    assert "camera.mp4" in rendered
    assert "frame 10" in rendered
    assert "Citation" not in rendered


@pytest.mark.parametrize(
    ("declined", "expected_status"),
    [(False, "answered"), (True, "insufficient_evidence")],
)
def test_ask_dispatch_returns_success_for_supported_or_declined_result(
    declined: bool, expected_status: str, monkeypatch, capsys
) -> None:
    outcome = _declined_outcome() if declined else _outcome()
    store_calls: list[object] = []
    ask_calls: list[AskRequest] = []

    class FakeStore:
        def __init__(self, database_url: str) -> None:
            store_calls.append(("init", database_url))

        def preflight(self, *, read_only: bool = False) -> None:
            store_calls.append(("preflight", read_only))

        def load_search_collection(self, request: object):
            store_calls.append(("search", request))
            return outcome.context, ()

        def close(self) -> None:
            store_calls.append(("close",))

    monkeypatch.setenv("BIRD_RECOGNITION_ASK_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules,
        "bird_recognition.embed.storage",
        SimpleNamespace(PgVectorStore=FakeStore, initialize_database=lambda _: None),
    )
    monkeypatch.setitem(
        sys.modules,
        "bird_recognition.embed.bioclip",
        SimpleNamespace(load_bioclip=lambda *_args, **_kwargs: object()),
    )
    monkeypatch.setattr(
        "bird_recognition.ask.execute_ask",
        lambda request, *_args, **_kwargs: ask_calls.append(request) or outcome,
    )

    exit_code = main(
        [
            "ask",
            "Which bird appears?",
            "--run-id",
            "00000000-0000-0000-0000-000000000001",
            "--database-url",
            "postgresql://bird@localhost/bird",
            "--model-dir",
            "models",
            "--start-date",
            "2026-10-25",
            "--end-date",
            "2026-10-26",
            "--lighting",
            "night",
            "--species-id",
            "bird",
            "--limit",
            "2",
            "--json",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["status"] == expected_status
    assert ("preflight", True) in store_calls
    search_call = next(call for call in store_calls if call[0] == "search")
    search_request = search_call[1]
    assert isinstance(search_request, SearchRequest)
    assert search_request.start_date == date(2026, 10, 25)
    assert search_request.end_date == date(2026, 10, 26)
    assert search_request.lighting is Lighting.NIGHT
    assert search_request.species_id == "bird"
    assert search_request.limit == 2
    assert len(ask_calls) == 1
    assert ask_calls[0].start_date == date(2026, 10, 25)
    assert ask_calls[0].end_date == date(2026, 10, 26)
    assert ask_calls[0].lighting is Lighting.NIGHT
    assert ask_calls[0].species_id == "bird"
    assert ask_calls[0].evidence_limit == 2
