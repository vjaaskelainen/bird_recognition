from pathlib import Path

import pytest

from bird_recognition.embed.migrate import MigrationError, discover_migrations


def test_discover_migrations_orders_contiguous_revisions(tmp_path: Path) -> None:
    (tmp_path / "002_add_index.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "001_initial.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "003_reference.sql").write_text("SELECT 3;", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [migration.version for migration in migrations] == [1, 2, 3]


@pytest.mark.parametrize(
    ("filenames", "message"),
    [
        (("001_initial.sql", "003_add_table.sql"), "contiguous"),
        (("initial.sql",), "filename"),
        ((), "no SQL migrations"),
    ],
)
def test_discover_migrations_rejects_invalid_history(
    tmp_path: Path, filenames: tuple[str, ...], message: str
) -> None:
    for filename in filenames:
        (tmp_path / filename).write_text("SELECT 1;", encoding="utf-8")

    with pytest.raises(MigrationError, match=message):
        discover_migrations(tmp_path)
