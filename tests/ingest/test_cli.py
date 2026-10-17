from pathlib import Path

import pytest

from bird_recognition.cli import main
from bird_recognition.ingest.models import Detection, DetectionCategory
from tests.ingest.fakes import FakeDetector


def test_ingest_cli_requires_paths() -> None:
    with pytest.raises(SystemExit) as result:
        main(["ingest"])

    assert result.value.code == 2


def test_ingest_cli_help_prints_defaults(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as result:
        main(["ingest", "--help"])

    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "animal threshold=0.2" in help_text
    assert "MDV6-mit-yolov9-c" in help_text
    assert "--model-config" in help_text


@pytest.mark.parametrize(
    ("option", "value"),
    [("--interval", "nan"), ("--interval", "0"), ("--animal-threshold", "1.1")],
)
def test_ingest_cli_rejects_invalid_numeric_options_before_output(
    tmp_path: Path, option: str, value: str
) -> None:
    input_root = tmp_path / "input"
    output_root = tmp_path / "output"
    input_root.mkdir()

    result = main(
        [
            "ingest",
            "--input",
            str(input_root),
            "--output",
            str(output_root),
            option,
            value,
        ],
        detector=FakeDetector(),
    )

    assert result == 2
    assert not output_root.exists()


def test_ingest_cli_processes_video_with_injected_detector(
    tiny_video: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    video_path = input_root / tiny_video.name
    video_path.write_bytes(tiny_video.read_bytes())
    output_root = tmp_path / "output"
    detector = FakeDetector(
        [
            Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.5, 0.8)),
            Detection(DetectionCategory.ANIMAL, 0.8, (0.5, 0.1, 0.9, 0.8)),
        ]
    )

    result = main(
        ["ingest", "--input", str(input_root), "--output", str(output_root)],
        detector=detector,
    )

    assert result == 0
    assert detector.calls > 0
    assert "Run status: complete" in capsys.readouterr().out
    assert len(list((output_root / "crops").rglob("*.jpg"))) == 4


def test_ingest_cli_person_detection_prevents_all_frame_crops(
    tiny_video: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    video_path = input_root / tiny_video.name
    video_path.write_bytes(tiny_video.read_bytes())
    detector = FakeDetector(
        [
            Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8)),
            Detection(DetectionCategory.PERSON, 0.9, (0.2, 0.2, 0.7, 0.7)),
        ]
    )

    result = main(
        ["ingest", "--input", str(input_root), "--output", str(tmp_path / "output")],
        detector=detector,
    )

    assert result == 0
    assert not list((tmp_path / "output" / "crops").rglob("*.jpg"))


def test_ingest_cli_empty_input_succeeds_without_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()

    result = main(
        ["ingest", "--input", str(input_root), "--output", str(tmp_path / "output")]
    )

    assert result == 0
    assert "Run status: no_input" in capsys.readouterr().out


def test_ingest_cli_reports_unreadable_video_failure(
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "broken.mp4").write_bytes(b"not a video")

    result = main(
        ["ingest", "--input", str(input_root), "--output", str(tmp_path / "output")],
        detector=FakeDetector(),
    )

    assert result == 1


def test_ingest_cli_rejects_missing_local_model_config_before_output(
    tiny_video: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / tiny_video.name).write_bytes(tiny_video.read_bytes())
    model_path = tmp_path / "MDV6-mit-yolov9-c.ckpt"
    model_path.write_bytes(b"local test weights")
    output_root = tmp_path / "output"

    result = main(
        [
            "ingest",
            "--input",
            str(input_root),
            "--output",
            str(output_root),
            "--model",
            str(model_path),
        ]
    )

    assert result == 2
    assert not output_root.exists()
    assert "model config cannot be resolved" in capsys.readouterr().err
