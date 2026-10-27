from collections.abc import Callable

import pytest
from PIL import Image

from bird_recognition.ingest.crops import crop_image, normalized_box_to_pixels
from bird_recognition.ingest.models import ValidationError


@pytest.mark.parametrize(
    ("box", "size", "expected"),
    [
        ((0.1, 0.2, 0.5, 0.6), (100, 50), (10, 10, 50, 30)),
        ((-0.2, -0.1, 0.4, 0.5), (20, 10), (0, 0, 8, 5)),
        ((0.8, 0.7, 1.2, 1.5), (10, 10), (8, 7, 10, 10)),
    ],
)
def test_normalized_box_to_pixels_clips_and_uses_exclusive_edges(
    box: tuple[float, float, float, float],
    size: tuple[int, int],
    expected: tuple[int, int, int, int],
) -> None:
    assert normalized_box_to_pixels(box, *size) == expected


@pytest.mark.parametrize(
    "box",
    [
        (0.5, 0.1, 0.4, 0.9),
        (0.1, 0.2, 0.1, 0.8),
        (float("nan"), 0, 1, 1),
        (0, 0, 0, 0),
    ],
)
def test_normalized_box_to_pixels_rejects_malformed_or_empty_box(
    box: tuple[float, float, float, float],
) -> None:
    with pytest.raises(ValidationError):
        normalized_box_to_pixels(box, 20, 10)


def test_crop_image_matches_pixel_box(
    frame_factory: Callable[..., Image.Image],
) -> None:
    image = frame_factory(size=(32, 24))

    crop, box = crop_image(image, (0.25, 0.25, 0.75, 0.75))

    assert box == (8, 6, 24, 18)
    assert crop.size == (16, 12)


def test_crop_image_expands_context_and_clips_at_frame_edges() -> None:
    image = Image.new("RGB", (100, 80), "white")

    crop, box = crop_image(image, (0.0, 0.25, 0.2, 0.75), context=0.1)

    assert box == (0, 16, 23, 64)
    assert crop.size == (23, 48)


def test_crop_image_context_preserves_elongated_rectangle() -> None:
    image = Image.new("RGB", (200, 80), "white")

    crop, box = crop_image(image, (0.1, 0.4, 0.9, 0.6), context=0.1)

    assert box == (3, 30, 196, 50)
    assert crop.size == (193, 20)
