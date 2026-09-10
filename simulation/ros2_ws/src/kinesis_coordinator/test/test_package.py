from pathlib import Path


def test_package_manifest_exists() -> None:
    assert (Path(__file__).parents[1] / "package.xml").is_file()
