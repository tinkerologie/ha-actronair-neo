"""Tests for the ActronAir Neo API client module."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.actronair_neo.api.client import (
    ActronAirNeoApiClient,
    RateLimiter,
    ResponseCache,
)
from custom_components.actronair_neo.api.const import (
    API_URL,
    API_URL_QUE,
)
from custom_components.actronair_neo.api.push.models import RealtimeConnectionDetails
from custom_components.actronair_neo.exceptions import (
    ApiError,
    AuthenticationError,
    DeviceOfflineError,
    RateLimitError,
)


def _mock_auth() -> MagicMock:
    """Create a mock auth object."""
    auth = MagicMock()
    auth.access_token = "test_token"
    auth.refresh_token_value = "test_refresh"
    auth.ensure_valid_token = AsyncMock()
    auth.get_auth_headers = AsyncMock(
        return_value={"Authorization": "Bearer test_token"}
    )
    return auth


def _mock_session() -> MagicMock:
    """Create a mock aiohttp session."""
    return MagicMock(spec=aiohttp.ClientSession)


def _make_response_ctx(status: int, body: dict | str | list) -> MagicMock:
    """Create a mock session.request context manager."""
    resp = MagicMock()
    resp.status = status
    resp.headers = {}
    if isinstance(body, (dict, list)):
        resp.text = AsyncMock(return_value=json.dumps(body))
    else:
        resp.text = AsyncMock(return_value=body)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# --- RateLimiter ---


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    @pytest.mark.asyncio
    async def test_acquire_release(self) -> None:
        limiter = RateLimiter(calls_per_minute=10)
        await limiter.acquire()
        assert len(limiter.call_times) == 1
        limiter.release()

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        limiter = RateLimiter(calls_per_minute=10)
        async with limiter:
            pass
        assert len(limiter.call_times) == 1

    @pytest.mark.asyncio
    async def test_rate_limiting_sleeps(self) -> None:
        limiter = RateLimiter(calls_per_minute=2)
        # Fill up the call times
        limiter.call_times = [
            datetime.now() - timedelta(seconds=1),
            datetime.now(),
        ]
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await limiter.acquire()
            mock_sleep.assert_called_once()
        limiter.release()


# --- ResponseCache ---


class TestResponseCache:
    @pytest.mark.asyncio
    async def test_get_set(self) -> None:
        cache = ResponseCache(default_ttl=timedelta(seconds=30))
        await cache.set("key1", {"data": True})
        result = await cache.get("key1")
        assert result == {"data": True}

    @pytest.mark.asyncio
    async def test_get_missing(self) -> None:
        cache = ResponseCache()
        assert await cache.get("missing") is None

    @pytest.mark.asyncio
    async def test_get_expired(self, freezer) -> None:
        cache = ResponseCache(default_ttl=timedelta(seconds=5))
        await cache.set("key1", {"data": True})
        freezer.move_to(datetime.now() + timedelta(seconds=10))
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_invalidate(self) -> None:
        cache = ResponseCache()
        await cache.set("key1", "val")
        await cache.invalidate("key1")
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent(self) -> None:
        cache = ResponseCache()
        await cache.invalidate("nope")  # Should not raise

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        cache = ResponseCache()
        await cache.set("a", 1)
        await cache.set("b", 2)
        await cache.clear()
        assert await cache.get("a") is None
        assert await cache.get("b") is None

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, freezer) -> None:
        cache = ResponseCache(default_ttl=timedelta(seconds=5))
        await cache.set("expired", "val")
        freezer.move_to(datetime.now() + timedelta(seconds=10))
        await cache.cleanup_expired()
        assert await cache.get("expired") is None

    @pytest.mark.asyncio
    async def test_custom_ttl_on_get(self, freezer) -> None:
        cache = ResponseCache(default_ttl=timedelta(seconds=60))
        await cache.set("key1", "val")
        freezer.move_to(datetime.now() + timedelta(seconds=5))
        result = await cache.get("key1", ttl=timedelta(seconds=1))
        assert result is None


# --- ActronAirNeoApiClient ---


class TestClientInit:
    def test_init_defaults(self) -> None:
        auth = _mock_auth()
        session = _mock_session()
        client = ActronAirNeoApiClient(auth, session)
        assert client.actron_serial == ""
        assert client.error_count == 0
        assert client.cached_status is None

    def test_is_api_healthy_initially(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.is_api_healthy() is True

    def test_is_api_healthy_degraded(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.error_count = 10
        client.last_successful_request = datetime.now()
        assert client.is_api_healthy() is False

    def test_is_api_healthy_half_open_probe_after_cooldown(self) -> None:
        """A degraded breaker permits a probe once the cooldown elapses (#112)."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.error_count = 10
        client.last_successful_request = datetime.now()

        # Freshly degraded → no probe yet (cooldown not elapsed).
        assert client.is_api_healthy() is False

        # Cooldown elapsed → half-open probe permitted.
        client._last_health_probe_time = datetime.now() - timedelta(seconds=120)
        assert client.is_api_healthy() is True

    @pytest.mark.asyncio
    async def test_get_ac_status_records_half_open_probe(self) -> None:
        """A half-open probe request updates the probe timestamp."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.error_count = 10
        client.last_successful_request = datetime.now()
        client._last_health_probe_time = datetime.now() - timedelta(seconds=120)
        client._make_request = AsyncMock(return_value={"fresh": True})

        result = await client.get_ac_status("SER1", use_cache=False)

        assert result == {"fresh": True}
        # Probe timestamp advanced so we don't immediately probe again.
        assert client.is_api_healthy() is False


class TestSetSystem:
    @pytest.mark.asyncio
    async def test_set_system_basic(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        await client.set_system("SER123", "sys1")
        assert client.actron_serial == "SER123"
        assert client.actron_system_id == "sys1"

    @pytest.mark.asyncio
    async def test_set_system_explicit_base_url(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        await client.set_system("SER123", base_url="https://custom.com")
        assert client._base_url == "https://custom.com"

    @pytest.mark.asyncio
    async def test_set_system_uses_device_urls(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._device_base_urls["SER123"] = "https://cached.com"
        await client.set_system("SER123")
        assert client._base_url == "https://cached.com"


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_calls_get_devices(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.get_devices = AsyncMock(return_value=[])
        await client.initialize()
        client.auth.ensure_valid_token.assert_called_once()
        client.get_devices.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_no_tokens(self) -> None:
        auth = _mock_auth()
        auth.access_token = None
        client = ActronAirNeoApiClient(auth, _mock_session())
        client.get_devices = AsyncMock()
        await client.initialize()
        client.get_devices.assert_not_called()


class TestMakeRequest:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        session = _mock_session()
        session.request = MagicMock(return_value=_make_response_ctx(200, {"ok": True}))
        client = ActronAirNeoApiClient(_mock_auth(), session)
        result = await client._make_request("GET", "http://test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_success_text_response(self) -> None:
        session = _mock_session()
        session.request = MagicMock(return_value=_make_response_ctx(200, "plain text"))
        client = ActronAirNeoApiClient(_mock_auth(), session)
        result = await client._make_request("GET", "http://test")
        assert result == "plain text"

    @pytest.mark.asyncio
    async def test_retry_on_timeout(self) -> None:
        session = _mock_session()
        call_count = 0

        def _request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                ctx = AsyncMock()
                ctx.__aenter__ = AsyncMock(side_effect=TimeoutError)
                ctx.__aexit__ = AsyncMock(return_value=False)
                return ctx
            return _make_response_ctx(200, {"ok": True})

        session.request = MagicMock(side_effect=_request)
        client = ActronAirNeoApiClient(_mock_auth(), session)
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await client._make_request("GET", "http://test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self) -> None:
        session = _mock_session()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=TimeoutError)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.request = MagicMock(return_value=ctx)
        client = ActronAirNeoApiClient(_mock_auth(), session)
        with (
            patch(
                "custom_components.actronair_neo.api.client.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(ApiError, match="after 3 attempts"),
        ):
            await client._make_request("GET", "http://test")

    @pytest.mark.asyncio
    async def test_no_auth_headers(self) -> None:
        session = _mock_session()
        session.request = MagicMock(return_value=_make_response_ctx(200, {"ok": True}))
        client = ActronAirNeoApiClient(_mock_auth(), session)
        await client._make_request("GET", "http://test", auth_required=False)
        client.auth.get_auth_headers.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_retries_hits_fallback_raise(self) -> None:
        """When retries are zero, _make_request raises the fallback ApiError."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with (
            patch("custom_components.actronair_neo.api.client.MAX_RETRIES", 0),
            pytest.raises(ApiError, match="Failed to make request"),
        ):
            await client._make_request("GET", "http://test")


