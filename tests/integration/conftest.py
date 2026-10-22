import os
from pathlib import Path

import psycopg
import pytest
from dotenv import dotenv_values
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from bird_recognition.embed.config import validate_local_database_url


@pytest.fixture(scope="session", autouse=True)
def load_integration_environment() -> None:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    test_database_url = dotenv_values(env_path).get(
        "BIRD_RECOGNITION_TEST_DATABASE_URL"
    )
    if test_database_url is not None:
        os.environ.setdefault("BIRD_RECOGNITION_TEST_DATABASE_URL", test_database_url)


@pytest.fixture(scope="session", autouse=True)
def recreate_test_database(load_integration_environment: None) -> None:
    database_url = os.environ.get("BIRD_RECOGNITION_TEST_DATABASE_URL")
    if not database_url:
        return
    validate_local_database_url(database_url)
    connection_info = conninfo_to_dict(database_url)
    database_name = connection_info.get("dbname")
    if not database_name or "test" not in database_name.casefold():
        return

    maintenance_connection_info = {**connection_info, "dbname": "postgres"}
    with psycopg.connect(**maintenance_connection_info, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                sql.Identifier(database_name)
            )
        )
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
        )
