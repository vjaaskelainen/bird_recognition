from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from bird_recognition.api.app import create_app
from bird_recognition.api.settings import APISettings


def test_ask_requires_opt_in_before_store_or_model_use() -> None:
    store_calls = []
    client = TestClient(
        create_app(
            APISettings(database_url="postgresql://local"),
            store_factory=lambda url: store_calls.append(url),
        )
    )

    response = client.post(
        "/v1/ask",
        json={
            "run_id": "9a0be798-6a41-4a2d-a2d2-bf6edbf15000",
            "question": "Which bird is visible?",
            "allow_external_transmission": False,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "opt_in_required"
    assert store_calls == []


def test_ask_opt_in_returns_payload_and_transmission_notice(
    fake_store, monkeypatch
) -> None:
    run_id = UUID("9a0be798-6a41-4a2d-a2d2-bf6edbf15000")
    fake_store.context = SimpleNamespace(
        run_id=run_id,
        model_input_view="fit-pad-v1",
        model_fingerprint=None,
        config_fingerprint=None,
        candidate_set_fingerprint=None,
    )
    outcome_holder = {}

    def execute(request, model, store, **kwargs):
        result = SimpleNamespace(
            request=request,
            context=kwargs["context"],
            status=SimpleNamespace(value="supported"),
            evidence=(),
            claims=(),
            reason=None,
        )
        outcome_holder["request"] = request
        return result

    monkeypatch.setenv("BIRD_RECOGNITION_ASK_API_KEY", "local-test-key")
    client = TestClient(
        create_app(
            APISettings(
                database_url="postgresql://localhost/test",
                model_dir=Path("model"),
            ),
            store_factory=lambda _: fake_store,
            model_loader=lambda *_: object(),
            ask_executor=execute,
        )
    )

    response = client.post(
        "/v1/ask",
        json={
            "run_id": str(run_id),
            "question": "Which bird is visible?",
            "allow_external_transmission": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert response.json()["question"] == "Which bird is visible?"
    assert "Transmission notice:" in response.json()["transmission_notice"]
    assert outcome_holder["request"].question == "Which bird is visible?"
