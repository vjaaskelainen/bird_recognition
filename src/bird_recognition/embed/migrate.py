from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any

import psycopg

_MIGRATION_LOCK_KEY = 0x42524952444D4947
_MIGRATION_NAME = re.compile(r"(?P<version>[0-9]{3})_[a-z0-9_]+\.sql\Z")
_MIGRATION_DIRECTORY = files("bird_recognition.embed").joinpath("migrations")
_POLL_INTERVAL_SECONDS = 30


class MigrationError(RuntimeError):
    """Raised when the database migration history is invalid or incomplete."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One numbered SQL migration resource."""

    version: int
    resource: Traversable


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """The schema version reached and migrations applied by one run."""

    version: int
    applied_versions: tuple[int, ...]


def discover_migrations(
    directory: Traversable = _MIGRATION_DIRECTORY,
) -> tuple[Migration, ...]:
    """Load SQL migration resources and require a contiguous sequence from 1."""
    migrations: list[Migration] = []
    for resource in directory.iterdir():
        if not resource.is_file() or not resource.name.endswith(".sql"):
            continue
        match = _MIGRATION_NAME.fullmatch(resource.name)
        if match is None:
            raise MigrationError("migration SQL filename must use NNN_name.sql")
        migrations.append(Migration(int(match.group("version")), resource))

    migrations.sort(key=lambda migration: migration.version)
    versions = tuple(migration.version for migration in migrations)
    if versions != tuple(range(1, len(versions) + 1)):
        raise MigrationError("migration versions must be contiguous starting at 001")
    if not migrations:
        raise MigrationError("no SQL migrations are packaged")
    return tuple(migrations)


def latest_migration_version(
    directory: Traversable = _MIGRATION_DIRECTORY,
) -> int:
    """Return the latest migration version packaged with the application."""
    return discover_migrations(directory)[-1].version


def apply_pending_migrations(
    connection: psycopg.Connection[Any],
    directory: Traversable = _MIGRATION_DIRECTORY,
) -> MigrationResult:
    """Apply only pending migrations, each in its own transaction."""
    if not connection.autocommit:
        raise MigrationError("migration connection must use autocommit mode")

    migrations = discover_migrations(directory)
    connection.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_LOCK_KEY,))
    try:
        current_version = _installed_version(connection)
        latest_version = migrations[-1].version
        if current_version > latest_version:
            raise MigrationError("database schema is newer than this application")
        if current_version == 0:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")

        applied_versions: list[int] = []
        for migration in migrations:
            if migration.version <= current_version:
                continue
            sql = migration.resource.read_text(encoding="utf-8")
            with connection.transaction():
                connection.execute(sql, prepare=False)
                updated = connection.execute(
                    "UPDATE bird_embed.schema_version SET version=%s WHERE singleton",
                    (migration.version,),
                )
                if updated.rowcount != 1:
                    raise MigrationError(
                        "migration did not leave one schema version record"
                    )
            current_version = migration.version
            applied_versions.append(migration.version)

        return MigrationResult(current_version, tuple(applied_versions))
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_LOCK_KEY,))


def check_database(connection: psycopg.Connection[Any]) -> int:
    """Verify that pgvector and the latest packaged schema are installed."""
    if not connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')"
    ).fetchone()[0]:
        raise MigrationError("pgvector extension is unavailable")
    current_version = _installed_version(connection)
    if current_version != latest_migration_version():
        raise MigrationError("database schema is not at the latest migration")
    return current_version


def _installed_version(connection: psycopg.Connection[Any]) -> int:
    schema_exists = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='bird_embed')"
    ).fetchone()[0]
    if not schema_exists:
        return 0

    version_table_exists = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_class AS t "
        "JOIN pg_namespace AS n ON n.oid=t.relnamespace "
        "WHERE n.nspname='bird_embed' AND t.relname='schema_version' "
        "AND t.relkind='r')"
    ).fetchone()[0]
    if not version_table_exists:
        raise MigrationError("database schema has no migration version record")

    row = connection.execute(
        "SELECT version FROM bird_embed.schema_version WHERE singleton"
    ).fetchone()
    if row is None:
        raise MigrationError("database schema has no migration version record")
    return int(row[0])


def _connect() -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        connect_timeout=5,
        autocommit=True,
    )


def main() -> int:
    """Run migrations once and monitor schema readiness for Compose health checks."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    try:
        with _connect() as connection:
            if arguments.check:
                check_database(connection)
                return 0
            while True:
                result = apply_pending_migrations(connection)
                print(
                    f"Database schema ready at version {result.version}.",
                    flush=True,
                )
                time.sleep(_POLL_INTERVAL_SECONDS)
    except MigrationError as error:
        print(
            f"Database migration service failed: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    except Exception as error:
        print(
            f"Database migration service failed ({type(error).__name__}).",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
