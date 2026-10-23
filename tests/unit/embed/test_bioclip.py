from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from bird_recognition.embed.models import EmbedValidationError, SharedModelError


def _write_asset_bundle(
    root: Path,
    *,
    config: dict[str, Any] | None = None,
    revision: str = "a" * 40,
) -> Path:
    from bird_recognition.embed.bioclip import ASSET_CHECKPOINT_NAME, ASSET_CONFIG_NAME

    root.mkdir(parents=True, exist_ok=True)
    config_path = root / ASSET_CONFIG_NAME
    checkpoint_path = root / ASSET_CHECKPOINT_NAME
    config_path.write_text(
        json.dumps(
            config
            or {
                "model_cfg": {
                    "embed_dim": 512,
                    "vision_cfg": {
                        "image_size": 224,
                        "layers": 12,
                        "width": 768,
                        "patch_size": 16,
                    },
                    "text_cfg": {"context_length": 77, "width": 512},
                },
                "preprocess_cfg": {
                    "mean": [0.48145466, 0.4578275, 0.40821073],
                    "std": [0.26862954, 0.26130258, 0.27577711],
                },
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path.write_bytes(b"controlled checkpoint")
    manifest = {
        "schema_version": 1,
        "upstream_name": "imageomics/bioclip",
        "upstream_revision": revision,
        "files": {
            ASSET_CONFIG_NAME: hashlib.sha256(config_path.read_bytes()).hexdigest(),
            ASSET_CHECKPOINT_NAME: hashlib.sha256(
                checkpoint_path.read_bytes()
            ).hexdigest(),
        },
    }
    (root / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


def test_load_bioclip_missing_asset_bundle_fails_preflight(tmp_path: Path) -> None:
    from bird_recognition.embed.bioclip import load_bioclip

    with pytest.raises((EmbedValidationError, SharedModelError)):
        load_bioclip(tmp_path / "missing")


def test_load_bioclip_rejects_hash_mismatched_asset(tmp_path: Path) -> None:
    from bird_recognition.embed.bioclip import (
        ASSET_CHECKPOINT_NAME,
        load_bioclip,
    )

    root = _write_asset_bundle(tmp_path / "assets")
    (root / ASSET_CHECKPOINT_NAME).write_bytes(b"tampered checkpoint")

    with pytest.raises(EmbedValidationError):
        load_bioclip(root)


@pytest.mark.parametrize(
    "configuration",
    [
        {"embed_dim": 256, "vision_cfg": {"image_size": 224}, "text_cfg": {}},
        {
            "embed_dim": 512,
            "vision_cfg": {"image_size": 336},
            "text_cfg": {"context_length": 77},
        },
    ],
)
def test_load_bioclip_rejects_unsupported_architecture_or_dimension(
    tmp_path: Path, configuration: dict[str, Any]
) -> None:
    from bird_recognition.embed.bioclip import load_bioclip

    root = _write_asset_bundle(tmp_path / "assets", config=configuration)

    with pytest.raises(EmbedValidationError):
        load_bioclip(root)


@pytest.mark.parametrize("revision", ["main", "latest", "short"])
def test_load_bioclip_requires_immutable_upstream_revision(
    tmp_path: Path, revision: str
) -> None:
    from bird_recognition.embed.bioclip import load_bioclip

    root = _write_asset_bundle(tmp_path / "assets", revision=revision)

    with pytest.raises(EmbedValidationError):
        load_bioclip(root)


def test_load_bioclip_requires_packaged_tokenizer_and_never_falls_back_to_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bird_recognition.embed import bioclip

    root = _write_asset_bundle(tmp_path / "assets")

    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("hub or pretrained loading was attempted")

    def missing_packaged_bpe() -> tuple[object, str]:
        raise EmbedValidationError("packaged OpenCLIP BPE vocabulary is unavailable")

    monkeypatch.setattr(bioclip, "_require_packaged_bpe", missing_packaged_bpe)
    monkeypatch.setattr(bioclip, "_create_model", fail_if_called)

    with pytest.raises(EmbedValidationError):
        bioclip.load_bioclip(root)


def test_load_bioclip_strictly_loads_local_checkpoint_on_cpu(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import open_clip
    import torch

    from bird_recognition.embed import bioclip

    root = _write_asset_bundle(tmp_path / "assets")
    loaded: dict[str, object] = {}
    model = _ControlledLoadedModel(torch)

    def create_model(
        open_clip_module: object, torch_module: object, checkpoint_path: Path
    ) -> _ControlledLoadedModel:
        loaded["factory"] = (open_clip_module, torch_module, checkpoint_path)
        return model

    monkeypatch.setattr(bioclip, "_require_packaged_bpe", lambda: (None, "5" * 64))
    monkeypatch.setattr(bioclip, "_create_model", create_model)
    monkeypatch.setattr(
        open_clip, "get_tokenizer", lambda name: lambda prompts: prompts
    )
    monkeypatch.setattr(
        bioclip, "_build_preprocess", lambda transform, config: object()
    )

    adapter = bioclip.load_bioclip(root)

    assert loaded["factory"] == (
        open_clip,
        torch,
        root / bioclip.ASSET_CHECKPOINT_NAME,
    )
    assert adapter.identity.architecture == "ViT-B-16"
    assert adapter.identity.dimension == 512
    assert adapter.identity.upstream_revision == "a" * 40
    assert adapter.identity.logit_scale == pytest.approx(2.0)


def test_create_model_loads_local_checkpoint_without_hub_loading(
    tmp_path: Path,
) -> None:
    from bird_recognition.embed.bioclip import _create_model

    options: dict[str, object] = {}
    checkpoint_path = tmp_path / "open_clip_pytorch_model.bin"

    class Model:
        def to(self, **kwargs: object) -> Model:
            return self

    def factory(name: str, **kwargs: object) -> Model:
        options.update({"name": name, **kwargs})
        return Model()

    clip = SimpleNamespace(create_model=factory)
    torch = SimpleNamespace(float32="float32")

    _create_model(clip, torch, checkpoint_path)

    assert options["pretrained"] == str(checkpoint_path)
    assert options["pretrained_image"] is False
    assert options["pretrained_text"] is False
    assert "pretrained_hf" not in options
    assert options["device"] == "cpu"


def test_packaged_bpe_resource_has_a_sha256_identity() -> None:
    from bird_recognition.embed.bioclip import _require_packaged_bpe

    resource, digest = _require_packaged_bpe()

    assert resource.is_file()
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


class _ControlledLoadedModel:
    def __init__(self, torch_module: object) -> None:
        self.torch = torch_module
        self.logit_scale = torch_module.tensor(0.6931471805599453)
        self.eval_called = False

    def to(self, **kwargs: object) -> _ControlledLoadedModel:
        return self

    def eval(self) -> _ControlledLoadedModel:
        self.eval_called = True
        return self


def test_bioclip_preprocesses_local_images_and_returns_cpu_float32_vectors(
    generated_crop: Path,
) -> None:
    import numpy as np
    import torch

    from bird_recognition.embed import bioclip
    from bird_recognition.embed.models import EmbeddingModelRecord

    model = bioclip.BioClipModel.__new__(bioclip.BioClipModel)
    model._identity = EmbeddingModelRecord(
        model_fingerprint="1" * 64,
        upstream_name="imageomics/bioclip",
        upstream_revision="a" * 40,
        checkpoint_sha256="2" * 64,
        config_sha256="3" * 64,
        tokenizer_sha256="4" * 64,
        architecture="ViT-B-16",
        dimension=512,
        preprocessing_json="{}",
        tokenizer_json="{}",
        adapter_version="bioclip-local-v1",
        runtime_json="{}",
        logit_scale=1.0,
        canonical_json="{}",
    )
    model._model = _ControlledModel()
    model._preprocess = lambda image: torch.zeros((3, 224, 224), dtype=torch.float32)
    model._tokenizer = lambda prompts: torch.zeros(
        (len(prompts), 77), dtype=torch.int64
    )

    result = model.encode_image(generated_crop)

    assert len(result) == 512
    assert all(np.isfinite(result))
    assert sum(value * value for value in result) == pytest.approx(1.0)
    assert model._model.image_input.dtype == torch.float32
    assert model._model.image_input.device.type == "cpu"
    text_result = model.encode_texts(("a photo of a bird.",))
    assert len(text_result) == 1
    assert len(text_result[0]) == 512
    assert sum(value * value for value in text_result[0]) == pytest.approx(1.0)


class _ControlledModel:
    def __init__(self) -> None:
        import torch

        self.image_input: Any = None
        self.text_input: Any = None
        self.torch = torch

    def encode_image(self, image: Any) -> Any:
        self.image_input = image
        return self.torch.nn.functional.normalize(
            self.torch.ones((1, 512), dtype=self.torch.float32), dim=-1
        )

    def encode_text(self, tokens: Any) -> Any:
        self.text_input = tokens
        return self.torch.nn.functional.normalize(
            self.torch.ones((len(tokens), 512), dtype=self.torch.float32), dim=-1
        )
