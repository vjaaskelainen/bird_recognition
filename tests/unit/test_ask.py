from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from bird_recognition.ask import (
    AskOperationalError,
    AskOutcome,
    AskOutcomeStatus,
    AskRequest,
    AskValidationError,
    Citation,
    EvidenceItem,
    GeneratedClaim,
    OpenAIAnswerClient,
    SupportedClaim,
    build_answer_input,
    build_search_request,
    execute_ask,
)
from bird_recognition.embed.config import AskServiceConfiguration
from bird_recognition.embed.models import Lighting, SearchContext, SearchResult
from bird_recognition.embed.search import SearchCandidate


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
        image_bytes=b"\x89PNG\r\n\x1a\ncrop-image",
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


def test_build_search_request_preserves_question_filters_and_limit() -> None:
    request = replace(
        _request(),
        start_date=date(2026, 10, 25),
        end_date=date(2026, 10, 26),
        lighting=Lighting.NIGHT,
        species_id="bird",
        evidence_limit=2,
    )

    search_request = build_search_request(request)

    assert search_request.query == request.question
    assert search_request.run_id == request.run_id
    assert search_request.start_date == request.start_date
    assert search_request.end_date == request.end_date
    assert search_request.lighting is Lighting.NIGHT
    assert search_request.species_id == "bird"
    assert search_request.limit == 2


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


def _search_context(crop_ids: tuple[str, ...] = ("crop-1",)) -> SearchContext:
    return SearchContext(
        run_id=_request().run_id,
        model_fingerprint="a" * 64,
        config_fingerprint="b" * 64,
        candidate_set_fingerprint="c" * 64,
        candidate_ids=("bird",),
        selected_crop_ids=crop_ids,
        model_input_view="fit-pad-v1",
    )


def _search_result(crop_path: Path) -> SearchResult:
    return SearchResult(
        rank=1,
        similarity=0.75,
        crop_id="crop-1",
        snapshot_id="d" * 64,
        representation_id=UUID("00000000-0000-0000-0000-000000000002"),
        decision_id=UUID("00000000-0000-0000-0000-000000000003"),
        assigned_species_id="bird",
        species_confidence=0.8,
        crop_path=crop_path,
        image_status="available",
        source_id="source-1",
        source_video="camera.mp4",
        source_original_path="recordings/camera.mp4",
        frame_number=10,
        elapsed_seconds=1.5,
        capture_time="2026-10-25T22:00:00",
        capture_timezone="Europe/Helsinki",
        lighting=Lighting.NIGHT,
        detection_id="detection-1",
        detection_category="animal",
        detection_confidence=0.9,
        detection_box_normalized=(0.1, 0.2, 0.5, 0.6),
        crop_box_pixels=(10, 20, 50, 60),
        frame_width=100,
        frame_height=100,
        config_fingerprint="b" * 64,
    )


class _AnswerClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, tuple[EvidenceItem, ...]]] = []

    def generate(self, question: str, evidence: tuple[EvidenceItem, ...]) -> str:
        self.calls.append((question, evidence))
        return self.response


def test_build_answer_input_includes_question_metadata_and_selected_image() -> None:
    messages = build_answer_input(_request(), (_evidence(),))
    user_content = messages[1]["content"]

    assert messages[0]["role"] == "system"
    assert (
        "Answer only from the supplied image pixels and metadata"
        in messages[0]["content"]
    )
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "input_text"
    assert "Which bird appears?" in user_content[0]["text"]
    assert user_content[1]["type"] == "input_text"
    assert '"evidence_index": 0' in user_content[1]["text"]
    assert "camera.mp4" in user_content[1]["text"]
    assert "frame_number" in user_content[1]["text"]
    assert user_content[2]["type"] == "input_image"
    assert user_content[2]["image_url"].startswith("data:image/")


def test_build_answer_input_constrains_absence_count_and_unrelated_questions() -> None:
    messages = build_answer_input(
        replace(_request(), question="Did a fox ever visit, and how often?"),
        (_evidence(),),
    )

    system_prompt = messages[0]["content"]
    assert "unrelated to the footage" in system_prompt
    assert "general knowledge" in system_prompt
    assert "universal absence" in system_prompt
    assert "exact counts or visit frequency" in system_prompt
    assert "Species decisions, confidence, and similarity" in system_prompt


