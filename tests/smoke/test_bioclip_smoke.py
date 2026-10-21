from __future__ import annotations

import math
import os
import socket
from pathlib import Path
from typing import Any

import pytest
from dotenv import dotenv_values, find_dotenv

_DOTENV_PATH = find_dotenv(usecwd=True)
_ENVIRONMENT = {
    **(dotenv_values(_DOTENV_PATH) if _DOTENV_PATH else {}),
    **os.environ,
}
_MODEL_DIR = _ENVIRONMENT.get("BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR")
_IMAGE = _ENVIRONMENT.get("BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE")


@pytest.fixture
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_network(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise OSError("network access is disabled for BioCLIP smoke tests")

    for target, name in (
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket.socket, "sendto"),
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket, "gethostbyname"),
        (socket, "gethostbyname_ex"),
        (socket, "gethostbyaddr"),
    ):
        monkeypatch.setattr(target, name, reject_network)


@pytest.mark.local_model
@pytest.mark.skipif(
    not all((_MODEL_DIR, _IMAGE)),
    reason=(
        "set BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR and "
        "BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE"
    ),
)
def test_bioclip_smoke_local_assets_produce_deterministic_vectors_and_scores(
    deny_network: None,
) -> None:
    """Verify local inference only; this is not evidence of species quality."""
    assert _MODEL_DIR is not None
    assert _IMAGE is not None

    from bird_recognition.embed.bioclip import load_bioclip
    from bird_recognition.embed.models import SpeciesCandidate
    from bird_recognition.embed.scoring import score_embeddings

    model = load_bioclip(Path(_MODEL_DIR))
    candidates = (
        SpeciesCandidate(id="chaffinch", name="chaffinch"),
        SpeciesCandidate(id="great_tit", name="great tit"),
    )
    prompts = tuple(f"a photo of {candidate.name}." for candidate in candidates)
    image_vector = model.encode_image(Path(_IMAGE))
    repeated_image_vector = model.encode_image(Path(_IMAGE))
    text_vectors = model.encode_texts(prompts)
    repeated_text_vectors = model.encode_texts(prompts)

    assert image_vector == repeated_image_vector
    assert text_vectors == repeated_text_vectors
    for vector in (image_vector, *text_vectors):
        assert len(vector) == 512
        assert all(math.isfinite(value) for value in vector)
        assert math.isclose(
            math.sqrt(math.fsum(value * value for value in vector)),
            1.0,
            rel_tol=0,
            abs_tol=1e-5,
        )

    result = score_embeddings(
        image_vector,
        text_vectors,
        candidates,
        logit_scale=model.identity.logit_scale,
        threshold=0.5,
    )
    repeated_result = score_embeddings(
        repeated_image_vector,
        repeated_text_vectors,
        candidates,
        logit_scale=model.identity.logit_scale,
        threshold=0.5,
    )

    assert result == repeated_result
    assert len(result.scores) == len(candidates)
    assert all(
        math.isfinite(score.logit)
        and math.isfinite(score.score)
        and 0 <= score.score <= 1
        for score in result.scores
    )
    assert math.isclose(
        math.fsum(score.score for score in result.scores),
        1.0,
        rel_tol=0,
        abs_tol=1e-12,
    )
