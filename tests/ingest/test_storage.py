import hashlib
import sqlite3
from pathlib import Path

import pytest

from bird_recognition.ingest.manifest import Manifest
from bird_recognition.ingest.models import StorageError


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