def test_openai_adapter_uses_strict_schema_and_finite_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class Responses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            captured["request"] = kwargs
            return SimpleNamespace(output_text='{"structured":true}')

    class FakeOpenAI:
        def __init__(self, *, api_key: str, timeout: float, max_retries: int) -> None:
            captured["api_key"] = api_key
            captured["timeout"] = timeout
            captured["max_retries"] = max_retries
            self.responses = Responses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    client = OpenAIAnswerClient(_request().service_config)

    assert client.generate("Which bird appears?", (_evidence(),)) == (
        '{"structured":true}'
    )
    request = captured["request"]
    assert captured["api_key"] == "test-key"
    assert captured["timeout"] == 60.0
    assert captured["max_retries"] == 0
    assert request["model"] == "gpt-4o-mini"
    assert request["timeout"] == 60.0
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True


def test_openai_adapter_sanitizes_service_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Responses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            raise RuntimeError("credential leaked: test-key")

    class FakeOpenAI:
        def __init__(self, **_: object) -> None:
            self.responses = Responses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    with pytest.raises(
        AskOperationalError, match="answer service request failed"
    ) as exc:
        OpenAIAnswerClient(_request().service_config).generate(
            "Which bird appears?", (_evidence(),)
        )

    assert "test-key" not in str(exc.value)


def test_openai_adapter_reports_timeout_without_disclosing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class APITimeoutError(Exception):
        pass

    class Responses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            raise APITimeoutError("request timed out with test-key")

    class FakeOpenAI:
        def __init__(self, **_: object) -> None:
            self.responses = Responses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    with pytest.raises(AskOperationalError, match="timed out") as exc:
        OpenAIAnswerClient(_request().service_config).generate(
            "Which bird appears?", (_evidence(),)
        )

    assert "test-key" not in str(exc.value)


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (
            SimpleNamespace(status="incomplete", output_text="", output=[]),
            "incomplete",
        ),
        (
            SimpleNamespace(
                status="completed",
                output_text="",
                output=[
                    SimpleNamespace(
                        type="message",
                        content=[SimpleNamespace(type="refusal")],
                    )
                ],
            ),
            "refused",
        ),
    ],
)
def test_openai_adapter_reports_refusal_and_incomplete_responses(
    monkeypatch: pytest.MonkeyPatch, response: SimpleNamespace, message: str
) -> None:
    class Responses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            return response

    class FakeOpenAI:
        def __init__(self, **_: object) -> None:
            self.responses = Responses()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    with pytest.raises(AskOperationalError, match=message):
        OpenAIAnswerClient(_request().service_config).generate(
            "Which bird appears?", (_evidence(),)
        )


def test_execute_ask_resolves_valid_claim_indices_to_selected_provenance(
    tmp_path: Path,
) -> None:
    request = replace(_request(), question="What appears in the crop?")
    context = _search_context()
    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(b"\x89PNG\r\n\x1a\ncrop-image")
    result = _search_result(crop_path)
    candidate = SearchCandidate(result=result, embedding=(1.0,) + (0.0,) * 511)
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, (candidate,)))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": True,
                "answer": "A bird appears.",
                "insufficient_reason": None,
                "claims": [
                    {"text": "A bird appears.", "evidence_indices": [0]},
                    {
                        "text": "The crop was recorded at night.",
                        "evidence_indices": [0],
                    },
                ],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert outcome.status is AskOutcomeStatus.SUPPORTED
    assert outcome.context is context
    assert len(outcome.claims) == 2
    citation = outcome.claims[0].citations[0]
    assert citation == Citation(
        evidence_index=0,
        crop_id="crop-1",
        source_video="camera.mp4",
        frame_number=10,
        capture_time="2026-10-25T22:00:00",
    )
    assert outcome.evidence[0].image_bytes is not None
    assert len(client.calls) == 1


def test_execute_ask_applies_metadata_filters_before_limit_in_stable_order(
    tmp_path: Path,
) -> None:
    request = replace(
        _request(),
        start_date=date(2026, 10, 25),
        end_date=date(2026, 10, 26),
        lighting=Lighting.NIGHT,
        species_id="bird",
        evidence_limit=2,
    )
    context = _search_context(
        ("a-too-early", "b-too-late", "c-day", "d-other", "z-boundary", "y-boundary")
    )
    base_result = _search_result(tmp_path / "missing.png")
    results = (
        replace(base_result, crop_id="a-too-early", capture_time="2026-10-24T23:00:00"),
        replace(base_result, crop_id="b-too-late", capture_time="2026-10-27T23:00:00"),
        replace(
            base_result,
            crop_id="c-day",
            capture_time="2026-10-25T12:00:00",
            lighting=Lighting.DAY,
        ),
        replace(
            base_result,
            crop_id="d-other",
            capture_time="2026-10-25T23:00:00",
            assigned_species_id="owl",
        ),
        replace(
            base_result,
            crop_id="z-boundary",
            capture_time="2026-10-25T23:00:00",
        ),
        replace(
            base_result,
            crop_id="y-boundary",
            capture_time="2026-10-26T23:00:00",
        ),
    )
    candidates = tuple(
        SearchCandidate(result=result, embedding=(1.0,) + (0.0,) * 511)
        for result in results
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, candidates))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": False,
                "answer": None,
                "insufficient_reason": "The evidence is not sufficient.",
                "claims": [],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert [item.crop_id for item in outcome.evidence] == ["y-boundary", "z-boundary"]
    assert [item.image_status for item in outcome.evidence] == [
        "unavailable",
        "unavailable",
    ]
    assert [item.evidence_index for item in outcome.evidence] == [0, 1]
    assert len(client.calls[0][1]) == 2


