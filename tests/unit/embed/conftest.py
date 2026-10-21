from __future__ import annotations

import ipaddress
import os
import socket
import sqlite3
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from bird_recognition.embed.models import EmbeddingModelRecord
from bird_recognition.ingest.manifest import SCHEMA as INGESTION_SCHEMA
from tests.unit.embed.fakes import FakeModel, FakeStore, FakeStoreState

_TEST_DATABASE_ENV = "BIRD_RECOGNITION_TEST_DATABASE_URL"
_SMOKE_MODEL_ENV = "BIRD_RECOGNITION_BIOCLIP_SMOKE_MODEL_DIR"
_SMOKE_IMAGE_ENV = "BIRD_RECOGNITION_BIOCLIP_SMOKE_IMAGE"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("real_database") and not os.environ.get(
            _TEST_DATABASE_ENV
        ):
            item.add_marker(
                pytest.mark.skip(
                    reason=f"requires explicit {_TEST_DATABASE_ENV} opt-in"
                )
            )
        if item.get_closest_marker("local_model") and not all(
            os.environ.get(name) for name in (_SMOKE_MODEL_ENV, _SMOKE_IMAGE_ENV)
        ):
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        f"requires explicit {_SMOKE_MODEL_ENV} and "
                        f"{_SMOKE_IMAGE_ENV} opt-ins"
                    )
                )
            )


@pytest.fixture(autouse=True)
def deny_network(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    allow_local_database = bool(
        request.node.get_closest_marker("real_database")
        and os.environ.get(_TEST_DATABASE_ENV)
    )
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex

    def is_local_address(address: Any) -> bool:
        if isinstance(address, str):
            return allow_local_database
        if not isinstance(address, tuple) or not address:
            return False
        host = address[0]
        if host == "localhost":
            return allow_local_database
        try:
            return allow_local_database and ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def guarded_connect(connection: socket.socket, address: Any) -> None:
        if not is_local_address(address):
            raise OSError("network access is disabled for embed tests")
        original_connect(connection, address)

    def guarded_connect_ex(connection: socket.socket, address: Any) -> int:
        if not is_local_address(address):
            raise OSError("network access is disabled for embed tests")
        return original_connect_ex(connection, address)

    def guarded_sendto(connection: socket.socket, data: bytes, address: Any) -> int:
        del connection, data, address
        raise OSError("network access is disabled for embed tests")

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not allow_local_database or host != "localhost":
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError, TypeError:
                is_loopback = False
            if not (allow_local_database and is_loopback):
                raise OSError("network access is disabled for embed tests")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_gethostbyname(host: str) -> str:
        if not allow_local_database or host != "localhost":
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError, TypeError:
                is_loopback = False
            if not (allow_local_database and is_loopback):
                raise OSError("network access is disabled for embed tests")
        return original_gethostbyname(host)

    def guarded_gethostbyname_ex(host: str) -> tuple[str, list[str], list[str]]:
        if not allow_local_database or host != "localhost":
            try:
                is_loopback = ipaddress.ip_address(host).is_loopback
            except ValueError, TypeError:
                is_loopback = False
            if not (allow_local_database and is_loopback):
                raise OSError("network access is disabled for embed tests")
        return original_gethostbyname_ex(host)

    def guarded_gethostbyaddr(host: str) -> tuple[str, list[str], list[str]]:
        del host
        raise OSError("network access is disabled for embed tests")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", guarded_gethostbyname)
    monkeypatch.setattr(socket, "gethostbyname_ex", guarded_gethostbyname_ex)
    monkeypatch.setattr(socket, "gethostbyaddr", guarded_gethostbyaddr)


@pytest.fixture
def frame_factory() -> Callable[[tuple[int, int], tuple[int, int, int]], Image.Image]:
    def create_frame(
        size: tuple[int, int] = (32, 24),
        color: tuple[int, int, int] = (40, 120, 210),
    ) -> Image.Image:
        return Image.new("RGB", size, color)

    return create_frame


@pytest.fixture
def generated_crop(
    tmp_path: Path,
    frame_factory: Callable[[tuple[int, int], tuple[int, int, int]], Image.Image],
) -> Path:
    image_path = tmp_path / "synthetic-crop.png"
    frame_factory().save(image_path, format="PNG")
    return image_path


@pytest.fixture
def ingestion_schema(tmp_path: Path) -> Generator[Path]:
    database_path = tmp_path / "ingestion-manifest.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(INGESTION_SCHEMA)
    yield database_path


@pytest.fixture
def model_record() -> EmbeddingModelRecord:
    return EmbeddingModelRecord(
        model_fingerprint="1" * 64,
        upstream_name="test-model",
        upstream_revision="test-revision",
        checkpoint_sha256="2" * 64,
        config_sha256="3" * 64,
        tokenizer_sha256="4" * 64,
        architecture="test-architecture",
        dimension=3,
        preprocessing_json="{}",
        tokenizer_json="{}",
        adapter_version="test-adapter-v1",
        runtime_json="{}",
        logit_scale=1.0,
        canonical_json="{}",
    )


@pytest.fixture
def fake_model(model_record: EmbeddingModelRecord) -> FakeModel:
    return FakeModel(model_record)


@pytest.fixture
def fake_store_state() -> FakeStoreState:
    return FakeStoreState()


@pytest.fixture
def fake_store(fake_store_state: FakeStoreState) -> FakeStore:
    return FakeStore(fake_store_state)
