"""Detector interface and local MegaDetector adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from bird_recognition.ingest.models import Detection, DetectionCategory, DetectionError

MEGADETECTOR_VARIANT = "MDV6-mit-yolov9-c"
MEGADETECTOR_CONFIG = "config_v9s.yaml"


class Detector(Protocol):
    """Interface implemented by inference backends and test doubles."""

    def detect(self, image: object) -> Sequence[Detection]:
        """Return normalized detections for a complete image."""


class MegaDetectorAdapter:
    """Load a locally provisioned MegaDetector V6 MIT model once per run."""

    def __init__(
        self,
        model_path: Path,
        config_path: Path | None = None,
        loader: Callable[[Path, Path, str], object] | None = None,
        inference: Callable[[object, object], object] | None = None,
        variant: str = MEGADETECTOR_VARIANT,
    ) -> None:
        try:
            self.model_path = model_path.expanduser().resolve(strict=True)
            if not self.model_path.is_file():
                raise DetectionError(
                    f"MegaDetector model is not a file: {self.model_path}"
                )
            config_candidate = config_path or (
                self.model_path.parent / MEGADETECTOR_CONFIG
            )
            try:
                self.config_path = config_candidate.expanduser().resolve(strict=True)
            except OSError as error:
                raise DetectionError(
                    f"MegaDetector model config is not a file: {config_candidate}"
                ) from error
            if not self.config_path.is_file():
                raise DetectionError(
                    f"MegaDetector model config is not a file: {self.config_path}"
                )
            if variant != MEGADETECTOR_VARIANT:
                raise DetectionError(f"unsupported MegaDetector V6 variant: {variant}")
            self.model_sha256 = self._hash_file(self.model_path, "model")
            self.model_config_sha256 = self._hash_file(self.config_path, "model config")
            self.model_variant = variant
            if loader is None:
                self._model = self._load_local_model(
                    self.model_path, self.config_path, self.model_variant
                )
            else:
                self._model = loader(
                    self.model_path, self.config_path, self.model_variant
                )
            self._inference = inference
            if inference is None and not callable(
                getattr(self._model, "single_image_detection", None)
            ):
                raise TypeError(
                    "loaded MegaDetector V6 model does not expose single-image "
                    "inference"
                )
            try:
                package_version = version("PytorchWildlife")
            except PackageNotFoundError:
                package_version = "unknown"
            self.package_version = package_version
        except Exception as error:
            if isinstance(error, DetectionError):
                raise
            raise DetectionError(
                f"failed to load local MegaDetector V6 model: {error}"
            ) from error
        self.model_identifier = self.model_path.name
        self.model_version = (
            f"pytorchwildlife-{self.package_version}/{self.model_variant}"
        )

    @staticmethod
    def _hash_file(path: Path, description: str) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as model_file:
                for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise DetectionError(
                f"cannot read MegaDetector {description}: {path}"
            ) from error
        return digest.hexdigest()

    @staticmethod
    def _load_local_model(model_path: Path, config_path: Path, variant: str) -> object:
        try:
            from omegaconf import OmegaConf
            from PytorchWildlife.models.detection.yolo_mit import (
                MegaDetectorV6MIT,
                yolo_mit_base,
            )
        except ImportError as error:
            raise DetectionError(
                "PyTorch-Wildlife 1.3.0 and its model dependencies are required"
            ) from error

        class LocalMegaDetectorV6MIT(MegaDetectorV6MIT):
            def _load_cfg(self) -> object:
                return OmegaConf.load(str(config_path))

            def _load_model(
                self,
                weights: str | None = None,
                device: str = "cpu",
                url: str | None = None,
            ) -> None:
                if getattr(self, "_ingest_model_loaded", False):
                    return
                if url is not None or weights is None:
                    raise DetectionError(
                        "MegaDetector V6 requires explicit local weights; "
                        "downloads are disabled"
                    )
                if Path(weights).resolve() != model_path:
                    raise DetectionError(
                        "MegaDetector attempted to load unexpected weights"
                    )
                self.cfg.image_size = [self.IMAGE_SIZE, self.IMAGE_SIZE]
                self.model = yolo_mit_base.create_model(
                    self.cfg.model, weight_path=str(model_path), class_num=3
                ).to(device)
                self.model.eval()
                self.converter = yolo_mit_base.create_converter(
                    self.cfg.model.name,
                    self.model,
                    self.cfg.model.anchor,
                    self.cfg.image_size,
                    device,
                )
                self.post_proccess = yolo_mit_base.PostProcess(
                    self.converter, self.cfg.task.nms
                )
                self.url = None
                self._ingest_model_loaded = True

        model = LocalMegaDetectorV6MIT(
            weights=str(model_path), device="cpu", version=variant
        )
        model._load_model(weights=str(model_path), device="cpu", url=None)
        return model

    def detect(self, image: object) -> tuple[Detection, ...]:
        """Run V6 on a complete RGB image and normalize its pixel boxes."""
        try:
            import numpy as np

            if hasattr(image, "convert"):
                image = image.convert("RGB")
            rgb_image = np.asarray(image)
            if rgb_image.ndim != 3 or rgb_image.shape[2] != 3:
                raise TypeError("input image must be an RGB HWC array")
            if rgb_image.dtype != np.uint8:
                raise TypeError("input image pixels must use uint8 values")
            rgb_image = np.ascontiguousarray(rgb_image)
            height, width = rgb_image.shape[:2]
            if width <= 0 or height <= 0:
                raise ValueError("input image dimensions must be positive")
            if self._inference is None:
                result = self._model.single_image_detection(
                    rgb_image, det_conf_thres=0.0
                )
            else:
                result = self._inference(rgb_image, self._model)
            if not isinstance(result, dict):
                raise TypeError("model output must be an object")
            if result.get("failure"):
                raise RuntimeError(
                    f"MegaDetector V6 reported failure: {result['failure']}"
                )
            raw_detections = result["detections"]
            boxes = np.asarray(raw_detections.xyxy)
            confidences = np.asarray(raw_detections.confidence)
            class_ids = np.asarray(raw_detections.class_id)
            if boxes.ndim != 2 or boxes.shape[1:] != (4,):
                raise TypeError("model xyxy boxes must have shape (N, 4)")
            if confidences.ndim != 1 or class_ids.ndim != 1:
                raise TypeError(
                    "model confidences and class IDs must be one-dimensional"
                )
            if not (len(boxes) == len(confidences) == len(class_ids)):
                raise TypeError("model output arrays have inconsistent lengths")
            detections: list[Detection] = []
            for index, (box, raw_confidence, raw_class_id) in enumerate(
                zip(boxes, confidences, class_ids, strict=True)
            ):
                category = self._category(raw_class_id)
                confidence = float(raw_confidence)
                if not np.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError(
                        "model confidence must be finite and within [0, 1]"
                    )
                left, top, right, bottom = (float(value) for value in box)
                if not all(np.isfinite(value) for value in (left, top, right, bottom)):
                    raise ValueError("model bounding box coordinates must be finite")
                if right <= left or bottom <= top:
                    raise ValueError("model bounding box must have positive area")
                normalized_box = (
                    max(0.0, min(1.0, left / width)),
                    max(0.0, min(1.0, top / height)),
                    max(0.0, min(1.0, right / width)),
                    max(0.0, min(1.0, bottom / height)),
                )
                if (
                    normalized_box[2] <= normalized_box[0]
                    or normalized_box[3] <= normalized_box[1]
                ):
                    continue
                detections.append(
                    Detection(
                        category=category,
                        confidence=confidence,
                        box=normalized_box,
                        detection_id=f"d{index:06d}",
                    )
                )
            return tuple(detections)
        except Exception as error:
            raise DetectionError(
                f"MegaDetector V6 inference failed: {error}"
            ) from error

    @staticmethod
    def _category(value: object) -> DetectionCategory:
        class_id = int(value)
        if class_id != value:
            raise TypeError(f"unexpected MegaDetector V6 class ID: {value}")
        if class_id == 0:
            return DetectionCategory.ANIMAL
        if class_id == 1:
            return DetectionCategory.PERSON
        if class_id == 2:
            return DetectionCategory.OTHER
        raise ValueError(f"unexpected MegaDetector V6 class ID: {class_id}")
