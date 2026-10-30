"""Build deterministic, validated HACS release assets from tracked files."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

INTEGRATION = Path("custom_components/actronair_neo")
ASSET = "actronair_neo.zip"
REQUIRED = {
    "__init__.py",
    "api/__init__.py",
    "api/push/__init__.py",
    "certs/sectigo_dv_r36.pem",
    "config_flow.py",
    "icons.json",
    "frontend/actronair-neo-cards.js",
    "frontend/THIRD_PARTY_LICENSES.txt",
    "manifest.json",
    "services.yaml",
    "strings.json",
    "translations/en.json",
}
# Static imports, re-exports, side-effect imports and literal dynamic imports.
IMPORTS = re.compile(
    r"(?:\b(?:import|export)\s+(?:[^;]*?\s+from\s*)?|\bimport\s*\(\s*)"
    r"[\"'](\.{1,2}/[^\"']+)[\"']"
)


def git(root: Path, *args: str) -> bytes:
    """Run a read-only Git command without a shell."""
    executable = shutil.which("git")
    if executable is None:
        message = "git is required"
        raise ValueError(message)
    return subprocess.run(  # noqa: S603 - Resolved executable, argument list, no shell.
        [executable, *args], cwd=root, check=True, capture_output=True
    ).stdout


def validate(archive: Path, tag: str | None) -> None:
    """Reject incomplete archives and missing relative frontend imports."""
    with ZipFile(archive) as package:
        names = set(package.namelist())
        missing = REQUIRED - names
        if missing:
            message = f"Missing required files: {', '.join(sorted(missing))}"
            raise ValueError(message)
        if any(name.startswith("actronair_neo/") for name in names):
            message = "Integration files must be at the ZIP root"
            raise ValueError(message)
        manifest = json.loads(package.read("manifest.json"))
        if manifest.get("domain") != "actronair_neo":
            message = "Manifest domain must be actronair_neo"
            raise ValueError(message)
        if tag is not None and manifest.get("version") != tag:
            message = f"Manifest version {manifest.get('version')!r} != tag {tag!r}"
            raise ValueError(message)
        for name in sorted(names):
            if PurePosixPath(name).suffix not in {".js", ".mjs"}:
                continue
            for specifier in IMPORTS.findall(package.read(name).decode("utf-8")):
                target = posixpath.normpath(
                    posixpath.join(
                        posixpath.dirname(name), re.split(r"[?#]", specifier)[0]
                    )
                )
                if target not in names:
                    message = f"Missing frontend import: {name} -> {specifier}"
                    raise ValueError(message)


def build(root: Path, output: Path, tag: str | None) -> Path:
    """Build deterministic release bytes from tracked integration files."""
    integration = root / INTEGRATION
    if integration.is_symlink():
        message = "Integration directory must not be a symlink"
        raise ValueError(message)
    timestamp = int(
        os.environ.get("SOURCE_DATE_EPOCH")
        or git(root, "log", "-1", "--format=%ct").decode().strip()
    )
    # ZIP timestamps have a 1980-2107 range and two-second resolution.
    timestamp = min(max(timestamp, 315532800), 4354819198)
    date = datetime.fromtimestamp(timestamp, UTC)
    date_time = (
        date.year,
        date.month,
        date.day,
        date.hour,
        date.minute,
        date.second // 2 * 2,
    )
    files: list[tuple[str, Path]] = []
    tracked = git(root, "ls-files", "-z", "--", INTEGRATION.as_posix())
    for entry in tracked.split(b"\0"):
        if not entry:
            continue
        relative = Path(os.fsdecode(entry))
        source = root / relative
        name = relative.relative_to(INTEGRATION).as_posix()
        if (
            "__pycache__" in relative.parts
            or relative.suffix == ".pyc"
            or source.is_symlink()
            or not source.is_file()
            or not source.resolve().is_relative_to(integration.resolve())
            or any(
                parent.is_symlink()
                for parent in source.parents
                if parent.is_relative_to(integration)
            )
        ):
            message = f"Unsafe tracked file: {relative}"
            raise ValueError(message)
        files.append((name, source))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output, suffix=".zip", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with ZipFile(
            temporary, "w", compression=ZIP_DEFLATED, compresslevel=9
        ) as package:
            for name, source in sorted(files):
                info = ZipInfo(name, date_time)
                info.create_system = 3
                info.external_attr = 0o644 << 16
                package.writestr(
                    info,
                    source.read_bytes(),
                    compress_type=ZIP_DEFLATED,
                    compresslevel=9,
                )
        validate(temporary, tag)
        destination = output / ASSET
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (output / "SHA256SUMS").write_text(f"{digest}  {ASSET}\n", encoding="utf-8")
    return destination


def main() -> int:
    """Parse CLI options and report build failures without a traceback."""
    parser = argparse.ArgumentParser(description="Build the HACS release ZIP")
    parser.add_argument("--tag")
    parser.add_argument(
        "--source-root", type=Path, default=Path(__file__).resolve().parent.parent
    )
    parser.add_argument("--output-dir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    try:
        asset = build(args.source_root.resolve(), args.output_dir.resolve(), args.tag)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.stderr.write(f"Release build failed: {error}\n")
        return 1
    sys.stdout.write(f"Built and validated {asset}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
