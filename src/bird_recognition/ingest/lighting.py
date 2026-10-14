"""Conservative image-evidence lighting classifier."""

from __future__ import annotations

from collections.abc import Sequence

from bird_recognition.ingest.models import Lighting, ValidationError

RULE_VERSION = "pixel-evidence-v1"
RULE_THRESHOLDS = {
    "day_min_mean_saturation": 0.16,
    "day_min_luma": 0.28,
    "night_max_mean_saturation": 0.09,
    "night_max_luma": 0.82,
    "night_min_luma": 0.03,
}


def classify_lighting(pixels: Sequence[Sequence[Sequence[int]]]) -> Lighting:
    """Classify clear daylight-color or monochrome low-light evidence."""
    if not pixels or not pixels[0]:
        raise ValidationError("lighting classifier requires a non-empty image")
    count = 0
    saturation_total = 0.0
    luma_total = 0.0
    for row in pixels:
        for pixel in row:
            if len(pixel) < 3:
                raise ValidationError("lighting image must contain RGB pixels")
            red, green, blue = (component / 255.0 for component in pixel[:3])
            maximum = max(red, green, blue)
            minimum = min(red, green, blue)
            saturation_total += 0.0 if maximum == 0 else (maximum - minimum) / maximum
            luma_total += 0.2126 * red + 0.7152 * green + 0.0722 * blue
            count += 1
    if count == 0:
        raise ValidationError("lighting classifier requires image pixels")
    saturation = saturation_total / count
    luma = luma_total / count
    if (
        saturation >= RULE_THRESHOLDS["day_min_mean_saturation"]
        and luma >= RULE_THRESHOLDS["day_min_luma"]
    ):
        return Lighting.DAY
    if (
        saturation <= RULE_THRESHOLDS["night_max_mean_saturation"]
        and RULE_THRESHOLDS["night_min_luma"]
        <= luma
        <= RULE_THRESHOLDS["night_max_luma"]
    ):
        return Lighting.NIGHT
    return Lighting.UNKNOWN


def classify_image(image: object) -> Lighting:
    """Classify a Pillow-compatible image using deterministic RGB statistics."""
    try:
        rgb = image.convert("RGB")  # type: ignore[attr-defined]
        width, height = rgb.size  # type: ignore[attr-defined]
        pixels = rgb.resize((min(width, 64), min(height, 64))).load()  # type: ignore[attr-defined]
        sampled = [
            [pixels[x, y] for x in range(min(width, 64))]
            for y in range(min(height, 64))
        ]
        return classify_lighting(sampled)
    except Exception as error:
        if isinstance(error, ValidationError):
            raise
        raise ValidationError("unable to inspect image lighting evidence") from error
