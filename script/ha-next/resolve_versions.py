"""Resolve an HA Next channel's Home Assistant and matching test plugin."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tomllib
import traceback
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

HARNESS = "pytest-homeassistant"
CORE_REPO = "home-assistant/core"
PLUGIN_DIR = "packages/pytest-homeassistant"
NOT_PUBLISHED = "not published on PyPI for this Home Assistant version"

MAX_ATTEMPTS = 3
BACKOFF_BASE = 2.0
MAX_RETRY_DELAY = 30.0
RETRYABLE_STATUSES = frozenset(
    {
        HTTPStatus.TOO_MANY_REQUESTS,
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    }
)


class ResolverHTTPError(Exception):
    """An HTTP failure after retries, carrying what the failure note needs."""

    def __init__(self, err: HTTPError, url: str, attempts: int) -> None:
        """Wrap the last HTTPError with its URL and the attempts made."""
        super().__init__(f"HTTP {err.code} {err.reason}")
        self.code = err.code
        self.reason = err.reason
        self.host = urlsplit(url).hostname or ""
        self.attempts = attempts


def _retry_after(err: HTTPError) -> float | None:
    """Seconds requested by a Retry-After header (delta or HTTP-date), if any."""
    value = err.headers.get("Retry-After") if err.headers else None
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _is_retryable(err: HTTPError) -> bool:
    """429/5xx, or a 403 that GitHub marks as a rate limit."""
    if err.code in RETRYABLE_STATUSES:
        return True
    headers = err.headers
    return (
        err.code == HTTPStatus.FORBIDDEN
        and headers is not None
        and (
            headers.get("Retry-After") is not None
            or headers.get("x-ratelimit-remaining") == "0"
        )
    )


def _get(url: str, accept: str = "application/json") -> bytes | None:
    """
    GET a fixed HTTPS URL; return None for 404 (absent release/file/ref).

    Retries rate limits and server errors a few times with a capped delay.
    The GitHub token is sent only to api.github.com and never on redirects.
    """
    request = Request(  # noqa: S310 - Fixed HTTPS hosts only.
        url, headers={"Accept": accept, "User-Agent": "ha-next-resolver"}
    )
    if url.startswith("https://api.github.com/") and (
        token := os.environ.get("GITHUB_TOKEN")
    ):
        request.add_unredirected_header("Authorization", f"Bearer {token}")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - Fixed HTTPS hosts.
                return response.read()
        except HTTPError as err:
            if err.code == HTTPStatus.NOT_FOUND:
                return None
            if not _is_retryable(err) or attempt == MAX_ATTEMPTS:
                raise ResolverHTTPError(err, url, attempt) from err
            requested = _retry_after(err)
            if requested is not None and requested > MAX_RETRY_DELAY:
                raise ResolverHTTPError(err, url, attempt) from err
            delay = (
                requested
                if requested is not None
                else min(BACKOFF_BASE * 2 ** (attempt - 1), MAX_RETRY_DELAY)
            )
            sys.stderr.write(
                f"HTTP {err.code} from {urlsplit(url).hostname}; "
                f"retry {attempt}/{MAX_ATTEMPTS - 1} in {delay:.0f}s\n"
            )
            time.sleep(delay)
    return None  # pragma: no cover - the loop always returns or raises


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
    """Read a file from Core at a commit through the authenticated contents API."""
    return _get(
        f"https://api.github.com/repos/{CORE_REPO}/contents/{quote(path)}?ref={sha}",
        accept="application/vnd.github.raw+json",
    )


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
        raise RuntimeError(msg)
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
    failed = False
    try:
        values = resolve_pypi() if channel == "pypi" else resolve_dev()
    except Exception as err:  # noqa: BLE001 - Any failure becomes a reported note.
        traceback.print_exc()
        failed = True
        values = dict.fromkeys(
            ("ha_version", "ha_spec", "harness_source", "harness_spec"), ""
        )
        values["harness_note"] = failure_note(err)
    output = "".join(f"{key}={value}\n" for key, value in values.items())
    sys.stdout.write(output)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(output)
    if failed:
        sys.exit(1)


def failure_note(err: Exception) -> str:
    """One-line cause for a failed resolution; never includes request headers."""
    if isinstance(err, ResolverHTTPError):
        note = f"resolver failed: HTTP {err.code} {err.reason} from {err.host}"
        if err.attempts > 1:
            note += f" after {err.attempts} attempts"
    elif isinstance(err, URLError):
        host = urlsplit(err.filename or "").hostname if err.filename else None
        source = f" from {host}" if host else ""
        note = f"resolver failed: network error{source}: {err.reason}"
    elif isinstance(err, TimeoutError):
        note = f"resolver failed: network timeout: {err}"
    else:
        note = f"resolver failed: {type(err).__name__}: {err}"
    return " ".join(note.split())


if __name__ == "__main__":
    main()
