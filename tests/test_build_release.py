"""Verify release bytes and complete frontend packaging at the install root."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest

from script.build_release import ASSET, INTEGRATION, build


@pytest.fixture
def release_source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / INTEGRATION,
        source / INTEGRATION,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    git = shutil.which("git")
    assert git
    for args in [
        ("init",),
        ("add", "custom_components"),
        (
            "-c",
            "user.name=Release test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "fixture",
        ),
    ]:
        subprocess.run([git, *args], cwd=source, check=True, capture_output=True)  # noqa: S603 - Resolved Git and fixed arguments in a temp fixture.
    return source


def test_release_is_reproducible_and_complete(release_source, tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1234567890")
    version = json.loads((release_source / INTEGRATION / "manifest.json").read_text())[
        "version"
    ]
    first = build(release_source, tmp_path / "first", version)
    second = build(release_source, tmp_path / "second", version)
    assert first.read_bytes() == second.read_bytes()
    with ZipFile(first) as package:
        assert "manifest.json" in package.namelist()
        assert "frontend/actronair-neo-cards.js" in package.namelist()
        assert not any(name.startswith("actronair_neo/") for name in package.namelist())
        assert package.testzip() is None
    expected = hashlib.sha256(first.read_bytes()).hexdigest() + "  " + ASSET + "\n"
    assert (first.parent / "SHA256SUMS").read_text() == expected


def test_release_rejects_wrong_version(release_source, tmp_path):
    with pytest.raises(ValueError, match="Manifest version"):
        build(release_source, tmp_path / "dist", "wrong-version")
    assert not (tmp_path / "dist" / ASSET).exists()


def test_untracked_files_are_excluded(release_source, tmp_path):
    (release_source / INTEGRATION / "untracked.txt").write_text("do not ship")
    archive = build(release_source, tmp_path / "dist", None)
    with ZipFile(archive) as package:
        assert "untracked.txt" not in package.namelist()
