import pytest

from bird_recognition.ingest.models import (
    Detection,
    DetectionCategory,
    FrameOutcome,
    IngestSettings,
)
from bird_recognition.ingest.pipeline import filter_detections


@pytest.mark.parametrize(
    ("detections", "outcome"),
    [
        (
            [Detection(DetectionCategory.ANIMAL, 0.2, (0.1, 0.1, 0.8, 0.8))],
            FrameOutcome.RETAINED,
        ),
        (
            [Detection(DetectionCategory.ANIMAL, 0.19, (0.1, 0.1, 0.8, 0.8))],
            FrameOutcome.NO_ANIMAL,
        ),
        (
            [Detection(DetectionCategory.OTHER, 0.99, (0.1, 0.1, 0.8, 0.8))],
            FrameOutcome.NO_ANIMAL,
        ),
        (
            [Detection(DetectionCategory.PERSON, 0.2, (0.1, 0.1, 0.8, 0.8))],
            FrameOutcome.PERSON_EXCLUDED,
        ),
        (
            [
                Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8)),
                Detection(DetectionCategory.PERSON, 0.2, (0.1, 0.1, 0.8, 0.8)),
            ],
            FrameOutcome.PERSON_EXCLUDED,
        ),
    ],
)
def test_filter_detections_applies_category_threshold_and_person_precedence(
    detections: list[Detection],
    outcome: FrameOutcome,
) -> None:
    result = filter_detections(4, detections, IngestSettings())

    assert result.outcome is outcome
    assert all(
        d.qualifies
        == (
            d.category in {DetectionCategory.ANIMAL, DetectionCategory.PERSON}
            and d.confidence >= 0.2
        )
        for d in result.detections
    )


def test_filter_detections_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        Detection(DetectionCategory.ANIMAL, float("nan"), (0.1, 0.1, 0.8, 0.8))


def test_filter_detections_fails_closed_on_inference_error() -> None:
    result = filter_detections(
        2, None, IngestSettings(), failure_reason="inference failed"
    )

    assert result.outcome is FrameOutcome.FAILED
    assert not result.crops
