from pathlib import Path

from bird_recognition.ingest.manifest import settings_identity, source_identity
from bird_recognition.ingest.models import IngestSettings


def test_source_identity_distinguishes_same_basename_different_paths(
    tmp_path: Path,
) -> None:
    first = tmp_path / "one" / "camera.mp4"
    second = tmp_path / "two" / "camera.mp4"

    assert source_identity(first, "a" * 64) != source_identity(second, "a" * 64)


def test_source_identity_changes_when_content_digest_changes(tmp_path: Path) -> None:
    source = tmp_path / "camera.mp4"

    assert source_identity(source, "a" * 64) != source_identity(source, "b" * 64)


def test_settings_identity_changes_when_effective_settings_change() -> None:
    default_fingerprint = settings_identity(IngestSettings())[1]
    changed_fingerprint = settings_identity(IngestSettings(interval=2.0))[1]

    assert default_fingerprint != changed_fingerprint
