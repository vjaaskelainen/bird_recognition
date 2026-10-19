import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from bird_recognition.ingest.detection import (
    MEGADETECTOR_VARIANT,
    MegaDetectorAdapter,
)
from bird_recognition.ingest.models import DetectionCategory, DetectionError


def _files(tmp_path: Path) -> tuple[Path, Path]:
    model_path = tmp_path / "weights.ckpt"
    config_path = tmp_path / "config_v9s.yaml"
    model_path.write_bytes(b"local model")
    config_path.write_text("model: {}\ntask: {}\n", encoding="utf-8")
    return model_path, config_path


def _result(
    boxes: list[list[float]], confidences: list[float], classes: list[int]
) -> dict[str, object]:
    return {
        "detections": SimpleNamespace(
            xyxy=np.asarray(boxes, dtype=np.float32).reshape((-1, 4)),
            confidence=np.asarray(confidences, dtype=np.float32),
            class_id=np.asarray(classes, dtype=np.int64),
        )
    }


def test_adapter_loads_explicit_local_weights_and_normalizes_v6_output(
    tmp_path: Path,
) -> None:
    model_path, config_path = _files(tmp_path)
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    inference = MagicMock(
        return_value=_result(
            [[20, 10, 80, 50], [50, 25, 200, 100], [0, 0, 200, 100]],
            [0.8, 0.7, 0.6],
            [0, 1, 2],
        )
    )
    model = object()
    loader = MagicMock(return_value=model)
    adapter = MegaDetectorAdapter(
        model_path, config_path, loader=loader, inference=inference
    )

    detections = adapter.detect(image)

    loader.assert_called_once_with(
        model_path.resolve(), config_path.resolve(), MEGADETECTOR_VARIANT
    )
    inference.assert_called_once_with(image, model)
    assert [detection.category for detection in detections] == [
        DetectionCategory.ANIMAL,
        DetectionCategory.PERSON,
        DetectionCategory.OTHER,
    ]
    assert detections[0].box == pytest.approx((0.1, 0.1, 0.4, 0.5))
    assert detections[1].box == pytest.approx((0.25, 0.25, 1.0, 1.0))
    assert detections[2].box == pytest.approx((0.0, 0.0, 1.0, 1.0))
    assert adapter.model_variant == MEGADETECTOR_VARIANT
    assert adapter.model_config_sha256


def test_adapter_loads_pinned_mit_api_without_downloads(tmp_path: Path) -> None:
    model_path, config_path = _files(tmp_path)
    model_instance = MagicMock()
    model_instance.to.return_value = model_instance
    package_model = MagicMock(return_value=model_instance)
    package_converter = MagicMock(return_value=object())
    package_postprocess = MagicMock(return_value=object())
    model_config = SimpleNamespace(
        model=SimpleNamespace(name="yolov9", anchor=object()),
        task=SimpleNamespace(nms=object()),
    )
    omega_conf = ModuleType("omegaconf")
    config_loader = MagicMock(return_value=model_config)
    omega_conf.OmegaConf = SimpleNamespace(load=config_loader)
    wildlife = ModuleType("PytorchWildlife")
    wildlife.__path__ = []
    models = ModuleType("PytorchWildlife.models")
    models.__path__ = []
    detection = ModuleType("PytorchWildlife.models.detection")
    detection.__path__ = []
    yolo_mit = ModuleType("PytorchWildlife.models.detection.yolo_mit")
    yolo_mit.__path__ = []
    yolo_base = ModuleType("PytorchWildlife.models.detection.yolo_mit.yolo_mit_base")
    yolo_base.create_model = package_model
    yolo_base.create_converter = package_converter
    yolo_base.PostProcess = package_postprocess

    class MegaDetectorV6MIT:
        def __init__(self, weights: str, device: str, version: str) -> None:
            self.IMAGE_SIZE = 640
            self.MODEL_NAME = "MDV6-mit-yolov9-c.ckpt"
            self.cfg = self._load_cfg()
            self.weights = weights
            self.device = device
            self.url = "https://model-weights-must-not-download.invalid"
            self.received_version = version

    yolo_mit.MegaDetectorV6MIT = MegaDetectorV6MIT
    yolo_mit.yolo_mit_base = yolo_base
    detection.yolo_mit = yolo_mit
    models.detection = detection
    wildlife.models = models
    modules = {
        "omegaconf": omega_conf,
        "PytorchWildlife": wildlife,
        "PytorchWildlife.models": models,
        "PytorchWildlife.models.detection": detection,
        "PytorchWildlife.models.detection.yolo_mit": yolo_mit,
        "PytorchWildlife.models.detection.yolo_mit.yolo_mit_base": yolo_base,
    }

    with patch.dict(sys.modules, modules):
        model = MegaDetectorAdapter._load_local_model(
            model_path.resolve(), config_path.resolve(), MEGADETECTOR_VARIANT
        )
        model._load_model(weights=str(model_path.resolve()), device="cpu", url=None)

    assert model.url is None
    assert model._ingest_model_loaded is True
    assert model.weights == str(model_path.resolve())
    assert model.received_version == MEGADETECTOR_VARIANT
    config_loader.assert_called_once_with(str(config_path.resolve()))
    package_model.assert_called_once_with(
        model_config.model, weight_path=str(model_path.resolve()), class_num=3
    )
    package_converter.assert_called_once()
    package_postprocess.assert_called_once()


