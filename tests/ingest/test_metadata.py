import math

import pytest

from bird_recognition.ingest.models import (
    Detection,
    DetectionCategory,
    IngestSettings,
    SampledFrame,
    ValidationError,
)


def test_settings_identity_validation_rejects_nonfinite_interval() -> None:
    with pytest.raises(ValidationError):
        IngestSettings(interval=math.inf)


@pytest.mark.parametrize("threshold", [-0.1, 1.1, math.nan, math.inf])
def test_settings_validation_rejects_threshold_outside_finite_unit_interval(
    threshold: float,
) -> None:
    with pytest.raises(ValidationError):
        IngestSettings(animal_threshold=threshold)


def test_detection_validation_rejects_invalid_confidence_and_box() -> None:
    with pytest.raises(ValidationError):
        Detection(DetectionCategory.ANIMAL, math.nan, (0.1, 0.1, 0.8, 0.8))
    with pytest.raises(ValidationError):
        Detection(DetectionCategory.ANIMAL, 0.9, (0.8, 0.1, 0.2, 0.8))


def test_sampled_frame_validation_requires_positive_dimensions() -> None:
    with pytest.raises(ValidationError):
        SampledFrame(0, 0.0, 0, 10, object())


def test_settings_record_lighting_evidence_thresholds() -> None:
    settings = IngestSettings()

    assert dict(settings.lighting_settings)["day_min_luma"] == 0.28