def test_execute_ask_includes_both_date_boundaries_when_date_filtering_alone(
    tmp_path: Path,
) -> None:
    request = replace(
        _request(),
        start_date=date(2026, 10, 25),
        end_date=date(2026, 10, 26),
    )
    crop_ids = ("before", "start-boundary", "end-boundary", "after", "unknown-time")
    context = _search_context(crop_ids)
    base_result = _search_result(tmp_path / "missing.png")
    results = (
        replace(base_result, crop_id="before", capture_time="2026-10-24T23:59:59"),
        replace(
            base_result,
            crop_id="start-boundary",
            capture_time="2026-10-25T00:00:00",
        ),
        replace(
            base_result,
            crop_id="end-boundary",
            capture_time="2026-10-26T23:59:59",
        ),
        replace(base_result, crop_id="after", capture_time="2026-10-27T00:00:00"),
        replace(base_result, crop_id="unknown-time", capture_time=None),
    )
    candidates = tuple(
        SearchCandidate(result=result, embedding=(1.0,) + (0.0,) * 511)
        for result in results
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, candidates))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": False,
                "answer": None,
                "insufficient_reason": "The evidence is not sufficient.",
                "claims": [],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert [item.crop_id for item in outcome.evidence] == [
        "end-boundary",
        "start-boundary",
    ]


@pytest.mark.parametrize(
    ("field", "filter_value", "matching", "nonmatching"),
    [
        (
            "lighting",
            Lighting.NIGHT,
            {"lighting": Lighting.NIGHT},
            {"lighting": Lighting.DAY},
        ),
        (
            "species_id",
            "bird",
            {"assigned_species_id": "bird"},
            {"assigned_species_id": "owl"},
        ),
        (
            "species_id",
            "unknown",
            {"assigned_species_id": None},
            {"assigned_species_id": "bird"},
        ),
    ],
)
def test_execute_ask_applies_lighting_and_species_filters(
    tmp_path: Path,
    field: str,
    filter_value: object,
    matching: dict[str, object],
    nonmatching: dict[str, object],
) -> None:
    request = replace(_request(), **{field: filter_value}, evidence_limit=5)
    context = _search_context(("matching", "nonmatching"))
    base_result = _search_result(tmp_path / "missing.png")
    candidates = tuple(
        SearchCandidate(
            result=replace(base_result, crop_id=crop_id, **changes),
            embedding=(1.0,) + (0.0,) * 511,
        )
        for crop_id, changes in (
            ("matching", matching),
            ("nonmatching", nonmatching),
        )
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, candidates))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": False,
                "answer": None,
                "insufficient_reason": "The evidence is not sufficient.",
                "claims": [],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert [item.crop_id for item in outcome.evidence] == ["matching"]


def test_execute_ask_discards_invalid_indices_and_downgrades_uncited_claims(
    tmp_path: Path,
) -> None:
    request = _request()
    context = _search_context()
    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(b"\x89PNG\r\n\x1a\ncrop-image")
    result = _search_result(crop_path)
    candidate = SearchCandidate(result=result, embedding=(1.0,) + (0.0,) * 511)
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, (candidate,)))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": True,
                "answer": "Two claims.",
                "insufficient_reason": None,
                "claims": [
                    {"text": "Supported.", "evidence_indices": [0, 7]},
                    {"text": "Unsupported.", "evidence_indices": [99]},
                ],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert outcome.status is AskOutcomeStatus.INSUFFICIENT_EVIDENCE
    assert outcome.claims == ()
    assert outcome.reason


def test_execute_ask_uses_only_valid_indices_from_a_mixed_citation_list(
    tmp_path: Path,
) -> None:
    request = _request()
    context = _search_context()
    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(b"\x89PNG\r\n\x1a\ncrop-image")
    candidate = SearchCandidate(
        result=_search_result(crop_path),
        embedding=(1.0,) + (0.0,) * 511,
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, (candidate,)))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": True,
                "answer": "A bird appears.",
                "insufficient_reason": None,
                "claims": [
                    {"text": "A bird appears.", "evidence_indices": [0, -1, 8]},
                ],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert outcome.status is AskOutcomeStatus.SUPPORTED
    assert [citation.evidence_index for citation in outcome.claims[0].citations] == [0]


