"""Tests for the HA Next resolver's HTTP retries, authentication and failure notes."""

from __future__ import annotations

import importlib.util
import io
import sys
from datetime import UTC, datetime, timedelta
from email.message import Message
from email.utils import format_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self
from urllib.error import HTTPError, URLError

import pytest

if TYPE_CHECKING:
    from types import ModuleType

pytest.importorskip("packaging")

SCRIPT = (
    Path(__file__).resolve().parents[1] / "script" / "ha-next" / "resolve_versions.py"
)


@pytest.fixture
def resolver() -> ModuleType:
    """Load the standalone script (its directory name is not importable)."""
    spec = importlib.util.spec_from_file_location("ha_next_resolve_versions", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _http_error(code: int, headers: dict[str, str] | None = None) -> HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return HTTPError("https://example.invalid", code, "reason", message, io.BytesIO())


class _Recorder:
    """Fake urlopen: replays outcomes and records each request."""

    def __init__(self, *outcomes: bytes | Exception) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> _Response:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(outcome)


@pytest.fixture
def sleeps(resolver: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr(resolver.time, "sleep", delays.append)
    return delays


def _install(
    resolver: ModuleType, monkeypatch: pytest.MonkeyPatch, *outcomes: bytes | Exception
) -> _Recorder:
    recorder = _Recorder(*outcomes)
    monkeypatch.setattr(resolver, "urlopen", recorder)
    return recorder


def test_core_file_uses_authenticated_contents_api(resolver, monkeypatch, sleeps):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    recorder = _install(resolver, monkeypatch, b"[project]\n")

    assert resolver.core_file("abc123", "packages/x/pyproject.toml") == b"[project]\n"

    request = recorder.requests[0]
    assert request.full_url == (
        "https://api.github.com/repos/home-assistant/core/contents/"
        "packages/x/pyproject.toml?ref=abc123"
    )
    assert request.get_header("Accept") == "application/vnd.github.raw+json"
    # Sent only to the original host, never on redirects.
    assert request.unredirected_hdrs["Authorization"] == "Bearer test-token"
    assert sleeps == []


def test_pypi_requests_are_unauthenticated(resolver, monkeypatch, sleeps):
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    recorder = _install(resolver, monkeypatch, b'{"info": {}}')

    assert resolver.metadata("homeassistant") == {"info": {}}
    request = recorder.requests[0]
    assert request.get_header("Authorization") is None
    assert "Authorization" not in request.unredirected_hdrs


def test_not_found_returns_none_without_retry(resolver, monkeypatch, sleeps):
    recorder = _install(resolver, monkeypatch, _http_error(404))

    assert resolver.core_file("abc", "missing") is None
    assert len(recorder.requests) == 1
    assert sleeps == []


def test_429_honours_retry_after_seconds(resolver, monkeypatch, sleeps):
    recorder = _install(
        resolver, monkeypatch, _http_error(429, {"Retry-After": "2"}), b"ok"
    )

    assert resolver.core_file("abc", "file") == b"ok"
    assert len(recorder.requests) == 2
    assert sleeps == [2.0]


def test_503_without_retry_after_backs_off_exponentially(resolver, monkeypatch, sleeps):
    _install(resolver, monkeypatch, _http_error(503), _http_error(503), b"ok")

    assert resolver.core_file("abc", "file") == b"ok"
    assert sleeps == [2.0, 4.0]


def test_retry_after_http_date_is_parsed(resolver, monkeypatch, sleeps):
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    _install(resolver, monkeypatch, _http_error(429, {"Retry-After": when}), b"ok")

    assert resolver.core_file("abc", "file") == b"ok"
    assert len(sleeps) == 1
    assert 8.0 <= sleeps[0] <= 10.0


def test_malformed_retry_after_falls_back_to_backoff(resolver, monkeypatch, sleeps):
    _install(resolver, monkeypatch, _http_error(429, {"Retry-After": "soon"}), b"ok")

    assert resolver.core_file("abc", "file") == b"ok"
    assert sleeps == [2.0]


def test_retry_after_above_cap_fails_without_sleeping(resolver, monkeypatch, sleeps):
    recorder = _install(
        resolver, monkeypatch, _http_error(429, {"Retry-After": "3600"})
    )

    with pytest.raises(resolver.ResolverHTTPError) as err:
        resolver.core_file("abc", "file")
    assert err.value.code == 429
    assert len(recorder.requests) == 1
    assert sleeps == []


def test_exhausted_attempts_reraise(resolver, monkeypatch, sleeps):
    recorder = _install(
        resolver, monkeypatch, _http_error(502), _http_error(502), _http_error(502)
    )

    with pytest.raises(resolver.ResolverHTTPError) as err:
        resolver.core_file("abc", "file")
    assert err.value.code == 502
    assert err.value.attempts == resolver.MAX_ATTEMPTS
    assert len(recorder.requests) == resolver.MAX_ATTEMPTS
    assert sleeps == [2.0, 4.0]


@pytest.mark.parametrize("code", [400, 403])
def test_non_retryable_errors_fail_immediately(resolver, monkeypatch, sleeps, code):
    recorder = _install(resolver, monkeypatch, _http_error(code))

    with pytest.raises(resolver.ResolverHTTPError):
        resolver.core_file("abc", "file")
    assert len(recorder.requests) == 1
    assert sleeps == []


def test_rate_limited_403_is_retried(resolver, monkeypatch, sleeps):
    _install(
        resolver,
        monkeypatch,
        _http_error(403, {"x-ratelimit-remaining": "0"}),
        b"ok",
    )

    assert resolver.core_file("abc", "file") == b"ok"
    assert sleeps == [2.0]


def _run_main(
    resolver: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    channel: str,
) -> tuple[int, str, str]:
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(sys, "argv", ["resolve_versions.py", channel])
    stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout)
    with pytest.raises(SystemExit) as exit_info:
        resolver.main()
    return int(exit_info.value.code or 0), stdout.getvalue(), output.read_text()


def test_main_reports_http_failure_and_exits_nonzero(
    resolver, monkeypatch, tmp_path, sleeps
):
    _install(resolver, monkeypatch, *[_http_error(429)] * resolver.MAX_ATTEMPTS)

    code, stdout, github_output = _run_main(resolver, monkeypatch, tmp_path, "pypi")

    assert code == 1
    note = (
        "harness_note=resolver failed: HTTP 429 reason from pypi.org "
        f"after {resolver.MAX_ATTEMPTS} attempts\n"
    )
    assert note in stdout
    assert github_output == stdout
    assert "ha_spec=\n" in stdout
    assert "harness_spec=\n" in stdout


def test_main_reports_missing_dev_branch(resolver, monkeypatch, tmp_path, sleeps):
    _install(resolver, monkeypatch, _http_error(404))

    code, stdout, _ = _run_main(resolver, monkeypatch, tmp_path, "dev")

    assert code == 1
    assert (
        "harness_note=resolver failed: RuntimeError: "
        "could not resolve the Core dev branch\n"
    ) in stdout


def test_main_reports_network_error(resolver, monkeypatch, tmp_path, sleeps):
    _install(resolver, monkeypatch, URLError("connection refused"))

    code, stdout, _ = _run_main(resolver, monkeypatch, tmp_path, "pypi")

    assert code == 1
    assert "harness_note=resolver failed: network error: connection refused\n" in stdout


def test_main_success_exits_zero(resolver, monkeypatch, tmp_path):
    monkeypatch.setattr(
        resolver,
        "resolve_pypi",
        lambda: {
            "ha_version": "1.0",
            "ha_spec": "homeassistant==1.0",
            "harness_source": "pypi",
            "harness_spec": "pytest-homeassistant==1.0",
            "harness_note": "",
        },
    )
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(sys, "argv", ["resolve_versions.py", "pypi"])

    resolver.main()

    assert "harness_spec=pytest-homeassistant==1.0\n" in output.read_text()
