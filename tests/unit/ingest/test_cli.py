import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.cli import _build_parser, main
from bird_recognition.ingest import pipeline
from bird_recognition.ingest.models import (
    CaptureTime,
    Detection,
    DetectionCategory,
    SampledFrame,
)
from tests.unit.ingest.fakes import FakeDetector, ScriptedDetector


def test_ingest_cli_uses_dotenv_defaults_and_cli_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment_names = (
        "BIRD_RECOGNITION_INTERVAL",
        "BIRD_RECOGNITION_ANIMAL_THRESHOLD",
        "BIRD_RECOGNITION_PERSON_THRESHOLD",
        "BIRD_RECOGNITION_EXTENSIONS",
        "BIRD_RECOGNITION_MEGADETECTOR_MODEL",
        "BIRD_RECOGNITION_MEGADETECTOR_CONFIG",
    )
    for name in environment_names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            (
                "BIRD_RECOGNITION_INTERVAL=2.5",
                "BIRD_RECOGNITION_ANIMAL_THRESHOLD=0.4",
                "BIRD_RECOGNITION_PERSON_THRESHOLD=0.6",
                "BIRD_RECOGNITION_EXTENSIONS=.mp4,.mkv",
                "BIRD_RECOGNITION_MEGADETECTOR_MODEL=env-model.ckpt",
                "BIRD_RECOGNITION_MEGADETECTOR_CONFIG=env-config.yaml",
            )
        ),
        encoding="utf-8",
    )

    parser = _build_parser()
    default_arguments = parser.parse_args(
        ["ingest", "--input", "videos", "--output", "crops"]
    )
    overridden_arguments = parser.parse_args(
        [
            "ingest",
            "--input",
            "videos",
            "--output",
            "crops",
            "--interval",
            "3.0",
            "--model",
            "cli-model.ckpt",
            "--model-config",
            "cli-config.yaml",
        ]
    )

    assert default_arguments.interval == 2.5
    assert default_arguments.animal_threshold == 0.4
    assert default_arguments.person_threshold == 0.6
    assert default_arguments.extensions == ".mp4,.mkv"
    assert default_arguments.model == Path("env-model.ckpt")
    assert default_arguments.model_config == Path("env-config.yaml")
    assert overridden_arguments.interval == 3.0
    assert overridden_arguments.model == Path("cli-model.ckpt")
    assert overridden_arguments.model_config == Path("cli-config.yaml")


def test_ingest_cli_process_environment_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIRD_RECOGNITION_INTERVAL", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("BIRD_RECOGNITION_INTERVAL=2.5\n", encoding="utf-8")
    monkeypatch.setenv("BIRD_RECOGNITION_INTERVAL", "4.0")

    parser = _build_parser()
    arguments = parser.parse_args(["ingest", "--input", "videos", "--output", "crops"])
    overridden_arguments = parser.parse_args(
        [
            "ingest",
            "--input",
            "videos",
            "--output",
            "crops",
            "--interval",
            "5.0",
        ]
    )

    assert arguments.interval == 4.0
    assert overridden_arguments.interval == 5.0


def test_ingest_cli_ignores_blank_dotenv_model_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BIRD_RECOGNITION_MEGADETECTOR_MODEL", raising=False)
    monkeypatch.delenv("BIRD_RECOGNITION_MEGADETECTOR_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "BIRD_RECOGNITION_MEGADETECTOR_MODEL=\nBIRD_RECOGNITION_MEGADETECTOR_CONFIG=\n",
        encoding="utf-8",
    )

    arguments = _build_parser().parse_args(
        ["ingest", "--input", "videos", "--output", "crops"]
    )

    assert arguments.model is None
    assert arguments.model_config is None


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


