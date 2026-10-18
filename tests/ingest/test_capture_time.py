import pytest

from bird_recognition.ingest.models import CaptureTime
from bird_recognition.ingest.video import derive_capture_time, parse_capture_start


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"com.apple.quicktime.creationdate": "2025-05-01T12:30:00-04:00"},
            CaptureTime("2025-05-01T12:30:00-04:00", "-04:00"),
        ),
        (
            {"camera.capture_start": "2025-05-01T12:30:00"},
            CaptureTime("2025-05-01T12:30:00", None),
        ),
        ({"creation_time": "2025-05-01T12:30:00Z"}, CaptureTime()),
        ({"com.apple.quicktime.creationdate": "not-a-date"}, CaptureTime()),
        ({}, CaptureTime()),
    ],
)
def test_parse_capture_start_accepts_only_known_capture_tags(
    metadata: dict[str, str], expected: CaptureTime
) -> None:
    assert parse_capture_start(metadata) == expected


def test_parse_capture_start_rejects_conflicting_capture_tags() -> None:
    parsed = parse_capture_start(
        {
            "com.apple.quicktime.creationdate": "2025-05-01T12:30:00-04:00",
            "camera.capture_start": "2025-05-01T13:30:00-04:00",
        }
    )

    assert parsed == CaptureTime()


def test_parse_capture_start_rejects_conflicts_across_metadata_scopes() -> None:
    parsed = parse_capture_start(
        {
            "com.apple.quicktime.creationdate": "2025-05-01T12:30:00-04:00",
            "stream0:com.apple.quicktime.creationdate": "2025-05-01T13:30:00-04:00",
        }
    )

    assert parsed == CaptureTime()


def test_derive_capture_time_adds_elapsed_seconds_without_losing_timezone() -> None:
    start = CaptureTime("2025-05-01T12:30:00-04:00", "-04:00")

    assert derive_capture_time(start, 10.5) == "2025-05-01T12:30:10.500000-04:00"


def test_derive_capture_time_keeps_local_time_timezone_unknown() -> None:
    start = CaptureTime("2025-05-01T12:30:00", None)

    result = derive_capture_time(start, 5)

    assert result == "2025-05-01T12:30:05"
    assert start.timezone is None


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        (
            {"com.apple.quicktime.creationdate": "2025-05-01T12:30:00+00:00"},
            CaptureTime("2025-05-01T12:30:00+00:00", "+00:00"),
        ),
        (
            {"camera.capture_start": "2025-05-01T12:30:00+05:30"},
            CaptureTime("2025-05-01T12:30:00+05:30", "+05:30"),
        ),
        (
            {"camera.capture_start": "2025-05-01T12:30:00-07:00"},
            CaptureTime("2025-05-01T12:30:00-07:00", "-07:00"),
        ),
    ],
)
def test_parse_capture_start_preserves_reliable_timezone_offsets(
    metadata: dict[str, str], expected: CaptureTime
) -> None:
    assert parse_capture_start(metadata) == expected


def test_derive_capture_time_adds_pts_elapsed_seconds_to_offset_start() -> None:
    start = CaptureTime("2025-05-01T23:59:59+05:30", "+05:30")

    assert derive_capture_time(start, 1.25) == "2025-05-02T00:00:00.250000+05:30"


def test_parse_capture_start_does_not_fall_back_to_generic_metadata() -> None:
    parsed = parse_capture_start(
        {
            "creation_time": "2025-05-01T12:30:00+00:00",
            "modification_time": "2025-05-01T12:31:00+00:00",
        }
    )

    assert parsed == CaptureTime()
    assert derive_capture_time(parsed, 12.0) is None


@pytest.mark.parametrize(
    "metadata",
    [
        {"camera.capture_start": ""},
        {"camera.capture_start": "2025-02-30T12:30:00"},
        {
            "camera.capture_start": "2025-05-01T12:30:00+02:00",
            "com.apple.quicktime.creationdate": "2025-05-01T12:30:00+03:00",
        },
    ],
)
def test_parse_capture_start_preserves_unknown_for_unreliable_metadata(
    metadata: dict[str, str],
) -> None:
    assert parse_capture_start(metadata) == CaptureTime()
