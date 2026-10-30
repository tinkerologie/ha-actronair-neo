"""Resolve exact HA and matching harness versions, including HA betas."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

HARNESS = "pytest-homeassistant-custom-component"
HARNESS_SCAN_LIMIT = 30


def metadata(project: str, version: str = "") -> dict[str, Any]:
    """Read version metadata from the fixed HTTPS PyPI endpoint."""
    url = f"https://pypi.org/pypi/{project}/{version + '/' if version else ''}json"
    with urlopen(url, timeout=30) as response:
        return json.load(response)


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


def resolve() -> tuple[str, str]:
    """Find the newest HA release and a harness accepting that exact version."""
    ha = compatible_versions(metadata("homeassistant"))[0]
    for version in compatible_versions(metadata(HARNESS))[:HARNESS_SCAN_LIMIT]:
        info = metadata(HARNESS, str(version))["info"]
        for raw in info.get("requires_dist") or []:
            requirement = Requirement(raw)
            if (
                requirement.name.lower().replace("_", "-") == "homeassistant"
                and (requirement.marker is None or requirement.marker.evaluate())
                and requirement.specifier.contains(ha, prereleases=True)
            ):
                return str(ha), str(version)
    return str(ha), ""


def main() -> None:
    """Print workflow outputs and optionally append them to GITHUB_OUTPUT."""
    ha, harness = resolve()
    output = f"ha_version={ha}\nharness_version={harness}\n"
    sys.stdout.write(output)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(output)


if __name__ == "__main__":
    main()
