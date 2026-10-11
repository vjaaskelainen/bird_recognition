from importlib import import_module


def test_package_import_when_installed_succeeds() -> None:
    package = import_module("bird_recognition")

    assert package.__name__ == "bird_recognition"