def test_execute_ask_does_not_call_answer_client_when_search_is_empty() -> None:
    request = _request()
    context = _search_context(())
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, ()))
    client = _AnswerClient("{}")

    notice_calls: list[tuple[EvidenceItem, ...]] = []
    outcome = execute_ask(
        request,
        model,
        store,
        client,
        before_answer=notice_calls.append,
    )

    assert outcome.status is AskOutcomeStatus.INSUFFICIENT_EVIDENCE
    assert outcome.evidence == ()
    assert outcome.claims == ()
    assert outcome.reason
    assert client.calls == []
    assert notice_calls == []


def test_execute_ask_notifies_before_sending_only_selected_evidence(
    tmp_path: Path,
) -> None:
    request = replace(_request(), evidence_limit=1)
    context = _search_context(("crop-1", "crop-2"))
    crop_path = tmp_path / "missing.png"
    candidate = SearchCandidate(
        result=_search_result(crop_path),
        embedding=(1.0,) + (0.0,) * 511,
    )
    second_candidate = SearchCandidate(
        result=replace(_search_result(crop_path), crop_id="crop-2"),
        embedding=(1.0,) + (0.0,) * 511,
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(
        load_search_collection=lambda _: (context, (candidate, second_candidate))
    )
    events: list[str] = []
    notified_evidence: list[tuple[EvidenceItem, ...]] = []

    class OrderedAnswerClient:
        def generate(self, question: str, evidence: tuple[EvidenceItem, ...]) -> str:
            events.append("answer service")
            assert question == request.question
            assert len(evidence) == 1
            assert evidence[0].image_status == "unavailable"
            assert evidence[0].image_bytes is None
            return json.dumps(
                {
                    "sufficient_evidence": False,
                    "answer": None,
                    "insufficient_reason": "The image is unavailable.",
                    "claims": [],
                }
            )

    def announce(evidence: tuple[EvidenceItem, ...]) -> None:
        events.append("transmission notice")
        notified_evidence.append(evidence)

    outcome = execute_ask(
        request,
        model,
        store,
        OrderedAnswerClient(),
        before_answer=announce,
    )

    assert outcome.status is AskOutcomeStatus.INSUFFICIENT_EVIDENCE
    assert events == ["transmission notice", "answer service"]
    assert len(notified_evidence) == 1
    assert notified_evidence[0][0].evidence_index == 0
    assert notified_evidence[0][0].crop_id == "crop-1"
    assert notified_evidence[0][0].image_status == "unavailable"


@pytest.mark.parametrize("response_text", ["not-json", "{}"])
def test_execute_ask_classifies_malformed_responses_as_operational(
    tmp_path: Path, response_text: str
) -> None:
    request = _request()
    context = _search_context()
    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(b"\x89PNG\r\n\x1a\ncrop-image")
    candidate = SearchCandidate(
        result=_search_result(crop_path),
        embedding=(1.0,) + (0.0,) * 511,
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, (candidate,)))

    with pytest.raises(AskOperationalError, match="malformed structured output"):
        execute_ask(request, model, store, _AnswerClient(response_text))


def test_execute_ask_drops_claims_when_answer_client_declines(
    tmp_path: Path,
) -> None:
    request = _request()
    context = _search_context()
    crop_path = tmp_path / "crop.png"
    crop_path.write_bytes(b"\x89PNG\r\n\x1a\ncrop-image")
    candidate = SearchCandidate(
        result=_search_result(crop_path),
        embedding=(1.0,) + (0.0,) * 511,
    )
    model = SimpleNamespace(
        identity=SimpleNamespace(model_fingerprint=context.model_fingerprint),
        encode_texts=lambda _: ((1.0,) + (0.0,) * 511,),
    )
    store = SimpleNamespace(load_search_collection=lambda _: (context, (candidate,)))
    client = _AnswerClient(
        json.dumps(
            {
                "sufficient_evidence": False,
                "answer": None,
                "insufficient_reason": "The evidence does not establish a visit count.",
                "claims": [{"text": "A fox visited once.", "evidence_indices": [0]}],
            }
        )
    )

    outcome = execute_ask(request, model, store, client)

    assert outcome.status is AskOutcomeStatus.INSUFFICIENT_EVIDENCE
    assert outcome.reason == "The evidence does not establish a visit count."
    assert outcome.claims == ()
    assert len(outcome.evidence) == 1
