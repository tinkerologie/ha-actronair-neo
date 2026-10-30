"""Import every integration module and report integration deprecations."""  # noqa: INP001 - Standalone CLI.

from __future__ import annotations

import importlib
import logging
import os
import pkgutil
import re
import sys
import warnings
from pathlib import Path

DOMAIN = "custom_components.actronair_neo"
PATTERNS = (
    re.compile(r"Detected that custom integration 'actronair_neo'"),
    re.compile(r"The deprecated .* was used from actronair_neo\b"),
    re.compile(
        r"custom_components\.actronair_neo\.[\w.]+::\w+ provides the deprecated "
    ),
)


class Capture(logging.Handler):
    """Collect HA log reports during package discovery and imports."""

    def __init__(self) -> None:
        """Initialise the capture handler at warning level."""
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep only deprecation reports naming this integration."""
        message = record.getMessage()
        if any(pattern.search(message) for pattern in PATTERNS):
            self.messages.append(message)


def check_imports() -> tuple[str, list[str]]:
    """Capture import failures and warnings before the first integration import."""
    capture = Capture()
    root_logger = logging.getLogger()
    root_logger.addHandler(capture)
    findings: list[str] = []
    version = "unknown"
    # Prefer the checkout, including when the project is also installed as a wheel.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    try:
        with warnings.catch_warnings(record=True) as recorded:
            warnings.simplefilter("always")
            try:
                version = importlib.import_module("homeassistant.const").__version__
                package = importlib.import_module(DOMAIN)
            except Exception as error:  # noqa: BLE001 - Every import failure is a finding.
                findings.append(f"{DOMAIN}: {type(error).__name__}: {error}")
            else:

                def onerror(name: str) -> None:
                    """Record subpackage failures raised by walk_packages itself."""
                    findings.append(f"{name}: {sys.exc_info()[1]}")

                for module in pkgutil.walk_packages(
                    package.__path__, DOMAIN + ".", onerror=onerror
                ):
                    try:
                        importlib.import_module(module.name)
                    except Exception as error:  # noqa: BLE001 - Continue to inspect all modules.
                        findings.append(
                            f"{module.name}: {type(error).__name__}: {error}"
                        )
            for warning in recorded:
                path = Path(warning.filename).as_posix()
                if "custom_components/actronair_neo/" in path and issubclass(
                    warning.category, (DeprecationWarning, PendingDeprecationWarning)
                ):
                    findings.append(f"{path}:{warning.lineno}: {warning.message}")
    finally:
        root_logger.removeHandler(capture)
    return version, sorted(set(findings + capture.messages))


def main() -> int:
    """Write the installed version and findings for humans and workflows."""
    version, findings = check_imports()
    if output := os.environ.get("GITHUB_OUTPUT"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(f"ha_version={version}\n")
    summary = (
        f"## Import check: Home Assistant {version}\n\n"
        "| Result | Detail |\n| --- | --- |\n"
    )
    for finding in findings or [
        "All integration modules imported without deprecations"
    ]:
        detail = finding.replace("|", "\\|").replace("\n", " ")
        summary += f"| {'Failure' if findings else 'Pass'} | {detail} |\n"
    sys.stdout.write(summary)
    if output := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(summary)
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
