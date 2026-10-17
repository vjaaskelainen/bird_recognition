import os
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.ingest.detection import MegaDetectorAdapter
from bird_recognition.ingest.models import Detection

_SMOKE_MODEL = os.environ.get("BIRD_RECOGNITION_SMOKE_MODEL")
_SMOKE_CONFIG = os.environ.get("BIRD_RECOGNITION_SMOKE_CONFIG")
_SMOKE_IMAGE = os.environ.get("BIRD_RECOGNITION_SMOKE_IMAGE")


@pytest.mark.skipif(
    not all((_SMOKE_MODEL, _SMOKE_CONFIG, _SMOKE_IMAGE)),
    reason="set local V6 smoke model, config, and image environment variables",
)
def test_v6_model_smoke_with_local_weights_and_rgb_image() -> None:
    assert _SMOKE_MODEL is not None
    assert _SMOKE_CONFIG is not None
    assert _SMOKE_IMAGE is not None
    adapter = MegaDetectorAdapter(Path(_SMOKE_MODEL), Path(_SMOKE_CONFIG))
    with Image.open(_SMOKE_IMAGE) as image:
        detections = adapter.detect(image)

    assert isinstance(detections, tuple)
    assert all(isinstance(detection, Detection) for detection in detections)
