import pytest
from PIL import Image

from bird_recognition.ingest.lighting import (
    RULE_THRESHOLDS,
    RULE_VERSION,
    classify_image,
)
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


@pytest.mark.parametrize(
    ("colors", "expected"),
    [
        (
            ((54, 100, 48), (130, 90, 55), (95, 140, 190)),
            Lighting.DAY,
        ),
        (
            ((45, 45, 45), (80, 80, 80), (120, 120, 120)),
            Lighting.NIGHT,
        ),
        (
            ((100, 94, 90), (150, 140, 135), (190, 180, 175)),
            Lighting.UNKNOWN,
        ),
    ],
)
def test_classify_image_classifies_patterned_field_evidence(
    colors: tuple[tuple[int, int, int], ...], expected: Lighting
) -> None:
    image = Image.new("RGB", (24, 24))
    image.putdata(
        [colors[(x // 8 + y // 8) % len(colors)] for y in range(24) for x in range(24)]
    )

    assert classify_image(image) is expected


def test_lighting_classifier_exposes_all_versioned_thresholds() -> None:
    assert RULE_THRESHOLDS == {
        "day_min_mean_saturation": 0.16,
        "day_min_luma": 0.28,
        "night_max_mean_saturation": 0.09,
        "night_max_luma": 0.82,
        "night_min_luma": 0.03,
    }
