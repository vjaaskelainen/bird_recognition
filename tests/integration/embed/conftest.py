import os
from collections.abc import Iterator
from urllib.parse import urlsplit

import psycopg
import pytest

from bird_recognition.embed.config import validate_local_database_url


@pytest.fixture
def database_url() -> str:
    value = os.environ.get("BIRD_RECOGNITION_TEST_DATABASE_URL")
    if not value:
        pytest.skip("explicit disposable test database URL is required")
    validate_local_database_url(value)
    if "test" not in urlsplit(value).path.strip("/").casefold():
        pytest.skip("test database name must include 'test' before schema cleanup")
    return value


@pytest.fixture
def disposable_embed_schema(database_url: str) -> Iterator[str]:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS bird_embed CASCADE")
    yield database_url
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS bird_embed CASCADE")
