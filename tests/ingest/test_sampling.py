from fractions import Fraction

import pytest

from bird_recognition.ingest.models import (
    ProcessingError,
    SampledFrame,
    ValidationError,
)
from bird_recognition.ingest.video import sample_decoded_frames


class FrameImage:
    def __init__(self, marker: int) -> None:
        self.marker = marker
        self.size = (20, 10)


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_sample_decoded_frames_rejects_invalid_interval(interval: float) -> None:
    with pytest.raises(ValidationError):
        list(sample_decoded_frames([], interval))


def test_sample_decoded_frames_starts_at_zero_and_uses_pts_elapsed_time() -> None:
    decoded = [
        (i, pts, Fraction(1, 50), FrameImage(i))
        for i, pts in enumerate((100, 105, 110, 115, 120, 125))
    ]

    result = list(sample_decoded_frames(decoded, 0.2))

    assert [(frame.frame_number, frame.elapsed_seconds) for frame in result] == [
        (0, 0.0),
        (2, 0.2),
        (4, 0.4),
    ]


def test_sample_decoded_frames_handles_variable_timing_and_short_clip() -> None:
    decoded = [
        (i, pts, Fraction(1, 10), FrameImage(i)) for i, pts in enumerate((0, 1, 4, 13))
    ]

    result = list(sample_decoded_frames(decoded, 0.5))

    assert [frame.frame_number for frame in result] == [0, 3]
    assert [frame.elapsed_seconds for frame in result] == [0.0, 1.3]


def test_sample_decoded_frames_rejects_missing_or_nonmonotonic_pts() -> None:
    decoded = [
        (0, 0, Fraction(1, 10), FrameImage(0)),
        (1, None, Fraction(1, 10), FrameImage(1)),
    ]

    with pytest.raises(ProcessingError, match="PTS"):
        list(sample_decoded_frames(decoded, 1.0))


def test_sampled_frame_keeps_dimensions_and_image() -> None:
    image = FrameImage(7)

    frame = SampledFrame(7, 0.0, 20, 10, image)

    assert frame.image is image