class TestExecuteRequest:
    @pytest.mark.asyncio
    async def test_non_200_calls_error_handler(self) -> None:
        """Non-200 responses should delegate to _handle_error_status."""
        session = _mock_session()
        response = MagicMock()
        response.status = 400
        response.text = AsyncMock(return_value="bad")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=response)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.request = MagicMock(return_value=ctx)

        client = ActronAirNeoApiClient(_mock_auth(), session)
        with patch.object(
            client, "_handle_error_status", return_value={"handled": True}
        ) as mock_handle:
            result = await client._execute_request("GET", "http://test", 0)

        assert result == {"handled": True}
        mock_handle.assert_called_once_with(response, "bad", 0)


class TestHandleErrorStatus:
    def _make_resp(self, status: int, text: str = "") -> MagicMock:
        resp = MagicMock()
        resp.status = status
        resp.headers = {}
        return resp

    def test_401_raises_auth_error(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(AuthenticationError, match="Unauthorized"):
            client._handle_error_status(self._make_resp(401), "unauth", 0)

    def test_429_raises_rate_limit(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        resp = self._make_resp(429)
        resp.headers = {"Retry-After": "30"}
        with pytest.raises(RateLimitError, match="Rate limit"):
            client._handle_error_status(resp, "rate limit", 0)

    def test_503_device_offline_structured(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER123"
        body = json.dumps({"type": "unavailable"})
        with pytest.raises(DeviceOfflineError, match="unavailable"):
            client._handle_error_status(self._make_resp(503), body, 0)

    def test_503_device_offline_text(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER123"
        with pytest.raises(DeviceOfflineError, match="offline"):
            client._handle_error_status(self._make_resp(503), "device is offline", 0)

    def test_503_generic(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError, match="Service unavailable"):
            client._handle_error_status(self._make_resp(503), "some 503 error", 0)

    def test_4xx_client_error(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError, match="Client error"):
            client._handle_error_status(self._make_resp(404), "not found", 0)

    def test_5xx_server_error(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError, match="Server error"):
            client._handle_error_status(self._make_resp(500), "internal", 2)

    def test_unexpected_status(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError, match="Unexpected"):
            client._handle_error_status(self._make_resp(600), "weird", 0)


class TestHandleServerError:
    def test_raises_on_final_attempt(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError, match="Server error"):
            client._handle_server_error(500, "error", 2)

    def test_raises_on_early_attempt_too(self) -> None:
        """_handle_server_error always raises."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError):
            client._handle_server_error(500, "error", 0)


class TestTryParseJson:
    def test_valid_json(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client._try_parse_json('{"a": 1}') == {"a": 1}

    def test_invalid_json(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client._try_parse_json("not json") is None


class TestGetDevices:
    @pytest.mark.asyncio
    async def test_get_devices_success(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        api_response = {
            "_embedded": {
                "ac-system": [
                    {
                        "serial": "SER1",
                        "description": "Living Room",
                        "type": "default",
                        "id": "id1",
                    },
                    {
                        "serial": "SER2",
                        "description": "Bedroom",
                        "type": "NX-Gen",
                        "id": "id2",
                    },
                ]
            }
        }
        client._make_request = AsyncMock(return_value=api_response)
        devices = await client.get_devices()
        assert len(devices) == 2
        assert devices[0].serial == "SER1"
        assert devices[0].base_url == API_URL
        assert devices[1].serial == "SER2"
        assert devices[1].base_url == API_URL_QUE

    @pytest.mark.asyncio
    async def test_get_devices_empty(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(return_value={"_embedded": {}})
        devices = await client.get_devices()
        assert devices == []

    @pytest.mark.asyncio
    async def test_get_devices_no_embedded(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(return_value={})
        devices = await client.get_devices()
        assert devices == []


class TestResolveBaseUrl:
    def test_default_type(self) -> None:
        assert ActronAirNeoApiClient._resolve_base_url({"type": "default"}) == API_URL

    def test_nxgen_type(self) -> None:
        assert (
            ActronAirNeoApiClient._resolve_base_url({"type": "NX-Gen"}) == API_URL_QUE
        )

    def test_nxgen_lowercase(self) -> None:
        assert ActronAirNeoApiClient._resolve_base_url({"type": "nxgen"}) == API_URL_QUE

    def test_empty_type(self) -> None:
        assert ActronAirNeoApiClient._resolve_base_url({}) == API_URL


class TestGetAcStatus:
    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        await client.response_cache.set("ac_status_SER1", {"cached": True})
        result = await client.get_ac_status("SER1")
        assert result == {"cached": True}

    @pytest.mark.asyncio
    async def test_cache_miss(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(return_value={"fresh": True})
        result = await client.get_ac_status("SER1")
        assert result == {"fresh": True}

    @pytest.mark.asyncio
    async def test_unhealthy_uses_cached(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.error_count = 10
        client.last_successful_request = datetime.now()
        client.cached_status = {"old": True}
        result = await client.get_ac_status("SER1")
        assert result == {"old": True}

    @pytest.mark.asyncio
    async def test_unhealthy_no_cache(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.error_count = 10
        client.last_successful_request = datetime.now()
        result = await client.get_ac_status("SER1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_no_cache(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(return_value={"data": True})
        result = await client.get_ac_status("SER1", use_cache=False)
        assert result == {"data": True}

    @pytest.mark.asyncio
    async def test_pending_request_success_reused(self) -> None:
        """Test successful existing pending request is reused."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        key = "get_ac_status_SER1"
        pending: asyncio.Future[dict[str, bool]] = asyncio.Future()
        pending.set_result({"pending": True})
        client._pending_requests[key] = pending

        result = await client.get_ac_status("SER1")

        assert result == {"pending": True}

    @pytest.mark.asyncio
    async def test_pending_request_error_recovers_with_new_request(self) -> None:
        """If existing pending request failed, a new request should be made."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        serial = "SER1"
        key = f"get_ac_status_{serial}"
        failed_future: asyncio.Future[dict[str, bool]] = asyncio.Future()
        failed_future.set_exception(ApiError("pending failed"))
        client._pending_requests[key] = failed_future
        client._make_request = AsyncMock(return_value={"fresh": True})

        result = await client.get_ac_status(serial)

        assert result == {"fresh": True}
        assert key not in client._pending_requests

    @pytest.mark.asyncio
    async def test_make_request_failure_sets_future_exception_and_reraises(
        self,
    ) -> None:
        """Failure in _make_request should set pending future exception and re-raise."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(side_effect=ApiError("boom"))

        with pytest.raises(ApiError, match="boom"):
            await client.get_ac_status("SER1")
        assert "get_ac_status_SER1" not in client._pending_requests


class TestSendCommand:
    @pytest.mark.asyncio
    async def test_send_command_success(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(return_value={"status": "ok"})
        client._invalidate_status_cache = AsyncMock()
        result = await client.send_command("SER1", {"command": {"type": "test"}})
        assert result == {"status": "ok"}
        client._invalidate_status_cache.assert_called_once_with("SER1")

    @pytest.mark.asyncio
    async def test_send_command_retries_on_retryable(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        call_count = 0

        async def _make_req(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ApiError("err", status_code=500)
            return {"status": "ok"}

        client._make_request = AsyncMock(side_effect=_make_req)
        client._invalidate_status_cache = AsyncMock()
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            result = await client.send_command("SER1", {"cmd": True})
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_send_command_raises_non_retryable(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(side_effect=ApiError("err", status_code=400))
        with pytest.raises(ApiError):
            await client.send_command("SER1", {"cmd": True})

    @pytest.mark.asyncio
    async def test_send_command_invalidates_cache_on_failure(self) -> None:
        """Cache is invalidated even when a command fails (issue #112)."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(side_effect=ApiError("err", status_code=400))
        client._invalidate_status_cache = AsyncMock()

        with pytest.raises(ApiError):
            await client.send_command("SER1", {"cmd": True})

        client._invalidate_status_cache.assert_called_once_with("SER1")

    @pytest.mark.asyncio
    async def test_send_command_timeout_then_success(self) -> None:
        """Test timeout/jsondecode branch retries and can then succeed."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._invalidate_status_cache = AsyncMock()
        client._make_request = AsyncMock(
            side_effect=[
                TimeoutError(),
                json.JSONDecodeError("bad", "x", 0),
                {"ok": True},
            ]
        )

        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            result = await client.send_command("SER1", {"cmd": True})

        assert result == {"ok": True}
        # Transient errors back off before retrying (issue #112 review).
        assert mock_sleep.await_count == 2
        client._invalidate_status_cache.assert_called_once_with("SER1")

    @pytest.mark.asyncio
    async def test_send_command_timeout_final_attempt_raises(self) -> None:
        """Test timeout branch re-raises on final attempt."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._make_request = AsyncMock(side_effect=TimeoutError())
        with (
            patch("custom_components.actronair_neo.api.client.MAX_RETRIES", 1),
            pytest.raises(TimeoutError),
        ):
            await client.send_command("SER1", {"cmd": True})

    @pytest.mark.asyncio
    async def test_send_command_zero_retries_hits_fallback_raise(self) -> None:
        """When retries are zero, send_command raises fallback ApiError."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with (
            patch("custom_components.actronair_neo.api.client.MAX_RETRIES", 0),
            pytest.raises(ApiError, match="Failed to send command"),
        ):
            await client.send_command("SER1", {"cmd": True})


class TestCreateCommand:
    def test_on(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("ON")
        assert cmd["command"]["UserAirconSettings.isOn"] is True

    def test_off(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("OFF")
        assert cmd["command"]["UserAirconSettings.isOn"] is False

    def test_climate_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("CLIMATE_MODE", mode="COOL")
        assert cmd["command"]["UserAirconSettings.Mode"] == "COOL"
        assert cmd["command"]["UserAirconSettings.isOn"] is True

    def test_fan_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("FAN_MODE", mode="HIGH")
        assert cmd["command"]["UserAirconSettings.FanMode"] == "HIGH"

    def test_set_temp_cool(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("SET_TEMP", temp=22.0, is_cool=True)
        assert cmd["command"]["UserAirconSettings.TemperatureSetpoint_Cool_oC"] == 22.0

    def test_set_temp_heat(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("SET_TEMP", temp=20.0, is_cool=False)
        assert cmd["command"]["UserAirconSettings.TemperatureSetpoint_Heat_oC"] == 20.0

    def test_away_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("AWAY_MODE", state=True)
        assert cmd["command"]["UserAirconSettings.AwayMode"] is True

    @pytest.mark.parametrize(
        "position",
        [{}, {"position": -1}, {"position": True}, {"position": "0"}],
    )
    def test_schedule_event_requires_valid_position(self, position: dict) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ApiError, match="non-negative integer"):
            client.create_command("SCHEDULE_EVENT_ENABLED", enabled=False, **position)

    def test_quiet_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("QUIET_MODE", state=True)
        assert cmd["command"]["UserAirconSettings.QuietMode"] is True

    def test_set_zone_temp(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command(
            "SET_ZONE_TEMP",
            zone=1,
            temp=23.0,
            temp_key="TemperatureSetpoint_oC",
        )
        assert cmd["command"]["RemoteZoneInfo[1].TemperatureSetpoint_oC"] == 23.0

    def test_set_zone_state(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        zones = [True, False, True, False, False, False, False, False]
        cmd = client.create_command("SET_ZONE_STATE", zones=zones)
        assert cmd["command"]["UserAirconSettings.EnabledZones"] == zones

    def test_set_zone_airflow(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("SET_ZONE_AIRFLOW", zone=2, airflow=75)
        assert cmd["command"]["RemoteZoneInfo[2].AirflowSetpoint"] == 75

    def test_turbo_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("TURBO_MODE", state=True)
        assert cmd["command"]["UserAirconSettings.TurboMode.Enabled"] is True

    def test_after_hours_enabled(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("AFTER_HOURS_ENABLED", state=True)
        assert cmd["command"]["UserAirconSettings.AfterHours.Enabled"] is True

    def test_after_hours_duration(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        cmd = client.create_command("AFTER_HOURS_DURATION", duration=120)
        assert cmd["command"]["UserAirconSettings.AfterHours.Duration"] == 120


class TestZoneOperations:
    @pytest.mark.asyncio
    async def test_get_zone_statuses(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        status = {
            "lastKnownState": {
                "UserAirconSettings": {"EnabledZones": [True, False, True]}
            }
        }
        client.get_ac_status = AsyncMock(return_value=status)
        result = await client.get_zone_statuses()
        assert result == [True, False, True]

    @pytest.mark.asyncio
    async def test_get_zone_statuses_from_cached(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        status = {
            "lastKnownState": {"UserAirconSettings": {"EnabledZones": [False, True]}}
        }
        result = await client.get_zone_statuses(cached_status=status)
        assert result == [False, True]

    @pytest.mark.asyncio
    async def test_get_zone_statuses_malformed(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.get_ac_status = AsyncMock(return_value={})
        with pytest.raises(ApiError, match="malformed"):
            await client.get_zone_statuses()

    @pytest.mark.asyncio
    async def test_get_zone_statuses_not_list(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        status = {"lastKnownState": {"UserAirconSettings": {"EnabledZones": "bad"}}}
        client.get_ac_status = AsyncMock(return_value=status)
        with pytest.raises(ApiError, match="expected list"):
            await client.get_zone_statuses()

    @pytest.mark.asyncio
    async def test_set_zone_state(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.get_zone_statuses = AsyncMock(
            return_value=[True, False, False, False, False, False, False, False]
        )
        client.send_command = AsyncMock(return_value={})
        await client.set_zone_state(1, enable=True)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_zone_state_invalid_index(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ValueError, match="between 0 and 7"):
            await client.set_zone_state(8, enable=True)

    def test_get_zone_capabilities(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        zone_data = {
            "CanOperate": True,
            "NV_Exists": True,
            "NV_VAV": True,
            "NV_ITC": True,
            "TemperatureSetpoint_Cool_oC": 24.0,
            "TemperatureSetpoint_Heat_oC": 20.0,
        }
        caps = client.get_zone_capabilities(zone_data)
        assert caps.can_operate is True
        assert caps.exists is True
        assert caps.has_temp_control is True
        assert caps.has_separate_targets is True

    @pytest.mark.asyncio
    async def test_set_zone_temperature_single(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_zone_temperature(0, temperature=22.0)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_zone_temperature_dual(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_zone_temperature(0, target_cool=24.0, target_heat=20.0)
        assert client.send_command.call_count == 2

    @pytest.mark.asyncio
    async def test_set_zone_temperature_invalid_zone(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(IndexError, match="out of bounds"):
            await client.set_zone_temperature(9, temperature=22.0)

    @pytest.mark.asyncio
    async def test_set_zone_temperature_out_of_range(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ValueError, match="outside valid range"):
            await client.set_zone_temperature(0, temperature=5.0)

    @pytest.mark.asyncio
    async def test_set_zone_temperature_no_params(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ValueError, match="Must provide"):
            await client.set_zone_temperature(0)

    @pytest.mark.asyncio
    async def test_set_zone_airflow(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_zone_airflow(0, 50)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_zone_airflow_invalid_zone(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(IndexError, match="out of bounds"):
            await client.set_zone_airflow(8, 50)

    @pytest.mark.asyncio
    async def test_set_zone_airflow_out_of_range(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ValueError, match="out of range"):
            await client.set_zone_airflow(0, 110)

    @pytest.mark.asyncio
    async def test_set_zone_airflow_bad_increment(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        with pytest.raises(ValueError, match="increments"):
            await client.set_zone_airflow(0, 13)


class TestHvacMethods:
    async def test_set_schedule_enabled_sends_partial_command(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        await client.set_system("SER1")
        client.send_command = AsyncMock()

        await client.set_schedule_enabled(enabled=True)

        client.send_command.assert_awaited_once_with(
            "SER1", {"command": {"type": "set-settings", "NV_Schedule.Enabled": True}}
        )

    async def test_set_schedule_event_enabled_sends_indexed_command(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        await client.set_system("SER1")
        client.send_command = AsyncMock()

        await client.set_schedule_event_enabled(2, enabled=False)

        client.send_command.assert_awaited_once_with(
            "SER1",
            {
                "command": {
                    "type": "set-settings",
                    "NV_Schedule.Events[2].Enabled": False,
                }
            },
        )

    @pytest.mark.asyncio
    async def test_set_climate_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_climate_mode("COOL")
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_fan_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client._min_fan_mode_interval = 0
        client.send_command = AsyncMock(return_value={})
        await client.set_fan_mode("HIGH")
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_fan_mode_with_throttling(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client._min_fan_mode_interval = 1
        client._last_fan_mode_change = datetime.now()
        client.send_command = AsyncMock(return_value={})
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await client.set_fan_mode("LOW")
            mock_sleep.assert_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode_retries(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client._min_fan_mode_interval = 0
        call_count = 0

        async def _send(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ApiError("err", status_code=500)
            return {}

        client.send_command = AsyncMock(side_effect=_send)
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await client.set_fan_mode("MED")

    @pytest.mark.asyncio
    async def test_set_fan_mode_final_retry_raises(self) -> None:
        """Retryable errors should raise on final retry attempt."""
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client._min_fan_mode_interval = 0
        client.send_command = AsyncMock(side_effect=ApiError("err", status_code=500))
        with (
            patch("custom_components.actronair_neo.api.client.MAX_RETRIES", 1),
            pytest.raises(ApiError, match="err"),
        ):
            await client.set_fan_mode("MED")

    @pytest.mark.asyncio
    async def test_set_temperature(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_temperature(22.0, is_cooling=True)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_away_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_away_mode(state=True)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_quiet_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_quiet_mode(state=True)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_turbo_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_turbo_mode(state=True)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_after_hours(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_after_hours(enabled=True)
        client.send_command.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_after_hours_duration(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        await client.set_after_hours_duration(120)
        client.send_command.assert_called_once()


class TestValidateFanMode:
    def test_empty_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("") == "LOW"

    def test_empty_mode_continuous(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("", continuous=True) == "LOW+CONT"

    def test_valid_mode(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("HIGH") == "HIGH"

    def test_mode_with_cont_suffix(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("HIGH+CONT") == "HIGH"

    def test_mode_with_dash(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("LOW-something") == "LOW"

    def test_invalid_mode_falls_back(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("TURBO") == "LOW"

    def test_continuous_flag(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode("MED", continuous=True) == "MED+CONT"

    def test_invalid_type_returns_fallback(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode(None, continuous=True) == "LOW+CONT"  # type: ignore[arg-type]

    def test_mode_strip_raises_type_error_falls_back(self) -> None:
        """Test validation fallback when strip() raises type error."""

        class BrokenMode:
            def __bool__(self) -> bool:
                return True

            def strip(self) -> str:
                msg = "bad mode"
                raise TypeError(msg)

        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        assert client.validate_fan_mode(BrokenMode(), continuous=True) == "LOW+CONT"  # type: ignore[arg-type]


class TestCacheManagement:
    @pytest.mark.asyncio
    async def test_invalidate_status_cache(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.cached_status = {"data": True}
        await client.response_cache.set("ac_status_SER1", {"data": True})
        await client._invalidate_status_cache("SER1")
        assert client.cached_status is None
        assert await client.response_cache.get("ac_status_SER1") is None

    @pytest.mark.asyncio
    async def test_clear_all_caches(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.cached_status = {"data": True}
        await client.response_cache.set("key", "val")
        await client.clear_all_caches()
        assert client.cached_status is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_cache(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        await client.cleanup_expired_cache()  # Should not raise


# --- Realtime push: discovery and token provider ---


@pytest.mark.asyncio
async def test_get_realtime_connection_details_parses_response():
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    client._make_request = AsyncMock(
        return_value={"endpoint": "mqtt.example", "port": 8883, "userId": "u1"}
    )
    details = await client.get_realtime_connection_details("SER123")
    assert isinstance(details, RealtimeConnectionDetails)
    assert details.endpoint == "mqtt.example"
    assert details.port == 8883


@pytest.mark.asyncio
async def test_get_realtime_connection_details_none_on_non_dict():
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    client._make_request = AsyncMock(return_value="oops")
    assert await client.get_realtime_connection_details("SER123") is None


@pytest.mark.asyncio
async def test_get_realtime_access_token_returns_token():
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    assert await client.get_realtime_access_token() == "test_token"


@pytest.mark.asyncio
async def test_get_realtime_access_token_raises_when_missing():
    auth = _mock_auth()
    auth.access_token = None
    client = ActronAirNeoApiClient(auth, _mock_session())
    with pytest.raises(AuthenticationError):
        await client.get_realtime_access_token()


def test_platform_property_defaults_to_neo():
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    assert client.platform == "neo"


@pytest.mark.asyncio
async def test_get_realtime_connection_details_none_when_no_endpoint():
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    client._make_request = AsyncMock(return_value={"port": 8883})
    assert await client.get_realtime_connection_details("SER123") is None


@pytest.mark.asyncio
async def test_get_realtime_access_token_ensures_valid_token():
    auth = _mock_auth()
    client = ActronAirNeoApiClient(auth, _mock_session())
    await client.get_realtime_access_token()
    auth.ensure_valid_token.assert_awaited_once()


def test_platform_property_que_for_que_base_url():
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    client._base_url = API_URL_QUE
    assert client.platform == "que"


# --- Coverage: cache length, retry on status, HAL links, account email ---


@pytest.mark.asyncio
async def test_response_cache_len() -> None:
    cache = ResponseCache()
    assert len(cache) == 0
    await cache.set("a", 1)
    await cache.set("b", 2)
    assert len(cache) == 2


class TestMakeRequestRetryableStatus:
    @pytest.mark.asyncio
    async def test_retryable_status_sleeps_then_succeeds(self) -> None:
        session = _mock_session()
        session.request = MagicMock(
            side_effect=[
                _make_response_ctx(500, "boom"),
                _make_response_ctx(502, "boom"),
                _make_response_ctx(200, {"ok": True}),
            ]
        )
        client = ActronAirNeoApiClient(_mock_auth(), session)
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            result = await client._make_request("GET", "http://test")
        assert result == {"ok": True}
        assert [c.args[0] for c in mock_sleep.await_args_list] == [5, 10]
        assert client.error_count == 0

    @pytest.mark.asyncio
    async def test_retryable_status_exhausted_raises(self) -> None:
        session = _mock_session()
        session.request = MagicMock(
            side_effect=lambda *a, **k: _make_response_ctx(500, "boom")
        )
        client = ActronAirNeoApiClient(_mock_auth(), session)
        with (
            patch(
                "custom_components.actronair_neo.api.client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            pytest.raises(ApiError, match="Server error") as exc_info,
        ):
            await client._make_request("GET", "http://test")
        assert exc_info.value.status_code == 500
        assert session.request.call_count == 3
        assert mock_sleep.await_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_status_raises_immediately(self) -> None:
        session = _mock_session()
        session.request = MagicMock(return_value=_make_response_ctx(404, "nope"))
        client = ActronAirNeoApiClient(_mock_auth(), session)
        with (
            patch(
                "custom_components.actronair_neo.api.client.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            pytest.raises(ApiError, match="Client error"),
        ):
            await client._make_request("GET", "http://test")
        assert session.request.call_count == 1
        mock_sleep.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_api_error_without_status_raises_immediately(self) -> None:
        auth = _mock_auth()
        auth.get_auth_headers = AsyncMock(side_effect=ApiError("no status"))
        session = _mock_session()
        session.request = MagicMock()
        client = ActronAirNeoApiClient(auth, session)
        with pytest.raises(ApiError, match="no status"):
            await client._make_request("GET", "http://test")
        session.request.assert_not_called()


class TestHalLinks:
    def test_extract_hal_links_valid(self) -> None:
        links = ActronAirNeoApiClient._extract_hal_links(
            {
                "_links": {
                    "self": {"href": "/api/v0/self"},
                    "rtc-details": {"href": "https://x.example/rtc"},
                    "empty": {"href": ""},
                    "non-str": {"href": 123},
                    "missing": {},
                    "not-dict": "oops",
                }
            }
        )
        assert links == {
            "self": "/api/v0/self",
            "rtc-details": "https://x.example/rtc",
        }

    @pytest.mark.parametrize("raw", [None, [], "x"])
    def test_extract_hal_links_not_dict(self, raw) -> None:
        system = {} if raw is None else {"_links": raw}
        assert ActronAirNeoApiClient._extract_hal_links(system) == {}

    def test_resolve_endpoint_url_absolute(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._device_links["SERIAL1"] = {"rel": "https://abs.example/path"}
        assert (
            client._resolve_endpoint_url("SERIAL1", "rel", "/default")
            == "https://abs.example/path"
        )

    def test_resolve_endpoint_url_relative(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._device_links["SERIAL1"] = {"rel": "/api/v0/rel?x=1"}
        assert (
            client._resolve_endpoint_url("SERIAL1", "rel", "/default")
            == f"{API_URL}/api/v0/rel?x=1"
        )

    def test_resolve_endpoint_url_fallback(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client._device_links["SERIAL1"] = {"other": "/x"}
        assert (
            client._resolve_endpoint_url("SERIAL1", "rel", "/default?q=1")
            == f"{API_URL}/default?q=1"
        )
        assert (
            client._resolve_endpoint_url("UNKNOWN", "rel", "/default")
            == f"{API_URL}/default"
        )

    @pytest.mark.asyncio
    async def test_get_devices_stores_links(self) -> None:
        session = _mock_session()
        session.request = MagicMock(
            return_value=_make_response_ctx(
                200,
                {
                    "_embedded": {
                        "ac-system": [
                            {
                                "serial": "SER1",
                                "description": "Lounge",
                                "type": "default",
                                "id": "id1",
                                "_links": {"rtc-details": {"href": "/api/v0/rtc/SER1"}},
                            },
                            {
                                "serial": "SER2",
                                "description": "Bed",
                                "type": "default",
                                "id": "id2",
                            },
                        ]
                    }
                },
            )
        )
        client = ActronAirNeoApiClient(_mock_auth(), session)
        devices = await client.get_devices()
        assert devices[0].links == {"rtc-details": "/api/v0/rtc/SER1"}
        assert devices[1].links == {}
        assert client._device_links == {"SER1": {"rtc-details": "/api/v0/rtc/SER1"}}
        assert (
            client._resolve_endpoint_url("SER1", "rtc-details", "/default")
            == f"{API_URL}/api/v0/rtc/SER1"
        )


class TestGetAccountEmail:
    @pytest.mark.asyncio
    async def test_cached_value_returned_without_request(self) -> None:
        session = _mock_session()
        session.request = MagicMock()
        client = ActronAirNeoApiClient(_mock_auth(), session)
        client._account_email = "cached@example.com"
        assert await client.get_account_email() == "cached@example.com"
        session.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_caches_email(self) -> None:
        session = _mock_session()
        session.request = MagicMock(
            return_value=_make_response_ctx(
                200, {"id": "u1", "email": "user@example.com"}
            )
        )
        client = ActronAirNeoApiClient(_mock_auth(), session)
        assert await client.get_account_email() == "user@example.com"
        assert await client.get_account_email() == "user@example.com"
        assert session.request.call_count == 1
        assert session.request.call_args.args[1].endswith("/api/v0/client/account")

    @pytest.mark.asyncio
    async def test_api_error_falls_back_to_empty(self) -> None:
        session = _mock_session()
        session.request = MagicMock(return_value=_make_response_ctx(404, "nope"))
        client = ActronAirNeoApiClient(_mock_auth(), session)
        assert await client.get_account_email() == ""
        assert client._account_email == ""

    @pytest.mark.asyncio
    async def test_validation_error_falls_back_to_empty(self) -> None:
        session = _mock_session()
        session.request = MagicMock(
            return_value=_make_response_ctx(200, {"email": ["not", "a", "string"]})
        )
        client = ActronAirNeoApiClient(_mock_auth(), session)
        assert await client.get_account_email() == ""
        assert client._account_email == ""

    @pytest.mark.asyncio
    async def test_non_dict_response_falls_back_to_empty(self) -> None:
        session = _mock_session()
        session.request = MagicMock(return_value=_make_response_ctx(200, "plain"))
        client = ActronAirNeoApiClient(_mock_auth(), session)
        assert await client.get_account_email() == ""
        assert client._account_email == ""


def test_create_command_unknown_type_raises() -> None:
    client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
    with pytest.raises(ApiError, match="Unknown command type: BOGUS"):
        client.create_command("BOGUS")


@pytest.mark.asyncio
async def test_set_system_auth_without_update_base_url() -> None:
    auth = _mock_auth()
    auth.update_base_url = None
    client = ActronAirNeoApiClient(auth, _mock_session())
    await client.set_system("SER1", base_url=API_URL_QUE)
    assert client._base_url == API_URL_QUE


@pytest.mark.asyncio
async def test_set_system_syncs_auth_base_url() -> None:
    auth = _mock_auth()
    client = ActronAirNeoApiClient(auth, _mock_session())
    await client.set_system("SER1", base_url=API_URL_QUE)
    auth.update_base_url.assert_called_once_with(API_URL_QUE)


class TestGetAcStatusFutureEdges:
    @pytest.mark.asyncio
    async def test_future_already_resolved_by_other_party(self) -> None:
        """A future completed during the request is left untouched."""
        session = _mock_session()
        client = ActronAirNeoApiClient(_mock_auth(), session)
        key = "get_ac_status_SER1"

        def _request(*args, **kwargs):
            client._pending_requests[key].set_result({"other": True})
            return _make_response_ctx(200, {"fresh": True})

        session.request = MagicMock(side_effect=_request)
        result = await client.get_ac_status("SER1", use_cache=False)
        assert result == {"fresh": True}
        assert key not in client._pending_requests

    @pytest.mark.asyncio
    async def test_future_already_failed_by_other_party(self) -> None:
        """A future failed during the request does not get a second exception."""
        session = _mock_session()
        client = ActronAirNeoApiClient(_mock_auth(), session)
        key = "get_ac_status_SER1"

        def _request(*args, **kwargs):
            client._pending_requests[key].set_exception(ApiError("other"))
            return _make_response_ctx(404, "nope")

        session.request = MagicMock(side_effect=_request)
        with pytest.raises(ApiError, match="Client error"):
            await client.get_ac_status("SER1")
        assert key not in client._pending_requests

    @pytest.mark.asyncio
    async def test_cancellation_cancels_future_and_cleans_up(self) -> None:
        """A cancelled owner cancels its published future and removes the key."""
        session = _mock_session()
        client = ActronAirNeoApiClient(_mock_auth(), session)
        published: list[asyncio.Future] = []

        def _request(*args, **kwargs):
            published.append(client._pending_requests["get_ac_status_SER1"])
            raise asyncio.CancelledError

        session.request = MagicMock(side_effect=_request)
        with pytest.raises(asyncio.CancelledError):
            await client.get_ac_status("SER1")
        assert published[0].cancelled()
        assert "get_ac_status_SER1" not in client._pending_requests


_STATUS_PAYLOAD = {"lastKnownState": {"ok": True}}


class _GatedRequests:
    """Fake ``_make_request``: gated, counted, first call optionally blocks."""

    def __init__(self, *, block_first: bool) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self._block_first = block_first

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        self.started.set()
        if self._block_first and self.calls == 1:
            await asyncio.Event().wait()  # blocks until cancelled
        await self.release.wait()
        return dict(_STATUS_PAYLOAD)


class TestGetAcStatusCancellation:
    """Deduplicated get_ac_status survives owner and waiter cancellation (#227)."""

    @pytest.mark.asyncio
    async def test_release_pending_future_settles_every_state(self) -> None:
        release = ActronAirNeoApiClient._release_pending_future
        loop = asyncio.get_running_loop()

        pending = loop.create_future()
        release(pending)
        assert pending.cancelled()

        already_cancelled = loop.create_future()
        already_cancelled.cancel()
        release(already_cancelled)
        assert already_cancelled.cancelled()

        failed = loop.create_future()
        failed.set_exception(ApiError("boom"))
        release(failed)  # retrieves the exception; no "never retrieved" warning
        assert isinstance(failed.exception(), ApiError)

        done = loop.create_future()
        done.set_result({"ok": True})
        release(done)
        assert done.result() == {"ok": True}

    @pytest.mark.asyncio
    async def test_waiter_reissues_when_owner_cancelled(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        fake = _GatedRequests(block_first=True)
        client._make_request = fake  # type: ignore[method-assign]
        key = "get_ac_status_SER1"

        owner = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        await asyncio.wait_for(fake.started.wait(), 1)
        waiter = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        await asyncio.sleep(0)

        owner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner
        fake.release.set()
        assert await asyncio.wait_for(waiter, 1) == _STATUS_PAYLOAD
        assert fake.calls == 2
        assert key not in client._pending_requests

        # Deduplication still works afterwards: two calls, one request.
        fake.release.clear()
        first = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        second = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        fake.release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 1)
        assert results == [_STATUS_PAYLOAD, _STATUS_PAYLOAD]
        assert fake.calls == 3

    @pytest.mark.asyncio
    async def test_cancelled_waiter_does_not_cancel_shared_request(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        fake = _GatedRequests(block_first=False)
        client._make_request = fake  # type: ignore[method-assign]

        owner = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        await asyncio.wait_for(fake.started.wait(), 1)
        shared = client._pending_requests["get_ac_status_SER1"]
        waiter_a = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        waiter_b = asyncio.create_task(client.get_ac_status("SER1", use_cache=False))
        await asyncio.sleep(0)

        waiter_a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter_a
        assert not shared.cancelled()

        fake.release.set()
        assert await asyncio.wait_for(owner, 1) == _STATUS_PAYLOAD
        assert await asyncio.wait_for(waiter_b, 1) == _STATUS_PAYLOAD
        assert fake.calls == 1


class TestSetFanModeBranches:
    @pytest.mark.asyncio
    async def test_explicit_continuous_and_no_throttle_needed(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client._min_fan_mode_interval = 1
        client._last_fan_mode_change = datetime.now() - timedelta(minutes=5)
        client.send_command = AsyncMock(return_value={})
        with patch(
            "custom_components.actronair_neo.api.client.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await client.set_fan_mode("HIGH", continuous=True)
        mock_sleep.assert_not_awaited()
        assert client._continuous_fan is True
        command = client.send_command.call_args.args[1]
        assert command["command"]["UserAirconSettings.FanMode"] == "HIGH+CONT"

    @pytest.mark.asyncio
    async def test_zero_retries_sends_nothing(self) -> None:
        client = ActronAirNeoApiClient(_mock_auth(), _mock_session())
        client.actron_serial = "SER1"
        client.send_command = AsyncMock(return_value={})
        with patch("custom_components.actronair_neo.api.client.MAX_RETRIES", 0):
            await client.set_fan_mode("HIGH")
        client.send_command.assert_not_called()
        assert client._last_fan_mode_change is None
