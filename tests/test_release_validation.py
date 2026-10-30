"""Exercise release validation failures before any archive can be published."""

import json
import shutil
import subprocess
from zipfile import ZipFile

import pytest

from script import build_release as release


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "source"
    integration = root / release.INTEGRATION
    for name in release.REQUIRED:
        path = integration / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    (integration / "manifest.json").write_text(
        json.dumps({"domain": "actronair_neo", "version": "2026.10.4"})
    )
    executable = shutil.which("git")
    assert executable
    for args in [
        ("init",),
        ("add", "."),
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
        subprocess.run([executable, *args], cwd=root, check=True, capture_output=True)  # noqa: S603
    return root


def archive_with(tmp_path, *, remove=None, extra=None, manifest=None):
    archive = tmp_path / "input.zip"
    content = dict.fromkeys(release.REQUIRED, "")
    content["manifest.json"] = json.dumps(
        manifest or {"domain": "actronair_neo", "version": "2026.10.4"}
    )
    if remove:
        content.pop(remove)
    content.update(extra or {})
    with ZipFile(archive, "w") as package:
        for name, value in content.items():
            package.writestr(name, value)
    return archive


def test_git_missing_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(release.shutil, "which", lambda _: None)
    with pytest.raises(ValueError, match="git is required"):
        release.git(tmp_path, "status")


def test_git_command_failure(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        release.git(tmp_path, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"remove": "services.yaml"}, "Missing required files: services.yaml"),
        ({"extra": {"actronair_neo/extra.py": ""}}, "ZIP root"),
        (
            {"manifest": {"domain": "foreign", "version": "2026.10.4"}},
            "Manifest domain",
        ),
        (
            {"extra": {"frontend/card.js": "import './missing.js';"}},
            "Missing frontend import",
        ),
    ],
)
def test_reject_invalid_archive(tmp_path, options, message):
    with pytest.raises(ValueError, match=message):
        release.validate(archive_with(tmp_path, **options), "2026.10.4")


def test_reject_version_mismatch(tmp_path):
    with pytest.raises(ValueError, match="Manifest version"):
        release.validate(archive_with(tmp_path), "2026.11.0")


def test_relative_imports_resolve_queries_fragments_and_parent_paths(tmp_path):
    archive = archive_with(
        tmp_path,
        extra={
            "frontend/card.js": (
                "import './chunk.js?v=1'; export {x} from '../shared.mjs#hash';"
                "import('./chunk.js#dynamic');"
            ),
            "frontend/chunk.js": "",
            "shared.mjs": "export const x = 1;",
        },
    )
    release.validate(archive, "2026.10.4")


@pytest.mark.parametrize("kind", ["integration", "file", "parent", "missing"])
def test_reject_unsafe_tracked_paths(source, tmp_path, kind):
    integration = source / release.INTEGRATION
    if kind == "integration":
        destination = source / "external"
        integration.rename(destination)
        integration.symlink_to(destination, target_is_directory=True)
    elif kind == "parent":
        destination = source / "external"
        (integration / "api").rename(destination)
        (integration / "api").symlink_to(destination, target_is_directory=True)
    else:
        target = integration / "services.yaml"
        target.unlink()
        if kind == "file":
            destination = source / "external.yaml"
            destination.write_text("private content")
            target.symlink_to(destination)
    with pytest.raises(ValueError, match=r"symlink|Unsafe tracked file"):
        release.build(source, tmp_path / "dist", None)
    assert not (tmp_path / "dist" / release.ASSET).exists()


@pytest.mark.parametrize(
    ("epoch", "expected"),
    [("0", (1980, 1, 1, 0, 0, 0)), ("9999999999", (2107, 12, 31, 23, 59, 58))],
)
def test_zip_timestamp_bounds(source, tmp_path, monkeypatch, epoch, expected):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", epoch)
    archive = release.build(source, tmp_path / "dist", None)
    with ZipFile(archive) as package:
        assert {item.date_time for item in package.infolist()} == {expected}


def test_git_timestamp_fallback_reproducibility_and_untracked_exclusion(
    source, tmp_path, monkeypatch
):
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    (source / release.INTEGRATION / "secret.txt").write_text("must stay local")
    first = release.build(source, tmp_path / "first", "2026.10.4")
    second = release.build(source, tmp_path / "second", "2026.10.4")
    assert first.read_bytes() == second.read_bytes()
    assert (first.parent / "SHA256SUMS").read_bytes() == (
        second.parent / "SHA256SUMS"
    ).read_bytes()
    with ZipFile(first) as package:
        assert "secret.txt" not in package.namelist()
        assert all(item.external_attr >> 16 == 0o644 for item in package.infolist())


def test_failed_validation_cleans_temporary_archive_and_preserves_existing_release(
    source, tmp_path
):
    output = tmp_path / "dist"
    archive = release.build(source, output, "2026.10.4")
    original = archive.read_bytes()
    checksum = (output / "SHA256SUMS").read_bytes()
    with pytest.raises(ValueError, match="Manifest version"):
        release.build(source, output, "incorrect")
    assert archive.read_bytes() == original
    assert (output / "SHA256SUMS").read_bytes() == checksum
    assert {path.name for path in output.iterdir()} == {release.ASSET, "SHA256SUMS"}


def test_cli_reports_failure_without_traceback(source, tmp_path, monkeypatch, capsys):
    output = tmp_path / "dist"
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_release.py",
            "--source-root",
            str(source),
            "--output-dir",
            str(output),
            "--tag",
            "incorrect",
        ],
    )
    assert release.main() == 1
    captured = capsys.readouterr()
    assert "Release build failed: Manifest version" in captured.err
    assert "Traceback" not in captured.err
    assert not captured.out
    assert not list(output.iterdir())
