"""Helpers that build ingestion manifests for review tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bird_recognition.ingest.manifest import SCHEMA


class ManifestBuilder:
    """Insert minimal ingestion rows using the production schema."""

    def __init__(self, output_root: Path, input_root: Path) -> None:
        self.output_root = output_root
        self.input_root = input_root
        output_root.mkdir(parents=True, exist_ok=True)
        self.path = output_root / "manifest.sqlite3"
        self.connection = sqlite3.connect(self.path)
        self.connection.executescript(SCHEMA)

    def run(
        self,
        run_id: str,
        started_at: str,
        *,
        status: str = "complete",
        interval: float = 1.0,
        threshold: float = 0.2,
    ) -> None:
        self.connection.execute(
            "INSERT INTO ingestion_run (run_id,started_at,completed_at,status,"
            "input_root,output_root,settings_json,settings_fingerprint) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id,
                started_at,
                None if status == "running" else started_at,
                status,
                str(self.input_root),
                str(self.output_root),
                json.dumps({"interval": interval, "animal_threshold": threshold}),
                f"fp-{run_id}",
            ),
        )
        self.connection.commit()

    def video(
        self,
        source_id: str,
        name: str,
        *,
        run_id: str,
        crops: int = 0,
        status: str = "processed",
        failure: str | None = None,
        capture: str | None = None,
        create_file: bool = True,
    ) -> Path:
        path = self.input_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if create_file:
            path.write_bytes(b"video")
        self.connection.execute(
            "INSERT INTO source_video (source_id,original_path,basename,"
            "content_sha256,capture_start) VALUES (?,?,?,?,?)",
            (source_id, str(path.resolve()), path.name, f"sha-{source_id}", capture),
        )
        self.connection.execute(
            "INSERT INTO run_source (run_id,source_id,settings_fingerprint,status,"
            "failure_reason,sampled_count,no_animal_count,retained_count,crop_count) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                source_id,
                f"fp-{run_id}",
                status,
                failure,
                0 if status == "failed" else 3,
                0 if status == "failed" or crops else 3,
                0 if status == "failed" or not crops else 3,
                crops,
            ),
        )
        self.connection.commit()
        return path

    def run_source(
        self,
        run_id: str,
        source_id: str,
        *,
        status: str,
        crops: int = 0,
        failure: str | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO run_source (run_id,source_id,settings_fingerprint,status,"
            "failure_reason,crop_count) VALUES (?,?,?,?,?,?)",
            (run_id, source_id, f"fp-{run_id}", status, failure, crops),
        )
        self.connection.commit()

    def frame(
        self,
        source_id: str,
        run_id: str,
        frame_number: int,
        elapsed: float,
        *,
        outcome: str = "no_animal",
        box: tuple[float, float, float, float] | None = None,
        crop_id: str | None = None,
    ) -> None:
        fingerprint = f"fp-{run_id}"
        self.connection.execute(
            "INSERT INTO sampled_frame (source_id,settings_fingerprint,frame_number,"
            "elapsed_seconds,frame_width,frame_height,lighting,outcome,run_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                fingerprint,
                frame_number,
                elapsed,
                640,
                480,
                "day",
                "retained" if box else outcome,
                run_id,
            ),
        )
        if box is not None:
            self.connection.execute(
                "INSERT INTO detection (detection_id,source_id,settings_fingerprint,"
                "frame_number,category,confidence,box_left,box_top,box_right,"
                "box_bottom,qualifies) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"d{frame_number}",
                    source_id,
                    fingerprint,
                    frame_number,
                    "animal",
                    0.9,
                    *box,
                    1,
                ),
            )
            if crop_id is not None:
                self.connection.execute(
                    "INSERT INTO animal_crop (crop_id,source_id,settings_fingerprint,"
                    "frame_number,detection_id,image_path,crop_sha256,box_left,"
                    "box_top,box_right,box_bottom,frame_width,frame_height,"
                    "confidence,elapsed_seconds,lighting,run_id) VALUES "
                    "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        crop_id,
                        source_id,
                        fingerprint,
                        frame_number,
                        f"d{frame_number}",
                        f"crops/{crop_id}.jpg",
                        "sha",
                        10,
                        10,
                        100,
                        100,
                        640,
                        480,
                        0.9,
                        elapsed,
                        "day",
                        run_id,
                    ),
                )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
