"""Tests for the ActronAir Neo API auth module."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.actronair_neo.api.auth import (
    ActronAirNeoAuth,
    DeviceCodeResponse,
)
from custom_components.actronair_neo.api.const import (
    DEVICE_CODE_POLL_INTERVAL,
    MAX_REFRESH_RETRIES,
    REFRESH_RETRY_DELAY,
    TOKEN_EXPIRY_BUFFER,
)
from custom_components.actronair_neo.exceptions import AuthenticationError


def _make_session() -> MagicMock:
    """Create a mock aiohttp session."""
    return MagicMock(spec=aiohttp.ClientSession)


def _make_response(status: int, body: dict | str) -> MagicMock:
    """Create a mock aiohttp response context manager."""
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(
        return_value=json.dumps(body) if isinstance(body, dict) else body
    )
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestTokenState:
    """Tests for token state helpers."""

    def test_is_token_valid_no_token(self) -> None:
        """Test is_token_valid returns False when no token."""
        auth = ActronAirNeoAuth(_make_session())
        assert auth.is_token_valid is False

    def test_is_token_valid_expired(self) -> None:
        """Test is_token_valid returns False when expired."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "tok"
        auth.token_expires_at = datetime.now() - timedelta(hours=1)
        assert auth.is_token_valid is False

    def test_is_token_valid_ok(self) -> None:
        """Test is_token_valid returns True when valid."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "tok"
        auth.token_expires_at = datetime.now() + timedelta(hours=1)
        assert auth.is_token_valid is True

    def test_set_tokens(self) -> None:
        """Test set_tokens restores tokens from storage."""
        auth = ActronAirNeoAuth(_make_session())
        future_ts = (datetime.now() + timedelta(hours=1)).timestamp()
        auth.set_tokens("at", "rt", future_ts)
        assert auth.access_token == "at"
        assert auth.refresh_token_value == "rt"
        assert auth.token_expires_at is not None


class TestTokenRefreshCallback:
    """Tests for the token-refresh callback management."""

    @pytest.mark.asyncio
    async def test_notify_token_refreshed_no_callback(self) -> None:
        """Test _notify_token_refreshed does nothing without callback."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth.refresh_token_value = "rt"
        auth.token_expires_at = datetime.now() + timedelta(hours=1)
        # Should not raise
        await auth._notify_token_refreshed()

    @pytest.mark.asyncio
    async def test_notify_token_refreshed_with_callback(self) -> None:
        """Test _notify_token_refreshed calls registered callback."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth.refresh_token_value = "rt"
        auth.token_expires_at = datetime.now() + timedelta(hours=1)

        cb = AsyncMock()
        auth.set_token_refresh_callback(cb)
        await auth._notify_token_refreshed()
        cb.assert_called_once()


class TestStoreTokenResponse:
    """Tests for _store_token_response."""

    def test_store_token_response_success(self) -> None:
        """Test storing a valid token response."""
        auth = ActronAirNeoAuth(_make_session())
        auth._store_token_response(
            {"access_token": "new", "refresh_token": "new_rt", "expires_in": 3600}
        )
        assert auth.access_token == "new"
        assert auth.refresh_token_value == "new_rt"
        assert auth.token_expires_at is not None

    def test_store_token_response_no_access_token(self) -> None:
        """Test storing a response without access_token raises error."""
        auth = ActronAirNeoAuth(_make_session())
        with pytest.raises(AuthenticationError, match="No access token"):
            auth._store_token_response({})

    def test_store_token_response_keeps_old_refresh(self) -> None:
        """Test storing keeps old refresh token if not in response."""
        auth = ActronAirNeoAuth(_make_session())
        auth.refresh_token_value = "old_rt"
        auth._store_token_response({"access_token": "new"})
        assert auth.refresh_token_value == "old_rt"


class TestMakeAuthRequest:
    """Tests for _make_auth_request."""

    @pytest.mark.asyncio
    async def test_make_auth_request_success(self) -> None:
        """Test successful auth request."""
        session = _make_session()
        session.request = MagicMock(return_value=_make_response(200, {"ok": True}))
        auth = ActronAirNeoAuth(session)
        result = await auth._make_auth_request("POST", "http://test")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_make_auth_request_non_200(self) -> None:
        """Test auth request with non-200 status raises error."""
        session = _make_session()
        session.request = MagicMock(return_value=_make_response(400, "bad request"))
        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="Auth request failed"):
            await auth._make_auth_request("POST", "http://test")

    @pytest.mark.asyncio
    async def test_make_auth_request_timeout(self) -> None:
        """Test auth request with timeout raises error."""
        session = _make_session()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=TimeoutError("timed out"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.request = MagicMock(return_value=ctx)
        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="Auth request failed"):
            await auth._make_auth_request("POST", "http://test")

    @pytest.mark.asyncio
    async def test_make_auth_request_client_error(self) -> None:
        """Test auth request with client error raises error."""
        session = _make_session()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("connection failed"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.request = MagicMock(return_value=ctx)
        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="Auth request failed"):
            await auth._make_auth_request("POST", "http://test")


class TestRequestDeviceCode:
    """Tests for request_device_code."""

    @pytest.mark.asyncio
    async def test_request_device_code_success(self) -> None:
        """Test successful device code request."""
        session = _make_session()
        session.request = MagicMock(
            return_value=_make_response(
                200,
                {
                    "device_code": "dc",
                    "user_code": "UC",
                    "verification_uri": "https://example.com",
                    "expires_in": 300,
                    "interval": 5,
                },
            )
        )
        auth = ActronAirNeoAuth(session)
        result = await auth.request_device_code()
        assert isinstance(result, DeviceCodeResponse)
        assert result.device_code == "dc"
        assert result.user_code == "UC"

    @pytest.mark.asyncio
    async def test_request_device_code_incomplete_response(self) -> None:
        """Test device code request with incomplete response."""
        session = _make_session()
        session.request = MagicMock(
            return_value=_make_response(200, {"verification_uri": "x"})
        )
        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="Incomplete"):
            await auth.request_device_code()


class TestPollForToken:
    """Tests for poll_for_token."""

    @pytest.mark.asyncio
    async def test_poll_for_token_immediate_success(self) -> None:
        """Test successful token polling."""
        session = _make_session()
        resp = MagicMock()
        resp.status = 200
        resp.text = AsyncMock(
            return_value=json.dumps(
                {"access_token": "at", "refresh_token": "rt", "expires_in": 3600}
            )
        )
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)
        auth = ActronAirNeoAuth(session)
        result = await auth.poll_for_token("dc", interval=0, expires_in=10)
        assert result["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_poll_for_token_authorization_pending(self) -> None:
        """Test polling retries on authorization_pending."""
        session = _make_session()
        call_count = 0

        async def _make_resp(_self=None):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count < 3:
                resp.status = 400
                resp.text = AsyncMock(
                    return_value=json.dumps({"error": "authorization_pending"})
                )
            else:
                resp.status = 200
                resp.text = AsyncMock(
                    return_value=json.dumps(
                        {
                            "access_token": "at",
                            "refresh_token": "rt",
                            "expires_in": 3600,
                        }
                    )
                )
            return resp

        ctx = AsyncMock()
        ctx.__aenter__ = _make_resp
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with patch("custom_components.actronair_neo.api.auth.asyncio.sleep"):
            result = await auth.poll_for_token("dc", interval=0, expires_in=60)
        assert result["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_poll_for_token_slow_down(self) -> None:
        """Test polling handles slow_down response."""
        session = _make_session()
        call_count = 0

        async def _make_resp(_self=None):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            if call_count == 1:
                resp.status = 400
                resp.text = AsyncMock(return_value=json.dumps({"error": "slow_down"}))
            else:
                resp.status = 200
                resp.text = AsyncMock(
                    return_value=json.dumps(
                        {
                            "access_token": "at",
                            "refresh_token": "rt",
                            "expires_in": 3600,
                        }
                    )
                )
            return resp

        ctx = AsyncMock()
        ctx.__aenter__ = _make_resp
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with patch("custom_components.actronair_neo.api.auth.asyncio.sleep"):
            result = await auth.poll_for_token("dc", interval=0, expires_in=60)
        assert result["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_poll_for_token_expired_token(self) -> None:
        """Test polling raises on expired token."""
        session = _make_session()
        resp = MagicMock()
        resp.status = 400
        resp.text = AsyncMock(return_value=json.dumps({"error": "expired_token"}))
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="expired"):
            await auth.poll_for_token("dc", interval=0, expires_in=10)

    @pytest.mark.asyncio
    async def test_poll_for_token_access_denied(self) -> None:
        """Test polling raises on access denied."""
        session = _make_session()
        resp = MagicMock()
        resp.status = 400
        resp.text = AsyncMock(return_value=json.dumps({"error": "access_denied"}))
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="denied"):
            await auth.poll_for_token("dc", interval=0, expires_in=10)

    @pytest.mark.asyncio
    async def test_poll_for_token_unknown_400_error(self) -> None:
        """Test polling raises on unknown 400 error."""
        session = _make_session()
        resp = MagicMock()
        resp.status = 400
        resp.text = AsyncMock(return_value=json.dumps({"error": "something_weird"}))
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="failed"):
            await auth.poll_for_token("dc", interval=0, expires_in=10)

    @pytest.mark.asyncio
    async def test_poll_for_token_unexpected_status(self) -> None:
        """Test polling raises on unexpected status code."""
        session = _make_session()
        resp = MagicMock()
        resp.status = 500
        resp.text = AsyncMock(return_value="server error")
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=resp)
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with pytest.raises(AuthenticationError, match="Unexpected"):
            await auth.poll_for_token("dc", interval=0, expires_in=10)

    @pytest.mark.asyncio
    async def test_poll_for_token_timeout_during_poll(self) -> None:
        """Test polling retries on timeout."""
        session = _make_session()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=TimeoutError("timed out"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        auth = ActronAirNeoAuth(session)
        with (
            patch("custom_components.actronair_neo.api.auth.asyncio.sleep"),
            pytest.raises(AuthenticationError, match="timed out"),
        ):
            await auth.poll_for_token("dc", interval=0, expires_in=1)


class TestRefreshAccessToken:
    """Tests for refresh_access_token."""

    @pytest.mark.asyncio
    async def test_refresh_no_refresh_token(self) -> None:
        """Test refresh raises when no refresh token available."""
        auth = ActronAirNeoAuth(_make_session())
        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(AuthenticationError, match="No refresh token"),
        ):
            await auth.refresh_access_token()

    @pytest.mark.asyncio
    async def test_refresh_success(self) -> None:
        """Test successful token refresh."""
        session = _make_session()
        session.request = MagicMock(
            return_value=_make_response(
                200,
                {
                    "access_token": "new_at",
                    "refresh_token": "new_rt",
                    "expires_in": 3600,
                },
            )
        )
        auth = ActronAirNeoAuth(session)
        auth.refresh_token_value = "old_rt"
        await auth.refresh_access_token()
        assert auth.access_token == "new_at"

    @pytest.mark.asyncio
    async def test_refresh_retries_on_failure(self) -> None:
        """Test refresh retries with backoff on failure."""
        session = _make_session()
        call_count = 0

        def _request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _make_response(400, "fail")
            return _make_response(
                200,
                {"access_token": "new", "refresh_token": "rt", "expires_in": 3600},
            )

        session.request = MagicMock(side_effect=_request)
        auth = ActronAirNeoAuth(session)
        auth.refresh_token_value = "rt"
        with patch("custom_components.actronair_neo.api.auth.asyncio.sleep"):
            await auth.refresh_access_token()
        assert auth.access_token == "new"

    @pytest.mark.asyncio
    async def test_refresh_all_retries_fail(self) -> None:
        """Test refresh raises after all retries fail."""
        session = _make_session()
        session.request = MagicMock(return_value=_make_response(400, "fail"))
        auth = ActronAirNeoAuth(session)
        auth.refresh_token_value = "rt"
        with (
            patch("custom_components.actronair_neo.api.auth.asyncio.sleep"),
            pytest.raises(AuthenticationError),
        ):
            await auth.refresh_access_token()


class TestEnsureValidToken:
    """Tests for ensure_valid_token."""

    @pytest.mark.asyncio
    async def test_ensure_valid_token_already_valid(self) -> None:
        """Test ensure_valid_token does nothing when token is valid."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth.token_expires_at = datetime.now() + timedelta(hours=1)
        # Should not raise
        await auth.ensure_valid_token()

    @pytest.mark.asyncio
    async def test_ensure_valid_token_triggers_refresh(self) -> None:
        """Test ensure_valid_token triggers refresh when expired."""
        session = _make_session()
        session.request = MagicMock(
            return_value=_make_response(
                200,
                {"access_token": "new", "refresh_token": "rt", "expires_in": 3600},
            )
        )
        auth = ActronAirNeoAuth(session)
        auth.access_token = "old"
        auth.refresh_token_value = "rt"
        auth.token_expires_at = datetime.now() - timedelta(hours=1)
        await auth.ensure_valid_token()
        assert auth.access_token == "new"


