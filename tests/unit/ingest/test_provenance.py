import sqlite3
from contextlib import closing
from pathlib import Path

from PIL import Image

from bird_recognition.cli import main
from bird_recognition.ingest.models import Detection, DetectionCategory
from tests.unit.ingest.fakes import FakeDetector


def test_cli_persists_crop_provenance_and_saved_region(
    tiny_video: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / tiny_video.name
    source.write_bytes(tiny_video.read_bytes())
    output_root = tmp_path / "output"
    detector = FakeDetector(
        [Detection(DetectionCategory.ANIMAL, 0.9, (0.25, 0.25, 0.75, 0.75))]
    )

    result = main(
        ["ingest", "--input", str(input_root), "--output", str(output_root)],
        detector=detector,
    )

    assert result == 0
    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        crop_rows = connection.execute(
            "SELECT image_path,box_left,box_top,box_right,box_bottom,frame_width,"
            "frame_height,confidence,elapsed_seconds,capture_time,capture_timezone,"
            "lighting FROM animal_crop ORDER BY frame_number"
        ).fetchall()
    assert len(crop_rows) == 2
    for row in crop_rows:
        (
            image_path,
            left,
            top,
            right,
            bottom,
            width,
            height,
            confidence,
            elapsed,
            capture,
            zone,
            light,
        ) = row
        assert confidence == 0.9
        assert elapsed >= 0
        assert capture is None
        assert zone is None
        assert light in {"day", "night", "unknown"}
        with Image.open(output_root / image_path) as image:
            assert image.size == (right - left, bottom - top)
        assert 0 <= left < right <= width
        assert 0 <= top < bottom <= height
