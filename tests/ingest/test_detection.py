from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from bird_recognition.ingest.detection import MegaDetectorAdapter
from bird_recognition.ingest.models import DetectionCategory, DetectionError


def test_adapter_uses_loaded_model_inference_api_and_normalizes_output(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"local model")
    image = object()
    inference = MagicMock(
        return_value={
            "detections": [
                {"category": "1", "conf": 0.8, "bbox": [0.1, 0.2, 0.3, 0.4]},
                {"category": "2", "conf": 0.7, "bbox": [0.2, 0.3, 0.1, 0.2]},
                {"category": "3", "conf": 0.6, "bbox": [0.0, 0.0, 0.5, 0.5]},
            ]
        }
    )
    model = SimpleNamespace(generate_detections_one_image=inference)
    adapter = MegaDetectorAdapter(
        model_path,
        loader=MagicMock(return_value=model),
    )

    detections = adapter.detect(image)

    inference.assert_called_once_with(image, detection_threshold=0.0)
    assert [detection.category for detection in detections] == [
        DetectionCategory.ANIMAL,
        DetectionCategory.PERSON,
        DetectionCategory.OTHER,
    ]
    assert detections[0].box == pytest.approx((0.1, 0.2, 0.4, 0.6))


def test_adapter_fails_closed_on_official_inference_failure(tmp_path: Path) -> None:
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"local model")
    model = SimpleNamespace(
        generate_detections_one_image=MagicMock(
            return_value={"failure": "inference failed", "detections": []}
        )
    )
    adapter = MegaDetectorAdapter(model_path, loader=MagicMock(return_value=model))

    with pytest.raises(DetectionError, match="MegaDetector reported failure"):
        adapter.detect(object())


def test_adapter_rejects_loaded_model_without_official_inference_method(
    tmp_path: Path,
) -> None:
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"local model")

    with pytest.raises(DetectionError, match="does not expose single-image inference"):
        MegaDetectorAdapter(model_path, loader=MagicMock(return_value=object()))
