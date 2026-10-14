"""Detector interface and local MegaDetector adapter."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Protocol

from bird_recognition.ingest.models import Detection, DetectionCategory, DetectionError


class Detector(Protocol):
    """Interface implemented by inference backends and test doubles."""

    def detect(self, image: object) -> Sequence[Detection]:
        """Return normalized detections for a complete image."""


class MegaDetectorAdapter:
    """Load a locally provisioned official MegaDetector model once per run."""

    def __init__(
        self,
        model_path: Path,
        loader: Callable[[str], object] | None = None,
        inference: Callable[[object, object], dict[str, object]] | None = None,
    ) -> None:
        self.model_path = model_path.expanduser().resolve(strict=True)
        if not self.model_path.is_file():
            raise DetectionError(f"MegaDetector model is not a file: {self.model_path}")
        self.model_sha256 = self._hash_model(self.model_path)
        try:
            if loader is None:
                from megadetector.detection import run_detector

                loader = run_detector.load_detector
            self._model = loader(str(self.model_path))
            self._inference = inference
            if inference is None and not callable(
                getattr(self._model, "generate_detections_one_image", None)
            ):
                raise TypeError(
                    "loaded MegaDetector does not expose single-image inference"
                )
            try:
                package_version = version("megadetector")
            except PackageNotFoundError:
                package_version = "unknown"
        except Exception as error:
            raise DetectionError(
                f"failed to load local MegaDetector model: {error}"
            ) from error
        self.model_identifier = self.model_path.name
        self.model_version = f"official-megadetector-{package_version}"

    @staticmethod
    def _hash_model(path: Path) -> str:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as model_file:
                for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as error:
            raise DetectionError(f"cannot read MegaDetector model: {path}") from error
        return digest.hexdigest()

    def detect(self, image: object) -> tuple[Detection, ...]:
        """Run inference and normalize official MegaDetector output categories."""
        try:
            if self._inference is None:
                result = self._model.generate_detections_one_image(
                    image, detection_threshold=0.0
                )
            else:
                result = self._inference(image, self._model)
            if result.get("failure"):
                raise RuntimeError(
                    f"MegaDetector reported failure: {result['failure']}"
                )
            raw_detections = result["detections"]
            if not isinstance(raw_detections, list):
                raise TypeError("model output detections must be a list")
            detections: list[Detection] = []
            for index, raw in enumerate(raw_detections):
                if not isinstance(raw, dict):
                    raise TypeError("model detection must be an object")
                category = self._category(raw["category"])
                confidence = float(raw["conf"])
                coordinates = raw["bbox"]
                if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 4:
                    raise TypeError("model bounding box must contain four values")
                left, top, width, height = (float(value) for value in coordinates)
                detections.append(
                    Detection(
                        category=category,
                        confidence=confidence,
                        box=(left, top, left + width, top + height),
                        detection_id=f"d{index:06d}",
                    )
                )
            return tuple(detections)
        except Exception as error:
            raise DetectionError(f"MegaDetector inference failed: {error}") from error

    @staticmethod
    def _category(value: object) -> DetectionCategory:
        normalized = str(value).strip().lower()
        if normalized in {"1", "animal"}:
            return DetectionCategory.ANIMAL
        if normalized in {"2", "person"}:
            return DetectionCategory.PERSON
        return DetectionCategory.OTHER
