"""Local-only adapter for the original BioCLIP ViT-B-16 checkpoint."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.resources
import json
import math
import platform
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from bird_recognition.embed.config import canonical_json_bytes, canonical_json_sha256
from bird_recognition.embed.models import (
    EmbeddingModelRecord,
    EmbedValidationError,
    SharedModelError,
    Vector,
)

ASSET_CONFIG_NAME = "open_clip_config.json"
ASSET_CHECKPOINT_NAME = "open_clip_pytorch_model.bin"
ASSET_MANIFEST_NAME = "asset-manifest.json"
UPSTREAM_NAME = "imageomics/bioclip"
ARCHITECTURE = "ViT-B-16"
DIMENSION = 512
IMAGE_SIZE = 224
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DEFAULT_MEAN = (0.48145466, 0.4578275, 0.40821073)
_DEFAULT_STD = (0.26862954, 0.26130258, 0.27577711)


class BioClipModel:
    """Loaded CPU BioCLIP model with immutable asset identity."""

    def __init__(
        self,
        model: Any,
        preprocess: Any,
        tokenizer: Any,
        identity: EmbeddingModelRecord,
    ) -> None:
        self._model = model
        self._preprocess = preprocess
        self._tokenizer = tokenizer
        self._identity = identity

    @property
    def identity(self) -> EmbeddingModelRecord:
        """Return the immutable model and runtime identity."""
        return self._identity

    def encode_image(self, image: object) -> Vector:
        """Return one deterministic, normalized CPU image vector."""
        try:
            import torch

            if isinstance(image, (str, Path)):
                with Image.open(image) as opened:
                    rgb_image = opened.convert("RGB")
                    tensor = self._preprocess(rgb_image)
            elif isinstance(image, Image.Image):
                tensor = self._preprocess(image.convert("RGB"))
            else:
                raise TypeError("image input must be a PIL image or path")
            batch = tensor.to(device="cpu", dtype=torch.float32).unsqueeze(0)
            with torch.inference_mode():
                encoded = self._model.encode_image(batch)
                normalized = torch.nn.functional.normalize(
                    encoded.to(device="cpu", dtype=torch.float32), dim=-1
                )
            return _validated_output(normalized, 1)
        except SharedModelError:
            raise
        except Exception as error:
            raise SharedModelError("BioCLIP image inference failed") from error

    def encode_texts(self, prompts: tuple[str, ...]) -> tuple[Vector, ...]:
        """Return normalized text vectors in prompt order."""
        if not prompts or any(
            not isinstance(prompt, str) or not prompt for prompt in prompts
        ):
            raise SharedModelError("BioCLIP prompts are invalid")
        try:
            import torch

            tokens = self._tokenizer(prompts).to(device="cpu")
            with torch.inference_mode():
                encoded = self._model.encode_text(tokens)
                normalized = torch.nn.functional.normalize(
                    encoded.to(device="cpu", dtype=torch.float32), dim=-1
                )
            return _validated_batch_output(normalized, len(prompts))
        except SharedModelError:
            raise
        except Exception as error:
            raise SharedModelError("BioCLIP text inference failed") from error


def load_bioclip(model_directory: Path) -> BioClipModel:
    """Validate and strictly load a complete local BioCLIP asset bundle."""
    root = Path(model_directory).expanduser()
    if not root.is_dir():
        raise EmbedValidationError("BioCLIP asset directory is unavailable")
    manifest = _read_asset_manifest(root / ASSET_MANIFEST_NAME)
    config_path = _asset_file(root, ASSET_CONFIG_NAME, manifest)
    checkpoint_path = _asset_file(root, ASSET_CHECKPOINT_NAME, manifest)
    config = _read_model_config(config_path)
    bpe_path, tokenizer_sha256 = _require_packaged_bpe()
    del bpe_path

    try:
        import open_clip
        import torch
        from open_clip import image_transform
    except ImportError as error:
        raise EmbedValidationError("OpenCLIP runtime is unavailable") from error

    try:
        model = _create_model(open_clip, torch)
        open_clip.load_checkpoint(model, str(checkpoint_path), strict=True)
        model = model.to(device="cpu", dtype=torch.float32)
        model.eval()
        preprocess = _build_preprocess(image_transform, config)
        tokenizer = open_clip.get_tokenizer(ARCHITECTURE)
        effective_logit_scale = float(torch.exp(model.logit_scale.detach()).item())
        if not math.isfinite(effective_logit_scale) or effective_logit_scale <= 0:
            raise EmbedValidationError("checkpoint logit scale is invalid")
    except EmbedValidationError:
        raise
    except Exception as error:
        raise EmbedValidationError(
            "BioCLIP checkpoint could not be loaded strictly"
        ) from error

    identity_json = {
        "upstream_name": UPSTREAM_NAME,
        "upstream_revision": manifest["upstream_revision"],
        "architecture": ARCHITECTURE,
        "dimension": DIMENSION,
        "checkpoint_sha256": manifest["files"][ASSET_CHECKPOINT_NAME],
        "config_sha256": manifest["files"][ASSET_CONFIG_NAME],
        "tokenizer_sha256": tokenizer_sha256,
        "preprocessing": _preprocessing_contract(config),
        "adapter_version": "bioclip-local-cpu-v1",
        "runtime": {
            "open_clip_torch": importlib.metadata.version("open-clip-torch"),
            "torch": torch.__version__,
            "torchvision": importlib.metadata.version("torchvision"),
            "numpy": importlib.metadata.version("numpy"),
            "pillow": importlib.metadata.version("Pillow"),
            "python": platform.python_version(),
            "device": "cpu",
            "dtype": "float32",
            "mode": "eval/inference_mode",
        },
        "effective_logit_scale": effective_logit_scale,
    }
    canonical_json = canonical_json_bytes(identity_json).decode("utf-8")
    preprocessing_json = canonical_json_bytes(identity_json["preprocessing"]).decode(
        "utf-8"
    )
    tokenizer_json = canonical_json_bytes(
        {
            "name": ARCHITECTURE,
            "bpe_sha256": tokenizer_sha256,
            "context_length": 77,
        }
    ).decode("utf-8")
    runtime_json = canonical_json_bytes(identity_json["runtime"]).decode("utf-8")
    record = EmbeddingModelRecord(
        model_fingerprint=canonical_json_sha256(identity_json),
        upstream_name=UPSTREAM_NAME,
        upstream_revision=manifest["upstream_revision"],
        checkpoint_sha256=manifest["files"][ASSET_CHECKPOINT_NAME],
        config_sha256=manifest["files"][ASSET_CONFIG_NAME],
        tokenizer_sha256=tokenizer_sha256,
        architecture=ARCHITECTURE,
        dimension=DIMENSION,
        preprocessing_json=preprocessing_json,
        tokenizer_json=tokenizer_json,
        adapter_version="bioclip-local-cpu-v1",
        runtime_json=runtime_json,
        logit_scale=effective_logit_scale,
        canonical_json=canonical_json,
    )
    return BioClipModel(model, preprocess, tokenizer, record)


def _read_asset_manifest(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except OSError, UnicodeError, ValueError, json.JSONDecodeError:
        raise EmbedValidationError(
            "BioCLIP asset manifest is unreadable or invalid"
        ) from None
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "upstream_name",
        "upstream_revision",
        "files",
    }:
        raise EmbedValidationError("BioCLIP asset manifest fields are invalid")
    revision = document["upstream_revision"]
    files = document["files"]
    if (
        type(document["schema_version"]) is not int
        or document["schema_version"] != 1
        or document["upstream_name"] != UPSTREAM_NAME
        or not isinstance(revision, str)
        or not _REVISION_PATTERN.fullmatch(revision)
        or not isinstance(files, dict)
        or set(files) != {ASSET_CONFIG_NAME, ASSET_CHECKPOINT_NAME}
        or any(
            not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest)
            for digest in files.values()
        )
    ):
        raise EmbedValidationError("BioCLIP asset manifest contract is invalid")
    return document


def _asset_file(root: Path, name: str, manifest: dict[str, Any]) -> Path:
    path = root / name
    try:
        resolved = path.resolve(strict=True)
        if root.resolve(strict=True) not in resolved.parents or not resolved.is_file():
            raise OSError
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        raise EmbedValidationError("BioCLIP asset file is unavailable") from None
    if digest != manifest["files"][name]:
        raise EmbedValidationError("BioCLIP asset hash does not match its manifest")
    return resolved


def _read_model_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except OSError, UnicodeError, ValueError, json.JSONDecodeError:
        raise EmbedValidationError(
            "BioCLIP model config is unreadable or invalid"
        ) from None
    if not isinstance(config, dict):
        raise EmbedValidationError("BioCLIP model config must be an object")
    vision = config.get("vision_cfg")
    text = config.get("text_cfg")
    if (
        config.get("embed_dim") != DIMENSION
        or not isinstance(vision, dict)
        or vision.get("image_size") != IMAGE_SIZE
        or vision.get("layers") != 12
        or vision.get("width") != 768
        or vision.get("patch_size") != 16
        or not isinstance(text, dict)
        or text.get("context_length") != 77
        or text.get("width") != 512
    ):
        raise EmbedValidationError("BioCLIP config is not supported ViT-B-16/512")
    return config


def _require_packaged_bpe() -> tuple[Any, str]:
    try:
        resource = importlib.resources.files("open_clip").joinpath(
            "bpe_simple_vocab_16e6.txt.gz"
        )
        content = resource.read_bytes()
    except ModuleNotFoundError, OSError, TypeError:
        raise EmbedValidationError(
            "packaged OpenCLIP BPE vocabulary is unavailable"
        ) from None
    return resource, hashlib.sha256(content).hexdigest()


def _create_model(open_clip: Any, torch: Any) -> Any:
    return open_clip.create_model(
        ARCHITECTURE,
        pretrained=None,
        device="cpu",
        precision="fp32",
        force_image_size=IMAGE_SIZE,
        pretrained_image=False,
        pretrained_text=False,
    ).to(device="cpu", dtype=torch.float32)


def _build_preprocess(image_transform: Any, config: dict[str, Any]) -> Any:
    preprocess_cfg = config.get("preprocess_cfg", {})
    mean = tuple(preprocess_cfg.get("mean", _DEFAULT_MEAN))
    std = tuple(preprocess_cfg.get("std", _DEFAULT_STD))
    if (
        len(mean) != 3
        or len(std) != 3
        or any(not math.isfinite(value) for value in (*mean, *std))
        or any(value <= 0 for value in std)
    ):
        raise EmbedValidationError("BioCLIP preprocessing configuration is invalid")
    return image_transform(
        IMAGE_SIZE,
        is_train=False,
        mean=mean,
        std=std,
    )


def _preprocessing_contract(config: dict[str, Any]) -> dict[str, Any]:
    preprocess_cfg = config.get("preprocess_cfg", {})
    return {
        "image_size": IMAGE_SIZE,
        "mean": preprocess_cfg.get("mean", _DEFAULT_MEAN),
        "std": preprocess_cfg.get("std", _DEFAULT_STD),
        "color": "RGB",
        "transform": "open_clip_eval_v1",
        "dtype": "float32",
    }


def _validated_output(output: Any, expected_rows: int) -> Vector:
    vectors = _validated_batch_output(output, expected_rows)
    return vectors[0]


def _validated_batch_output(output: Any, expected_rows: int) -> tuple[Vector, ...]:
    try:
        import torch

        values = output.detach().cpu().to(dtype=torch.float32).numpy()
        matrix = np.asarray(values, dtype=np.float32)
    except Exception as error:
        raise SharedModelError("BioCLIP returned an invalid vector batch") from error
    if matrix.shape != (expected_rows, DIMENSION) or not np.isfinite(matrix).all():
        raise SharedModelError("BioCLIP returned an invalid vector dimension or value")
    norms = np.linalg.norm(matrix.astype(np.float64), axis=1)
    if not np.all(np.isfinite(norms)) or not np.allclose(norms, 1.0, rtol=0, atol=1e-5):
        raise SharedModelError("BioCLIP returned a non-normalized vector")
    return tuple(tuple(float(item) for item in row) for row in matrix)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