class TestGetAuthHeaders:
    """Tests for get_auth_headers."""

    @pytest.mark.asyncio
    async def test_get_auth_headers(self) -> None:
        """Test get_auth_headers returns bearer token."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "mytoken"
        auth.token_expires_at = datetime.now() + timedelta(hours=1)
        headers = await auth.get_auth_headers()
        assert headers == {"Authorization": "Bearer mytoken"}


class TestUpdateBaseUrl:
    """Tests for update_base_url."""

    def test_init_strips_trailing_slash(self) -> None:
        """Test the constructor strips a trailing slash from the base URL."""
        auth = ActronAirNeoAuth(_make_session(), base_url="https://a.example/")
        assert auth.base_url == "https://a.example"

    def test_update_base_url_strips_trailing_slash(self) -> None:
        """Test update_base_url stores the URL without a trailing slash."""
        auth = ActronAirNeoAuth(_make_session(), base_url="https://a.example")
        auth.update_base_url("https://b.example/")
        assert auth.base_url == "https://b.example"

    def test_update_base_url_empty_is_noop(self) -> None:
        """Test update_base_url ignores an empty string."""
        auth = ActronAirNeoAuth(_make_session(), base_url="https://a.example")
        auth.update_base_url("")
        assert auth.base_url == "https://a.example"


class TestActualTokenExpiry:
    """Tests for _is_token_actually_unexpired."""

    def test_no_token(self) -> None:
        """Test returns False when there is no access token."""
        auth = ActronAirNeoAuth(_make_session())
        auth._actual_token_expires_at = datetime.now(UTC) + timedelta(hours=1)
        assert auth._is_token_actually_unexpired is False

    def test_no_expiry(self) -> None:
        """Test returns False when there is no actual expiry."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        assert auth._is_token_actually_unexpired is False

    def test_future_expiry(self) -> None:
        """Test returns True when the actual expiry is in the future."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth._actual_token_expires_at = datetime.now(UTC) + timedelta(minutes=1)
        assert auth._is_token_actually_unexpired is True

    def test_past_expiry(self) -> None:
        """Test returns False when the actual expiry has passed."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth._actual_token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        assert auth._is_token_actually_unexpired is False

    def test_naive_datetime(self) -> None:
        """Test a naive expiry is compared against a naive current time."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth._actual_token_expires_at = datetime.now() + timedelta(minutes=1)
        assert auth._is_token_actually_unexpired is True
        auth._actual_token_expires_at = datetime.now() - timedelta(minutes=1)
        assert auth._is_token_actually_unexpired is False

    def test_set_tokens_sets_actual_expiry_with_buffer(self) -> None:
        """Test set_tokens records the unbuffered expiry."""
        auth = ActronAirNeoAuth(_make_session())
        auth.set_tokens("at", "rt", datetime.now(UTC).timestamp())
        assert auth.token_expires_at is not None
        assert auth._actual_token_expires_at == auth.token_expires_at + timedelta(
            seconds=TOKEN_EXPIRY_BUFFER
        )
        assert auth.is_token_valid is False
        assert auth._is_token_actually_unexpired is True


class TestRefreshCallbackEdges:
    """Tests for refresh callback edge cases."""

    @pytest.mark.asyncio
    async def test_callback_receives_token_values(self) -> None:
        """Test the callback receives access, refresh and expiry timestamp."""
        session = _make_session()
        session.request = MagicMock(
            return_value=_make_response(
                200,
                {
                    "access_token": "new_at",
                    "refresh_token": "new_rt",
                    "expires_in": 3600,
                },
            )
        )
        auth = ActronAirNeoAuth(session)
        auth.refresh_token_value = "old_rt"
        cb = AsyncMock()
        auth.set_token_refresh_callback(cb)
        await auth.refresh_access_token()
        cb.assert_awaited_once()
        access, refresh, expires_at = cb.await_args.args
        assert access == "new_at"
        assert refresh == "new_rt"
        assert auth.token_expires_at is not None
        assert expires_at == auth.token_expires_at.timestamp()

    @pytest.mark.asyncio
    async def test_callback_exception_propagates(self) -> None:
        """Test an exception raised by the callback propagates to the caller."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = "at"
        auth.refresh_token_value = "rt"
        auth.token_expires_at = datetime.now(UTC) + timedelta(hours=1)
        auth.set_token_refresh_callback(AsyncMock(side_effect=RuntimeError("boom")))
        with pytest.raises(RuntimeError, match="boom"):
            await auth._notify_token_refreshed()

    @pytest.mark.parametrize(
        ("access", "refresh", "has_expiry"),
        [
            (None, "rt", True),
            ("at", None, True),
            ("at", "rt", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_callback_skipped_when_token_data_missing(
        self, access: str | None, refresh: str | None, *, has_expiry: bool
    ) -> None:
        """Test the callback is not invoked when token data is incomplete."""
        auth = ActronAirNeoAuth(_make_session())
        auth.access_token = access
        auth.refresh_token_value = refresh
        auth.token_expires_at = (
            datetime.now(UTC) + timedelta(hours=1) if has_expiry else None
        )
        cb = AsyncMock()
        auth.set_token_refresh_callback(cb)
        await auth._notify_token_refreshed()
        cb.assert_not_awaited()


class TestDeviceCodeResponseDefaults:
    """Tests for DeviceCodeResponse defaults."""

    def test_defaults(self) -> None:
        """Test expires_in and interval defaults."""
        resp = DeviceCodeResponse(
            device_code="dc",
            user_code="uc",
            verification_uri="https://v",
            verification_uri_complete="https://v?c=uc",
        )
        assert resp.expires_in == 300
        assert resp.interval == DEVICE_CODE_POLL_INTERVAL

    @pytest.mark.asyncio
    async def test_request_device_code_fills_defaults(self) -> None:
        """Test missing optional fields fall back to defaults."""
        session = _make_session()
        session.request = MagicMock(
            return_value=_make_response(200, {"device_code": "dc", "user_code": "uc"})
        )
        auth = ActronAirNeoAuth(session, base_url="https://a.example")
        result = await auth.request_device_code()
        assert result.verification_uri == "https://a.example/connect"
        assert result.verification_uri_complete == "https://a.example/connect"
        assert result.expires_in == 300
        assert result.interval == DEVICE_CODE_POLL_INTERVAL


class TestRefreshRetryDelays:
    """Tests for the refresh retry backoff."""

    @pytest.mark.asyncio
    async def test_sleep_delays_exponential(self) -> None:
        """Test retry sleeps use exponential backoff and stop before the last try."""
        session = _make_session()
        session.request = MagicMock(return_value=_make_response(400, "fail"))
        auth = ActronAirNeoAuth(session)
        auth.refresh_token_value = "rt"
        with (
            patch(
                "custom_components.actronair_neo.api.auth.asyncio.sleep",
                new_callable=AsyncMock,
            ) as mock_sleep,
            pytest.raises(AuthenticationError),
        ):
            await auth.refresh_access_token()
        assert [c.args[0] for c in mock_sleep.await_args_list] == [
            REFRESH_RETRY_DELAY * (2**i) for i in range(MAX_REFRESH_RETRIES - 1)
        ]
        assert session.request.call_count == MAX_REFRESH_RETRIES


class TestEnsureValidTokenFailure:
    """Tests for ensure_valid_token when refresh fails."""

    @pytest.mark.asyncio
    async def test_refresh_fails_but_token_unexpired(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test proactive refresh failure keeps using an unexpired token."""
        session = _make_session()
        session.request = MagicMock(return_value=_make_response(400, "fail"))
        auth = ActronAirNeoAuth(session)
        auth.set_tokens(
            "at", "rt", (datetime.now(UTC) - timedelta(seconds=1)).timestamp()
        )
        with patch(
            "custom_components.actronair_neo.api.auth.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await auth.ensure_valid_token()
        assert auth.access_token == "at"
        assert "Proactive token refresh failed" in caplog.text

    @pytest.mark.asyncio
    async def test_refresh_fails_and_token_expired(self) -> None:
        """Test refresh failure re-raises when the token is truly expired."""
        session = _make_session()
        session.request = MagicMock(return_value=_make_response(400, "fail"))
        auth = ActronAirNeoAuth(session)
        auth.set_tokens(
            "at", "rt", (datetime.now(UTC) - timedelta(hours=1)).timestamp()
        )
        with (
            patch(
                "custom_components.actronair_neo.api.auth.asyncio.sleep",
                new_callable=AsyncMock,
            ),
            pytest.raises(AuthenticationError),
        ):
            await auth.ensure_valid_token()


class TestStoreTokenResponseEmpty:
    """Tests for _store_token_response with an empty access token."""

    def test_empty_access_token_raises(self) -> None:
        """Test an empty access_token string is rejected."""
        auth = ActronAirNeoAuth(_make_session())
        with pytest.raises(AuthenticationError, match="No access token"):
            auth._store_token_response({"access_token": ""})
        assert auth.access_token is None


@pytest.mark.asyncio
async def test_refresh_zero_retries_returns_without_request() -> None:
    """Test refresh_access_token is a no-op when retries are configured to zero."""
    session = _make_session()
    session.request = MagicMock()
    auth = ActronAirNeoAuth(session)
    auth.refresh_token_value = "rt"
    with patch("custom_components.actronair_neo.api.auth.MAX_REFRESH_RETRIES", 0):
        await auth.refresh_access_token()
    session.request.assert_not_called()
    assert auth.access_token is None
