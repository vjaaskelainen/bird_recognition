from __future__ import annotations

from pathlib import Path

import pytest

from bird_recognition.api.settings import load_settings


def test_load_settings_precedence_override_before_environment_and_dotenv(
    tmp_path: Path,
) -> None:
    settings = load_settings(
        {"host": "0.0.0.0", "port": 9000},
        process_environment={
            "BIRD_RECOGNITION_API_HOST": "127.0.0.2",
            "BIRD_RECOGNITION_API_PORT": "9001",
            "BIRD_RECOGNITION_API_KEY": "env-key",
        },
        dotenv_environment={
            "BIRD_RECOGNITION_API_HOST": "localhost",
            "BIRD_RECOGNITION_API_PORT": "9002",
            "BIRD_RECOGNITION_API_KEY": "dotenv-key",
        },
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.api_key == "env-key"


def test_load_settings_reads_dotenv_and_path_list() -> None:
    settings = load_settings(
        process_environment={},
        dotenv_environment={
            "BIRD_RECOGNITION_API_HOST": "localhost",
            "BIRD_RECOGNITION_API_PORT": "8123",
            "BIRD_RECOGNITION_API_JOBS_DIR": "jobs",
            "BIRD_RECOGNITION_API_ALLOWED_ROOTS": "one;two",
        },
    )

    assert settings.host == "localhost"
    assert settings.port == 8123
    assert settings.jobs_dir == Path("jobs").resolve()
    assert settings.allowed_roots == (Path("one").resolve(), Path("two").resolve())


@pytest.mark.parametrize("port", ["0", "65536", "bad"])
def test_load_settings_rejects_invalid_port(port: str) -> None:
    with pytest.raises(ValueError, match="API port"):
        load_settings(
            process_environment={"BIRD_RECOGNITION_API_PORT": port},
            dotenv_environment={},
        )
