from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from bird_recognition.cli import extract_frame, main
from bird_recognition.ingest.models import ProcessingError, ValidationError
from bird_recognition.ingest.video import TimedImage


@pytest.fixture
def tiny_video(tiny_video: Path, tmp_path: Path) -> Path:
    input_root = tmp_path / "input"
    input_root.mkdir()
    return tiny_video.replace(input_root / tiny_video.name)


@pytest.mark.parametrize(
    ("timestamp", "expected_color"),
    [(0.0, (40, 120, 210)), (0.25, (210, 80, 30)), (1.0, (30, 180, 90))],
)
def test_extract_frame_valid_timestamp_saves_expected_png(
    tiny_video: Path,
    tmp_path: Path,
    timestamp: float,
    expected_color: tuple[int, int, int],
) -> None:
    output = tmp_path / "frames" / "nested"

    result = extract_frame(tiny_video, timestamp, output)

    assert result == output / f"tiny.mp4_frame_{timestamp}s.png"
    with Image.open(result) as image:
        assert image.format == "PNG"
        assert image.size == (32, 24)
        assert all(
            abs(actual - expected) < 10
            for actual, expected in zip(
                image.getpixel((16, 12)), expected_color, strict=True
            )
        )


@pytest.mark.parametrize("timestamp", [-1.0, float("nan"), float("inf")])
def test_extract_frame_invalid_timestamp_rejects_before_output(
    tiny_video: Path, tmp_path: Path, timestamp: float
) -> None:
    output = tmp_path / "frames"

    with pytest.raises(ValidationError, match="finite and non-negative"):
        extract_frame(tiny_video, timestamp, output)

    assert not output.exists()


def test_extract_frame_existing_image_preserves_contents(
    tiny_video: Path, tmp_path: Path
) -> None:
    result = extract_frame(tiny_video, 0.0, tmp_path / "frames")
    original = result.read_bytes()

    with pytest.raises(ValidationError, match="already exists"):
        extract_frame(tiny_video, 0.0, result.parent)

    assert result.read_bytes() == original


@pytest.mark.parametrize("source_kind", ["missing", "directory"])
def test_extract_frame_invalid_source_rejects_before_output(
    tmp_path: Path, source_kind: str
) -> None:
    source = tmp_path / "source"
    if source_kind == "directory":
        source.mkdir()
    output = tmp_path / "frames"

    with pytest.raises((ValidationError, OSError)):
        extract_frame(source, 0.0, output)

    assert not output.exists()


@pytest.mark.parametrize("destination_kind", ["overlap", "repository", "file"])
def test_extract_frame_unsafe_destination_rejects(
    tiny_video: Path, tmp_path: Path, destination_kind: str
) -> None:
    destinations = {
        "overlap": tiny_video.parent,
        "repository": Path(__file__).resolve().parents[2] / "extracted-frames",
        "file": tmp_path / "output.txt",
    }
    output = destinations[destination_kind]
    if destination_kind == "file":
        output.write_text("keep", encoding="utf-8")

    with pytest.raises(ValidationError):
        extract_frame(tiny_video, 0.0, output)


@pytest.mark.parametrize("timestamp", [0.0, 0.25])
def test_extract_frame_nonzero_start_uses_elapsed_time_and_closes_decoder(
    tmp_path: Path, timestamp: float
) -> None:
    source = tmp_path / "input" / "video.mp4"
    source.parent.mkdir()
    source.touch()
    closed = []

    def decoded() -> Iterator[TimedImage]:
        try:
            for number, color in enumerate(("red", "blue")):
                yield (
                    number,
                    20 + number,
                    Fraction(1, 2),
                    Image.new("RGB", (4, 4), color),
                )
        finally:
            closed.append(True)

    with patch(
        "bird_recognition.cli.iter_video_frames", side_effect=lambda _: decoded()
    ):
        result = extract_frame(source, timestamp, tmp_path / "frames")

    assert closed == [True]
    with Image.open(result) as image:
        assert image.getpixel((0, 0)) == (
            (255, 0, 0) if timestamp == 0 else (0, 0, 255)
        )


@pytest.mark.parametrize("pts_values", [(None,), (0, 0), (1, 0)])
def test_extract_frame_invalid_timing_fails_without_output(
    tmp_path: Path, pts_values: tuple[int | None, ...]
) -> None:
    source = tmp_path / "input" / "video.mp4"
    source.parent.mkdir()
    source.touch()
    output = tmp_path / "frames"

    def decoded() -> Iterator[TimedImage]:
        for number, pts in enumerate(pts_values):
            yield number, pts, Fraction(1, 2), Image.new("RGB", (4, 4))

    with (
        patch(
            "bird_recognition.cli.iter_video_frames", side_effect=lambda _: decoded()
        ),
        pytest.raises(ProcessingError, match="timing"),
    ):
        extract_frame(source, 10.0, output)

    assert not output.exists()


def test_extract_frame_cli_valid_video_succeeds_without_model(
    tiny_video: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "frames"

    result = main(
        [
            "extract-frame",
            "--input",
            str(tiny_video),
            "--timestamp",
            "0.25",
            "--output",
            str(output),
        ]
    )

    assert result == 0
    assert "Saved frame:" in capsys.readouterr().out
    assert len(list(output.glob("*.png"))) == 1


@pytest.mark.parametrize("failure", ["past-end", "broken", "invalid-timestamp"])
def test_extract_frame_cli_failure_reports_exit_code_without_output(
    tiny_video: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    timestamp = "10" if failure == "past-end" else "0"
    if failure == "broken":
        tiny_video.write_bytes(b"not a video")
    if failure == "invalid-timestamp":
        timestamp = "nan"
    output = tmp_path / "frames"

    result = main(
        [
            "extract-frame",
            "--input",
            str(tiny_video),
            "--timestamp",
            timestamp,
            "--output",
            str(output),
        ]
    )

    assert result == (2 if failure == "invalid-timestamp" else 1)
    assert "error:" in capsys.readouterr().err
    assert not output.exists()


def test_extract_frame_cli_missing_arguments_exits_with_usage_error() -> None:
    with pytest.raises(SystemExit) as error:
        main(["extract-frame"])

    assert error.value.code == 2
