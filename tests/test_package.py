from importlib import import_module
from importlib.resources import files


def test_package_import_when_installed_succeeds() -> None:
    package = import_module("bird_recognition")

    assert package.__name__ == "bird_recognition"


def test_initial_migration_is_in_installed_package_resources() -> None:
    migration = files("bird_recognition").joinpath(
        "embed", "migrations", "001_initial.sql"
    )

    assert migration.is_file()
