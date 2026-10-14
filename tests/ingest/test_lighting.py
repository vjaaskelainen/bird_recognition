import pytest
from PIL import Image

from bird_recognition.ingest.lighting import RULE_VERSION, classify_image
from bird_recognition.ingest.models import Lighting


@pytest.mark.parametrize("color", [(255, 150, 30), (35, 170, 70), (70, 100, 210)])
def test_classify_image_detects_clear_color_daylight(
    color: tuple[int, int, int],
) -> None:
    assert classify_image(Image.new("RGB", (16, 16), color)) is Lighting.DAY


def test_classify_image_detects_monochrome_infrared_night() -> None:
    assert classify_image(Image.new("RGB", (16, 16), (90, 90, 90))) is Lighting.NIGHT


def test_classify_image_returns_unknown_for_ambiguous_evidence() -> None:
    assert classify_image(Image.new("RGB", (16, 16), (30, 40, 50))) is Lighting.UNKNOWN


def test_lighting_classifier_exposes_rule_version() -> None:
    assert RULE_VERSION == "pixel-evidence-v1"
