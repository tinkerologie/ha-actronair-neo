"""Resolve an HA Next channel's Home Assistant and matching test plugin."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

HARNESS = "pytest-homeassistant"
CORE_REPO = "home-assistant/core"
PLUGIN_DIR = "packages/pytest-homeassistant"
NOT_PUBLISHED = "not published on PyPI for this Home Assistant version"


def _get(url: str, accept: str = "application/json") -> bytes | None:
    """GET a fixed HTTPS URL; return None for 404 (absent release/file/ref)."""
    headers = {"Accept": accept, "User-Agent": "ha-next-resolver"}
    if url.startswith("https://api.github.com/") and (
        token := os.environ.get("GITHUB_TOKEN")
    ):
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:  # noqa: S310 - Fixed HTTPS hosts.
            return response.read()
    except HTTPError as err:
        if err.code == HTTPStatus.NOT_FOUND:
            return None
        raise


def metadata(project: str, version: str = "") -> dict[str, Any] | None:
    """Read project or release metadata from PyPI; None when it does not exist."""
    url = f"https://pypi.org/pypi/{project}/{version + '/' if version else ''}json"
    raw = _get(url)
    return None if raw is None else json.loads(raw)


def compatible_versions(data: dict[str, Any]) -> list[Version]:
    """Sort non-yanked releases compatible with the running interpreter."""
    python = Version(".".join(map(str, sys.version_info[:3])))
    versions = []
    for raw, files in data["releases"].items():
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        if any(
            not file.get("yanked", False)
            and SpecifierSet(file.get("requires_python") or "").contains(python)
            for file in files
        ):
            versions.append(version)
    return sorted(versions, reverse=True)


def pypi_plugin_matches(ha: Version) -> bool:
    """
    Return whether PyPI has a plugin release built for this HA version.

    The release must share HA's version or pin ``homeassistant`` with a
    non-empty specifier containing it. Unversioned requirements never match,
    which also rules out the unrelated 2020 ``pytest-homeassistant`` releases.
    """
    data = metadata(HARNESS, str(ha))
    if data is None:
        return False
    if Version(data["info"]["version"]) == ha:
        return True
    for raw in data["info"].get("requires_dist") or []:
        requirement = Requirement(raw)
        if (
            requirement.name.lower().replace("_", "-") == "homeassistant"
            and (requirement.marker is None or requirement.marker.evaluate())
            and str(requirement.specifier)
            and requirement.specifier.contains(ha, prereleases=True)
        ):
            return True
    return False


def core_sha(ref: str) -> str | None:
    """Resolve a Core tag or branch to a full commit SHA."""
    raw = _get(
        f"https://api.github.com/repos/{CORE_REPO}/commits/{ref}",
        accept="application/vnd.github.sha",
    )
    return None if raw is None else raw.decode().strip()


def core_file(sha: str, path: str) -> bytes | None:
    """Read a file from Core at a commit."""
    return _get(f"https://raw.githubusercontent.com/{CORE_REPO}/{sha}/{path}")


def git_plugin_spec(sha: str) -> str:
    """PEP 508 requirement for the in-tree plugin at one Core commit."""
    return (
        f"{HARNESS} @ git+https://github.com/{CORE_REPO}.git@{sha}"
        f"#subdirectory={PLUGIN_DIR}"
    )


def resolve_pypi() -> dict[str, str]:
    """Newest PyPI HA (betas included) with a PyPI or Core-tag plugin source."""
    ha = compatible_versions(metadata("homeassistant") or {"releases": {}})[0]
    result = {"ha_version": str(ha), "ha_spec": f"homeassistant=={ha}"}
    if pypi_plugin_matches(ha):
        return result | {
            "harness_source": "pypi",
            "harness_spec": f"{HARNESS}=={ha}",
            "harness_note": "",
        }
    sha = core_sha(str(ha))
    if sha is None:
        note = f"{NOT_PUBLISHED}; no Core tag {ha}"
    elif core_file(sha, f"{PLUGIN_DIR}/pyproject.toml") is None:
        note = f"{NOT_PUBLISHED}; no in-tree plugin at Core tag {ha}"
    else:
        return result | {
            "harness_source": "git",
            "harness_spec": git_plugin_spec(sha),
            "harness_note": f"{NOT_PUBLISHED}; using Core tag {ha} ({sha[:12]})",
        }
    return result | {"harness_source": "", "harness_spec": "", "harness_note": note}


def resolve_dev() -> dict[str, str]:
    """Core dev head: HA and the in-tree plugin from the same commit."""
    sha = core_sha("dev")
    if sha is None:
        msg = "could not resolve the Core dev branch"
        raise SystemExit(msg)
    root = core_file(sha, "pyproject.toml")
    version = tomllib.loads(root.decode())["project"]["version"] if root else ""
    result = {
        "ha_version": f"{version} (dev {sha[:12]})" if version else f"dev {sha[:12]}",
        "ha_spec": (
            f"homeassistant @ https://github.com/{CORE_REPO}/archive/{sha}.tar.gz"
        ),
    }
    if core_file(sha, f"{PLUGIN_DIR}/pyproject.toml") is None:
        return result | {
            "harness_source": "",
            "harness_spec": "",
            "harness_note": f"no in-tree plugin at dev commit {sha[:12]}",
        }
    return result | {
        "harness_source": "git",
        "harness_spec": git_plugin_spec(sha),
        "harness_note": f"in-tree plugin at dev commit {sha[:12]}",
    }


def main() -> None:
    """Print workflow outputs and optionally append them to GITHUB_OUTPUT."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", choices=("pypi", "dev"), nargs="?", default="pypi")
    channel = parser.parse_args().channel
    values = resolve_pypi() if channel == "pypi" else resolve_dev()
    output = "".join(f"{key}={value}\n" for key, value in values.items())
    sys.stdout.write(output)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(output)


if __name__ == "__main__":
    main()