@pytest.mark.parametrize(
    ("capture_start", "capture_timezone", "expected_times"),
    [
        pytest.param(
            CaptureTime("2025-05-01T12:30:00+05:30", "+05:30"),
            "+05:30",
            {
                0: "2025-05-01T12:30:00+05:30",
                2: "2025-05-01T12:30:01+05:30",
            },
            id="offset-capture-start",
        ),
        pytest.param(
            CaptureTime(),
            None,
            {0: None, 2: None},
            id="unknown-capture-start",
        ),
    ],
)
def test_ingest_cli_reopens_persisted_crop_provenance(
    tiny_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capture_start: CaptureTime,
    capture_timezone: str | None,
    expected_times: dict[int, str | None],
) -> None:
    from bird_recognition import ingest

    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / tiny_video.name
    source.write_bytes(tiny_video.read_bytes())
    output_root = tmp_path / "output"
    monkeypatch.setattr(
        ingest.pipeline, "capture_start_for_video", lambda _path: capture_start
    )
    detector = FakeDetector(
        [Detection(DetectionCategory.ANIMAL, 0.9, (0.25, 0.25, 0.75, 0.75))]
    )

    result = main(
        ["ingest", "--input", str(input_root), "--output", str(output_root)],
        detector=detector,
    )

    assert result == 0
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT r.status AS run_status,rs.status AS source_status,"
            "s.capture_start,s.capture_timezone,f.frame_number,"
            "f.elapsed_seconds AS frame_elapsed,f.capture_time AS frame_capture_time,"
            "f.capture_timezone AS frame_timezone,f.lighting AS frame_lighting,"
            "d.confidence AS detection_confidence,c.elapsed_seconds AS crop_elapsed,"
            "c.capture_time AS crop_capture_time,c.capture_timezone AS crop_timezone,"
            "c.lighting AS crop_lighting,c.confidence,c.frame_width,c.frame_height,"
            "c.image_path,c.crop_sha256,c.box_left,c.box_top,c.box_right,c.box_bottom "
            "FROM animal_crop c "
            "JOIN sampled_frame f USING(source_id,settings_fingerprint,frame_number) "
            "JOIN detection d USING(detection_id,source_id,settings_fingerprint,"
            "frame_number) "
            "JOIN run_source rs USING(source_id,settings_fingerprint,run_id) "
            "JOIN source_video s USING(source_id) "
            "JOIN ingestion_run r USING(run_id) "
            "ORDER BY f.frame_number"
        ).fetchall()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert len(rows) == 2
    assert foreign_key_errors == []
    for row in rows:
        frame_number = row["frame_number"]
        assert frame_number in expected_times
        expected_time = expected_times[frame_number]
        assert row["run_status"] == "complete"
        assert row["source_status"] == "processed"
        assert row["capture_start"] == capture_start.local_time
        assert row["capture_timezone"] == capture_timezone
        assert row["frame_elapsed"] == row["crop_elapsed"]
        assert row["frame_capture_time"] == row["crop_capture_time"] == expected_time
        assert row["frame_timezone"] == row["crop_timezone"] == capture_timezone
        assert row["frame_lighting"] == row["crop_lighting"]
        assert row["frame_lighting"] in {"day", "night", "unknown"}
        assert row["confidence"] == row["detection_confidence"] == 0.9
        assert (row["frame_width"], row["frame_height"]) == (32, 24)
        assert (
            row["box_left"],
            row["box_top"],
            row["box_right"],
            row["box_bottom"],
        ) == (8, 6, 24, 18)
        image_path = (output_root / row["image_path"]).resolve()
        assert output_root.resolve() in image_path.parents
        assert hashlib.sha256(image_path.read_bytes()).hexdigest() == row["crop_sha256"]
        with Image.open(image_path) as image:
            assert image.size == (
                row["box_right"] - row["box_left"],
                row["box_bottom"] - row["box_top"],
            )


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
    tiny_video: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BIRD_RECOGNITION_MEGADETECTOR_CONFIG", raising=False)
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


def test_ingest_cli_reports_partial_failure_counts_and_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    (input_root / "a-broken.mp4").write_bytes(b"not a video")
    (input_root / "b-camera.mp4").write_bytes(b"controlled source")
    (input_root / "c-camera.mp4").write_bytes(b"successful source")
    frame = SampledFrame(0, 0.0, 32, 24, Image.new("RGB", (32, 24), "blue"))
    monkeypatch.setattr(
        pipeline, "sample_video", lambda _path, _settings: iter((frame,))
    )
    monkeypatch.setattr(
        pipeline, "capture_start_for_video", lambda _path: CaptureTime()
    )
    detector = ScriptedDetector(
        [
            RuntimeError("controlled inference failure"),
            [Detection(DetectionCategory.ANIMAL, 0.9, (0.1, 0.1, 0.8, 0.8))],
        ]
    )
    result = main(
        ["ingest", "--input", str(input_root), "--output", str(tmp_path / "output")],
        detector=detector,
    )
    captured = capsys.readouterr()
    assert result == 1
    assert "Run status: partial_failure" in captured.out
    assert "Processed Sources: 1" in captured.out
    assert "Failed Sources: 2" in captured.out
    assert "Sampled: 3" in captured.out
    assert "Retained: 1" in captured.out
    assert "Failed: 2" in captured.out
    assert "Crops: 1" in captured.out
    assert "controlled inference failure" in captured.err
