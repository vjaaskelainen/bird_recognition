import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from PIL import Image

from bird_recognition.cli import main
from bird_recognition.ingest.manifest import Manifest
from bird_recognition.ingest.models import (
    Detection,
    DetectionCategory,
    StorageError,
)
from tests.unit.ingest.fakes import FakeDetector


def test_manifest_reopens_with_saved_crop_location_hash_and_box(tmp_path: Path) -> None:
    root = tmp_path / "output"
    image = root / "crops" / "animal.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"synthetic crop")
    manifest = Manifest(root)

    with sqlite3.connect(manifest.database_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO ingestion_run "
            "(run_id,started_at,status,input_root,output_root,settings_json,"
            "settings_fingerprint) "
            "VALUES ('run','now','running','in','out','{}','set')"
        )
        connection.execute(
            "INSERT INTO source_video "
            "VALUES ('source','source.mp4','source.mp4','sha',NULL,NULL)"
        )
        connection.execute(
            "INSERT INTO sampled_frame "
            "VALUES ('source','set',0,0,20,10,NULL,NULL,'unknown',"
            "'retained',NULL,'run')"
        )
        connection.execute(
            "INSERT INTO detection "
            "VALUES ('det','source','set',0,'animal',0.9,0.1,0.1,0.8,0.8,1)"
        )
        connection.execute(
            "INSERT INTO animal_crop "
            "VALUES ('crop','source','set',0,'det','crops/animal.jpg',"
            "?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                hashlib.sha256(image.read_bytes()).hexdigest(),
                2,
                1,
                16,
                8,
                20,
                10,
                0.9,
                0.0,
                None,
                None,
                "unknown",
                "run",
            ),
        )

    reopened = sqlite3.connect(manifest.database_path)
    crop = reopened.execute(
        "SELECT image_path,crop_sha256,box_left,box_top,box_right,box_bottom "
        "FROM animal_crop"
    ).fetchone()
    reopened.close()

    assert crop == (
        "crops/animal.jpg",
        hashlib.sha256(image.read_bytes()).hexdigest(),
        2,
        1,
        16,
        8,
    )
    assert manifest._validate_crop_path(crop[0]) == image.resolve()


def test_manifest_rejects_crop_path_outside_output_root(tmp_path: Path) -> None:
    manifest = Manifest(tmp_path / "output")

    with pytest.raises(StorageError):
        manifest._validate_crop_path("../private.jpg")


def test_completed_ingest_reopens_with_complete_crop_provenance(
    tiny_video: Path, tmp_path: Path
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    source = input_root / tiny_video.name
    source.write_bytes(tiny_video.read_bytes())
    output_root = tmp_path / "output"
    detector = FakeDetector(
        [
            Detection(DetectionCategory.ANIMAL, 0.9, (0.25, 0.25, 0.75, 0.75)),
            Detection(DetectionCategory.ANIMAL, 0.8, (0.0, 0.0, 0.25, 0.25)),
        ]
    )

    assert (
        main(
            ["ingest", "--input", str(input_root), "--output", str(output_root)],
            detector=detector,
        )
        == 0
    )

    with closing(sqlite3.connect(output_root / "manifest.sqlite3")) as connection:
        connection.row_factory = sqlite3.Row
        crops = connection.execute(
            "SELECT c.*,f.frame_width AS source_width,f.frame_height AS source_height,"
            "f.elapsed_seconds AS source_elapsed,f.capture_time AS source_capture_time,"
            "f.capture_timezone AS source_timezone,f.lighting AS source_lighting,"
            "f.run_id AS frame_run_id,d.confidence AS detection_confidence,"
            "d.box_left AS detection_left,d.box_top AS detection_top,"
            "d.box_right AS detection_right,d.box_bottom AS detection_bottom,"
            "rs.run_id AS source_run_id,r.status AS run_status "
            "FROM animal_crop c "
            "JOIN sampled_frame f USING(source_id,settings_fingerprint,frame_number) "
            "JOIN detection d USING(detection_id,source_id,settings_fingerprint,"
            "frame_number) "
            "JOIN run_source rs USING(source_id,settings_fingerprint,run_id) "
            "JOIN ingestion_run r USING(run_id) "
            "ORDER BY c.frame_number,c.detection_id"
        ).fetchall()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        orphan_crops = connection.execute(
            "SELECT COUNT(*) FROM animal_crop c LEFT JOIN sampled_frame f "
            "USING(source_id,settings_fingerprint,frame_number) "
            "WHERE f.frame_number IS NULL"
        ).fetchone()[0]
        run_source = connection.execute(
            "SELECT sampled_count,person_excluded_count,no_animal_count,"
            "retained_count,failed_frame_count,crop_count FROM run_source"
        ).fetchone()

    assert len(crops) == 4
    assert foreign_key_errors == []
    assert orphan_crops == 0
    assert tuple(run_source) == (2, 0, 0, 2, 0, 4)
    assert {row["run_status"] for row in crops} == {"complete"}

    crops_by_frame: dict[int, list[sqlite3.Row]] = {}
    for crop in crops:
        crops_by_frame.setdefault(crop["frame_number"], []).append(crop)
        image_path = (output_root / crop["image_path"]).resolve()
        assert output_root.resolve() in image_path.parents
        assert image_path.is_file()
        assert (
            hashlib.sha256(image_path.read_bytes()).hexdigest() == crop["crop_sha256"]
        )
        assert crop["frame_run_id"] == crop["run_id"] == crop["source_run_id"]
        assert crop["run_status"] == "complete"
        assert crop["capture_time"] is None
        assert crop["capture_timezone"] is None
        assert crop["source_capture_time"] is None
        assert crop["source_timezone"] is None
        assert crop["elapsed_seconds"] == crop["source_elapsed"]
        assert crop["frame_width"] == crop["source_width"] == 32
        assert crop["frame_height"] == crop["source_height"] == 24
        assert crop["lighting"] == crop["source_lighting"]
        assert crop["confidence"] == crop["detection_confidence"]
        assert 0 <= crop["box_left"] < crop["box_right"] <= crop["frame_width"]
        assert 0 <= crop["box_top"] < crop["box_bottom"] <= crop["frame_height"]
        expected_box = (
            (6, 4, 26, 20) if crop["detection_confidence"] == 0.9 else (0, 0, 9, 7)
        )
        assert (
            crop["box_left"],
            crop["box_top"],
            crop["box_right"],
            crop["box_bottom"],
        ) == expected_box
        assert (
            crop["detection_left"],
            crop["detection_top"],
            crop["detection_right"],
            crop["detection_bottom"],
        ) == (
            (0.25, 0.25, 0.75, 0.75)
            if crop["detection_confidence"] == 0.9
            else (0.0, 0.0, 0.25, 0.25)
        )
        with Image.open(image_path) as image:
            assert image.size == (
                crop["box_right"] - crop["box_left"],
                crop["box_bottom"] - crop["box_top"],
            )

    assert set(crops_by_frame) == {0, 2}
    for frame_crops in crops_by_frame.values():
        assert len({crop["lighting"] for crop in frame_crops}) == 1
        assert len({crop["frame_width"] for crop in frame_crops}) == 1
        assert len({crop["frame_height"] for crop in frame_crops}) == 1