def test_adapter_requests_zero_confidence_and_accepts_no_detections(
    tmp_path: Path,
) -> None:
    model_path, config_path = _files(tmp_path)
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    inference = MagicMock(return_value=_result([], [], []))
    model = SimpleNamespace()
    adapter = MegaDetectorAdapter(
        model_path,
        config_path,
        loader=MagicMock(return_value=model),
        inference=inference,
    )

    assert adapter.detect(image) == ()
    inference.assert_called_once_with(image, model)


def test_adapter_skips_boxes_without_visible_area_after_clipping(
    tmp_path: Path,
) -> None:
    model_path, config_path = _files(tmp_path)
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    inference = MagicMock(
        return_value=_result([[-1, -2, 1, 0], [-1, 1, 4, 4]], [0.8, 0.7], [0, 0])
    )
    adapter = MegaDetectorAdapter(
        model_path,
        config_path,
        loader=MagicMock(return_value=object()),
        inference=inference,
    )

    detections = adapter.detect(image)

    assert len(detections) == 1
    assert detections[0].box == pytest.approx((0.0, 0.1, 0.4, 0.4))


def test_adapter_requests_zero_confidence_from_v6_model(tmp_path: Path) -> None:
    model_path, config_path = _files(tmp_path)
    image = np.zeros((8, 10, 3), dtype=np.uint8)
    model = SimpleNamespace(
        single_image_detection=MagicMock(
            return_value=_result([[1, 1, 4, 4]], [0.0], [0])
        )
    )
    adapter = MegaDetectorAdapter(
        model_path, config_path, loader=MagicMock(return_value=model)
    )

    detections = adapter.detect(image)

    model.single_image_detection.assert_called_once_with(image, det_conf_thres=0.0)
    assert detections[0].confidence == 0.0


def test_adapter_converts_pil_input_to_rgb_hwc(tmp_path: Path) -> None:
    model_path, config_path = _files(tmp_path)
    image = Image.new("RGB", (10, 8), (12, 34, 56))
    model = object()
    inference = MagicMock(return_value=_result([], [], []))
    adapter = MegaDetectorAdapter(
        model_path,
        config_path,
        loader=MagicMock(return_value=model),
        inference=inference,
    )

    assert adapter.detect(image) == ()
    received_image = inference.call_args.args[0]
    assert received_image.shape == (8, 10, 3)
    assert received_image.dtype == np.uint8
    assert received_image[0, 0].tolist() == [12, 34, 56]


def test_adapter_fails_closed_when_v6_result_omits_detections(
    tmp_path: Path,
) -> None:
    model_path, config_path = _files(tmp_path)
    adapter = MegaDetectorAdapter(
        model_path,
        config_path,
        loader=MagicMock(return_value=SimpleNamespace()),
        inference=MagicMock(return_value={}),
    )

    with pytest.raises(DetectionError, match="inference failed"):
        adapter.detect(np.zeros((10, 10, 3), dtype=np.uint8))


def test_adapter_fails_closed_when_v6_inference_raises(tmp_path: Path) -> None:
    model_path, config_path = _files(tmp_path)
    adapter = MegaDetectorAdapter(
        model_path,
        config_path,
        loader=MagicMock(return_value=SimpleNamespace()),
        inference=MagicMock(side_effect=RuntimeError("inference failed")),
    )

    with pytest.raises(DetectionError, match="inference failed"):
        adapter.detect(np.zeros((10, 10, 3), dtype=np.uint8))


@pytest.mark.parametrize(
    ("boxes", "confidences", "classes", "message"),
    [
        ([[0, 0, 1, 1]], [0.8], [3], "unexpected MegaDetector V6 class ID"),
        ([[0, 0, float("nan"), 1]], [0.8], [0], "finite"),
        ([[1, 1, 1, 2]], [0.8], [0], "positive area"),
        ([[0, 0, 1, 1]], [float("inf")], [0], "confidence"),
    ],
)
def test_adapter_fails_closed_on_invalid_v6_detections(
    tmp_path: Path,
    boxes: list[list[float]],
    confidences: list[float],
    classes: list[int],
    message: str,
) -> None:
    model_path, config_path = _files(tmp_path)
    adapter = MegaDetectorAdapter(
        model_path,
        config_path,
        loader=MagicMock(return_value=object()),
        inference=MagicMock(return_value=_result(boxes, confidences, classes)),
    )

    with pytest.raises(DetectionError, match=message):
        adapter.detect(np.zeros((10, 10, 3), dtype=np.uint8))


def test_adapter_rejects_missing_local_model_or_config(tmp_path: Path) -> None:
    model_path, config_path = _files(tmp_path)
    config_path.unlink()

    with pytest.raises(DetectionError, match="model config is not a file"):
        MegaDetectorAdapter(model_path)


def test_adapter_rejects_unsupported_variant(tmp_path: Path) -> None:
    model_path, config_path = _files(tmp_path)

    with pytest.raises(DetectionError, match="unsupported MegaDetector V6 variant"):
        MegaDetectorAdapter(model_path, config_path, variant="other")
