"""Tests for the ActronAir Neo config flow (device code auth)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant.common import MockConfigEntry

from custom_components.actronair_neo.api.auth import DeviceCodeResponse
from custom_components.actronair_neo.api.models import DeviceInfo
from custom_components.actronair_neo.config_flow import ActronairNeoConfigFlow
from custom_components.actronair_neo.const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_ENABLE_PUSH,
    CONF_ENABLE_ZONE_CONTROL,
    CONF_REFRESH_TOKEN,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)
from custom_components.actronair_neo.exceptions import AuthenticationError

from .conftest import MOCK_SERIAL

MOCK_DEVICE_1 = DeviceInfo(
    serial=MOCK_SERIAL, name="Living Room AC", type="Neo", id="12345"
)
MOCK_DEVICE_2 = DeviceInfo(serial="DEF456", name="Bedroom AC", type="Neo", id="67890")

MOCK_DEVICE_CODE_RESPONSE = DeviceCodeResponse(
    device_code="test-device-code",
    user_code="ABCD-1234",
    verification_uri="https://nimbus.actronair.com.au/connect",
    verification_uri_complete="https://nimbus.actronair.com.au/connect?user_code=ABCD-1234",
    expires_in=300,
    interval=1,
)

MOCK_TOKEN_RESPONSE = {
    "access_token": "mock_access_token",
    "refresh_token": "mock_refresh_token",
    "expires_in": 3600,
    "token_type": "bearer",
}

_PATCH_AUTH = "custom_components.actronair_neo.config_flow.ActronAirNeoAuth"
_PATCH_API = "custom_components.actronair_neo.config_flow.ActronAirNeoApiClient"
# Auto-creating a single-device entry triggers a real ``async_setup_entry``,
# which builds its own API client and calls ``get_devices()`` over the network.
# Flow tests only assert on the flow result, so stub setup to avoid the socket.
_PATCH_SETUP = "custom_components.actronair_neo.async_setup_entry"
_PATCH_SESSION = "custom_components.actronair_neo.ssl_helper.async_create_clientsession"


def _mock_auth_instance() -> MagicMock:
    """Create a mock auth instance with device code flow methods."""
    auth = MagicMock()
    auth.request_device_code = AsyncMock(return_value=MOCK_DEVICE_CODE_RESPONSE)
    auth.poll_for_token = AsyncMock(return_value=MOCK_TOKEN_RESPONSE)
    auth.access_token = "mock_access_token"
    auth.refresh_token_value = "mock_refresh_token"
    auth.token_expires_at = MagicMock()
    auth.token_expires_at.timestamp.return_value = 9999999999.0
    return auth


async def _advance_flow(hass: HomeAssistant, flow_id: str) -> dict:
    """Advance a flow past any SHOW_PROGRESS / SHOW_PROGRESS_DONE states."""
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow_id)
    while result["type"] in (
        FlowResultType.SHOW_PROGRESS_DONE,
        FlowResultType.SHOW_PROGRESS,
    ):
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def _finish_progress(hass: HomeAssistant, result: dict) -> dict:
    """Advance a flow only if it is still showing progress."""
    if result["type"] in (
        FlowResultType.SHOW_PROGRESS,
        FlowResultType.SHOW_PROGRESS_DONE,
    ):
        return await _advance_flow(hass, result["flow_id"])
    await hass.async_block_till_done()
    return result


async def _run_successful_user_flow(
    hass: HomeAssistant, mock_auth: MagicMock | None = None
) -> dict:
    """Run a complete single-device user flow and return the final result."""
    mock_auth = mock_auth or _mock_auth_instance()
    mock_api = MagicMock()
    mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1])
    with (
        patch(_PATCH_AUTH, return_value=mock_auth),
        patch(_PATCH_API, return_value=mock_api),
        patch(_PATCH_SETUP, return_value=None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await _advance_flow(hass, result["flow_id"])
        await hass.async_block_till_done()
    return result


class TestActronConfigFlow:
    """Test the ActronAir Neo config flow (device code auth)."""

    @pytest.mark.asyncio
    async def test_user_step_starts_device_code_flow(self, hass: HomeAssistant) -> None:
        """Test user step requests device code and shows progress."""
        mock_auth = _mock_auth_instance()
        # Make poll_for_token block (never completes during test)
        poll_event = asyncio.Event()

        async def _blocking_poll(*args, **kwargs):
            await poll_event.wait()

        mock_auth.poll_for_token = _blocking_poll

        with patch(_PATCH_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

        assert result["type"] == FlowResultType.SHOW_PROGRESS
        assert result["step_id"] == "user"
        assert result["description_placeholders"]["user_code"] == "ABCD-1234"
        assert (
            result["description_placeholders"]["verification_uri"]
            == "https://nimbus.actronair.com.au/connect?user_code=ABCD-1234"
        )

    @pytest.mark.asyncio
    async def test_single_device_creates_entry(self, hass: HomeAssistant) -> None:
        """Test auto-creation when only one device is found."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            # Task may complete immediately with mock — advance to final state
            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL
        assert result["data"][CONF_TOKEN_EXPIRES_AT] == 9999999999.0
        assert result["title"] == f"ActronAir Neo ({MOCK_DEVICE_1.name})"
        assert result["data"]["serial_number"] == MOCK_SERIAL
        assert result["data"]["system_id"] == "12345"
        assert result["data"][CONF_ACCESS_TOKEN] == "mock_access_token"
        assert result["data"][CONF_REFRESH_TOKEN] == "mock_refresh_token"
        assert result["options"][CONF_ENABLE_ZONE_CONTROL] is False

    @pytest.mark.asyncio
    async def test_multiple_devices_select_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        """Multiple devices show a selection form; picking one creates it."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1, MOCK_DEVICE_2])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await _advance_flow(hass, result["flow_id"])

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "select_device"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"device": MOCK_DEVICE_2.serial}
            )
            await hass.async_block_till_done()

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_DEVICE_2.serial
        assert result["title"] == f"ActronAir Neo ({MOCK_DEVICE_2.name})"
        assert result["data"]["system_id"] == MOCK_DEVICE_2.id

    @pytest.mark.asyncio
    async def test_device_code_request_fails(self, hass: HomeAssistant) -> None:
        """Test abort when device code request fails."""
        mock_auth = MagicMock()
        mock_auth.request_device_code = AsyncMock(
            side_effect=AuthenticationError("Connection failed")
        )

        with patch(_PATCH_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"

        # An aborted flow cannot resume; a fresh flow succeeds.
        result = await _run_successful_user_flow(hass)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL

    @pytest.mark.asyncio
    async def test_connection_error_then_retry_creates_entry(
        self, hass: HomeAssistant
    ) -> None:
        """AuthenticationError while polling shows connection_error; retry works."""
        mock_auth = _mock_auth_instance()
        mock_auth.poll_for_token = AsyncMock(
            side_effect=[
                AuthenticationError("Device code authorization failed"),
                MOCK_TOKEN_RESPONSE,
            ]
        )
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth) as auth_cls,
            patch(_PATCH_API, return_value=mock_api),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await _advance_flow(hass, result["flow_id"])

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "connection_error"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {}
            )
            result = await _finish_progress(hass, result)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL
        # connection_error resets auth state, so a new device code is requested.
        assert auth_cls.call_count == 2
        assert mock_auth.request_device_code.await_count == 2

    @pytest.mark.asyncio
    async def test_timeout_then_retry_creates_entry(self, hass: HomeAssistant) -> None:
        """A non-auth polling failure shows timeout; retry reuses the device code."""
        mock_auth = _mock_auth_instance()
        mock_auth.poll_for_token = AsyncMock(
            side_effect=[TimeoutError("expired"), MOCK_TOKEN_RESPONSE]
        )
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await _advance_flow(hass, result["flow_id"])

            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "timeout"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {}
            )
            result = await _finish_progress(hass, result)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL
        assert mock_auth.request_device_code.await_count == 1
        assert mock_auth.poll_for_token.await_count == 2

    @pytest.mark.asyncio
    async def test_select_device_invalid_data_then_recovers(
        self, hass: HomeAssistant
    ) -> None:
        """An unknown serial is rejected by the schema; a valid one succeeds."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1, MOCK_DEVICE_2])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            select_form = await _advance_flow(hass, result["flow_id"])
            with pytest.raises(InvalidData):
                await hass.config_entries.flow.async_configure(
                    select_form["flow_id"],
                    {"device": "UNKNOWN"},
                )
            result = await hass.config_entries.flow.async_configure(
                select_form["flow_id"], {"device": MOCK_SERIAL}
            )
            await hass.async_block_till_done()

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL

    @pytest.mark.asyncio
    async def test_already_configured_aborts(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """A device that already has an entry aborts the user flow."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    @pytest.mark.asyncio
    async def test_entry_without_token_expiry(self, hass: HomeAssistant) -> None:
        """A missing token expiry is stored as 0.0."""
        mock_auth = _mock_auth_instance()
        mock_auth.token_expires_at = None

        result = await _run_successful_user_flow(hass, mock_auth=mock_auth)

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL
        assert result["data"][CONF_TOKEN_EXPIRES_AT] == 0.0

    @pytest.mark.asyncio
    async def test_finish_auth_get_devices_fails_aborts(
        self, hass: HomeAssistant
    ) -> None:
        """get_devices failure aborts with cannot_connect; a new flow succeeds."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(side_effect=Exception("boom"))

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "cannot_connect"

        result = await _run_successful_user_flow(hass)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL

    @pytest.mark.asyncio
    async def test_finish_auth_no_devices_aborts(self, hass: HomeAssistant) -> None:
        """Test finish auth aborts when no devices are returned."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "no_devices"

        result = await _run_successful_user_flow(hass)
        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["result"].unique_id == MOCK_SERIAL


class TestReauthFlow:
    """Reauth flow journeys through the flow manager."""

    @staticmethod
    def _new_auth(expires_at: float | None) -> MagicMock:
        auth = _mock_auth_instance()
        auth.access_token = "new_access_token"
        auth.refresh_token_value = "new_refresh_token"
        if expires_at is None:
            auth.token_expires_at = None
        else:
            auth.token_expires_at.timestamp.return_value = expires_at
        return auth

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("expires_at", "expected_expiry"),
        [(1234567890.0, 1234567890.0), (None, 0.0)],
        ids=["with_expiry", "without_expiry"],
    )
    async def test_reauth_updates_tokens(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        expires_at: float | None,
        expected_expiry: float,
    ) -> None:
        """Reauth stores the new tokens and keeps the entry's unique ID."""
        mock_auth = self._new_auth(expires_at)

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await mock_config_entry.start_reauth_flow(hass)
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "reauth_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {}
            )
            result = await _finish_progress(hass, result)
            await hass.async_block_till_done()

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert mock_config_entry.unique_id == MOCK_SERIAL
        assert mock_config_entry.data[CONF_ACCESS_TOKEN] == "new_access_token"
        assert mock_config_entry.data[CONF_REFRESH_TOKEN] == "new_refresh_token"
        assert mock_config_entry.data[CONF_TOKEN_EXPIRES_AT] == expected_expiry


MOCK_DEVICE_1_RECONF = DeviceInfo(
    serial=MOCK_SERIAL,
    name="Living Room AC",
    type="Neo",
    id="99999",
    base_url="https://que.actronair.com.au",
)


class TestReconfigureFlow:
    """Reconfigure flow journeys through the flow manager."""

    async def _run(
        self,
        hass: HomeAssistant,
        entry: MockConfigEntry,
        get_devices: AsyncMock,
    ) -> dict:
        mock_auth = _mock_auth_instance()
        mock_auth.access_token = "reconf_access_token"
        mock_auth.refresh_token_value = "reconf_refresh_token"
        mock_api = MagicMock()
        mock_api.get_devices = get_devices
        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
            patch(_PATCH_SETUP, return_value=None),
        ):
            result = await entry.start_reconfigure_flow(hass)
            assert result["type"] == FlowResultType.FORM
            assert result["step_id"] == "reconfigure"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {}
            )
            result = await _finish_progress(hass, result)
            await hass.async_block_till_done()
        return result

    def _assert_reconfigured(self, entry: MockConfigEntry) -> None:
        assert entry.unique_id == MOCK_SERIAL
        assert entry.data[CONF_ACCESS_TOKEN] == "reconf_access_token"
        assert entry.data[CONF_REFRESH_TOKEN] == "reconf_refresh_token"
        assert entry.data[CONF_TOKEN_EXPIRES_AT] == 9999999999.0
        assert entry.data[CONF_BASE_URL] == "https://que.actronair.com.au"
        assert entry.data["system_id"] == "99999"

    @pytest.mark.asyncio
    async def test_reconfigure_success(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Reconfigure refreshes tokens and device metadata in place."""
        result = await self._run(
            hass,
            mock_config_entry,
            AsyncMock(return_value=[MOCK_DEVICE_2, MOCK_DEVICE_1_RECONF]),
        )

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        self._assert_reconfigured(mock_config_entry)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("get_devices", "reason"),
        [
            (AsyncMock(return_value=[MOCK_DEVICE_2]), "wrong_account"),
            (AsyncMock(side_effect=Exception("boom")), "cannot_connect"),
        ],
        ids=["wrong_account", "cannot_connect"],
    )
    async def test_reconfigure_abort_then_success(
        self,
        hass: HomeAssistant,
        mock_config_entry: MockConfigEntry,
        get_devices: AsyncMock,
        reason: str,
    ) -> None:
        """Reconfigure aborts leave the entry untouched; a new attempt succeeds."""
        original = dict(mock_config_entry.data)

        result = await self._run(hass, mock_config_entry, get_devices)

        assert result["type"] == FlowResultType.ABORT
        assert result["reason"] == reason
        assert dict(mock_config_entry.data) == original

        result = await self._run(
            hass, mock_config_entry, AsyncMock(return_value=[MOCK_DEVICE_1_RECONF])
        )
        assert result["reason"] == "reconfigure_successful"
        self._assert_reconfigured(mock_config_entry)


class TestOptionsFlow:
    """Test the options flow handler."""

    @staticmethod
    def _defaults(result: dict) -> dict:
        return {str(key): key.default() for key in result["data_schema"].schema}

    @pytest.mark.asyncio
    async def test_options_flow(
        self, hass: HomeAssistant, mock_config_entry: MockConfigEntry
    ) -> None:
        """Non-default options are saved on the entry."""
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"
        # Entry has no push option yet, so the form falls back to the default.
        assert self._defaults(result) == {
            CONF_ENABLE_ZONE_CONTROL: False,
            CONF_ENABLE_PUSH: True,
        }

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_ENABLE_ZONE_CONTROL: True, CONF_ENABLE_PUSH: False},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"] == {
            CONF_ENABLE_ZONE_CONTROL: True,
            CONF_ENABLE_PUSH: False,
        }
        assert mock_config_entry.options[CONF_ENABLE_ZONE_CONTROL] is True
        assert mock_config_entry.options[CONF_ENABLE_PUSH] is False

    @pytest.mark.asyncio
    async def test_options_form_defaults_reflect_entry(
        self, hass: HomeAssistant
    ) -> None:
        """Form defaults come from the entry's existing options."""
        entry = MockConfigEntry(
            domain=DOMAIN,
            data={},
            options={CONF_ENABLE_ZONE_CONTROL: True, CONF_ENABLE_PUSH: False},
            unique_id=MOCK_SERIAL,
            version=2,
        )
        entry.add_to_hass(hass)

        result = await hass.config_entries.options.async_init(entry.entry_id)

        assert result["type"] == FlowResultType.FORM
        assert self._defaults(result) == {
            CONF_ENABLE_ZONE_CONTROL: True,
            CONF_ENABLE_PUSH: False,
        }


class TestSessionHelpers:
    """Lifecycle of the flow's private aiohttp session."""

    @staticmethod
    def _session(*, closed: bool) -> MagicMock:
        session = MagicMock()
        session.closed = closed
        session.close = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_get_session_creates_when_absent(self, hass: HomeAssistant) -> None:
        flow = ActronairNeoConfigFlow()
        flow.hass = hass
        new_session = self._session(closed=False)
        with patch(_PATCH_SESSION, AsyncMock(return_value=new_session)) as create:
            assert await flow._async_get_session() is new_session
        create.assert_awaited_once_with(hass)

    @pytest.mark.asyncio
    async def test_get_session_reuses_open_session(self, hass: HomeAssistant) -> None:
        flow = ActronairNeoConfigFlow()
        flow.hass = hass
        existing = self._session(closed=False)
        flow._session = existing
        with patch(_PATCH_SESSION, AsyncMock()) as create:
            assert await flow._async_get_session() is existing
        create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_session_recreates_closed_session(
        self, hass: HomeAssistant
    ) -> None:
        flow = ActronairNeoConfigFlow()
        flow.hass = hass
        flow._session = self._session(closed=True)
        new_session = self._session(closed=False)
        with patch(_PATCH_SESSION, AsyncMock(return_value=new_session)) as create:
            assert await flow._async_get_session() is new_session
        create.assert_awaited_once_with(hass)

    @pytest.mark.asyncio
    async def test_close_session_closes_open_session(self) -> None:
        flow = ActronairNeoConfigFlow()
        session = self._session(closed=False)
        flow._session = session
        await flow._async_close_session()
        session.close.assert_awaited_once()
        assert flow._session is None

    @pytest.mark.asyncio
    async def test_close_session_skips_closed_session(self) -> None:
        flow = ActronairNeoConfigFlow()
        session = self._session(closed=True)
        flow._session = session
        await flow._async_close_session()
        session.close.assert_not_awaited()
        assert flow._session is None

    @pytest.mark.asyncio
    async def test_close_session_absent_is_noop(self) -> None:
        flow = ActronairNeoConfigFlow()
        await flow._async_close_session()
        assert flow._session is None

    @pytest.mark.asyncio
    async def test_real_session_lifecycle(self, hass: HomeAssistant) -> None:
        """The real certifi-backed session opens without network and closes."""
        flow = ActronairNeoConfigFlow()
        flow.hass = hass
        session = await flow._async_get_session()
        assert not session.closed
        assert await flow._async_get_session() is session
        await flow._async_close_session()
        assert session.closed
        assert flow._session is None


class TestUninitializedGuards:
    """Defensive RuntimeError guards for uninitialized flow state."""

    @staticmethod
    def _flow_capturing_task() -> tuple[ActronairNeoConfigFlow, list]:
        """Flow whose hass captures the authorization coroutine un-scheduled."""
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        captured: list = []

        def _capture(coro):
            captured.append(coro)
            task = MagicMock()
            task.done.return_value = False
            return task

        flow.hass.async_create_task = MagicMock(side_effect=_capture)
        flow.async_show_progress = MagicMock(return_value={"type": "progress"})
        flow._auth = _mock_auth_instance()
        flow._device_code_response = MOCK_DEVICE_CODE_RESPONSE
        return flow, captured

    @pytest.mark.asyncio
    async def test_wait_for_authorization_without_auth(self) -> None:
        flow, captured = self._flow_capturing_task()
        await flow.async_step_user()
        flow._auth = None
        with pytest.raises(RuntimeError, match="Auth object is not initialized"):
            await captured[0]

    @pytest.mark.asyncio
    async def test_wait_for_authorization_without_device_code(self) -> None:
        flow, captured = self._flow_capturing_task()
        await flow.async_step_user()
        flow._device_code_response = None
        with pytest.raises(
            RuntimeError, match="Device code response is not initialized"
        ):
            await captured[0]

    @pytest.mark.asyncio
    async def test_user_step_progress_without_device_code(self) -> None:
        flow = ActronairNeoConfigFlow()
        flow._auth = _mock_auth_instance()
        flow._device_code_response = None
        flow.login_task = MagicMock()
        flow.login_task.done.return_value = False
        with pytest.raises(
            RuntimeError, match="Device code response is not initialized"
        ):
            await flow.async_step_user()

    @pytest.mark.asyncio
    async def test_finish_auth_without_auth(self) -> None:
        flow = ActronairNeoConfigFlow()
        with pytest.raises(RuntimeError, match="Auth object is not initialized"):
            await flow.async_step_finish_auth()

    @pytest.mark.asyncio
    async def test_create_device_entry_without_auth(self) -> None:
        flow = ActronairNeoConfigFlow()
        with pytest.raises(RuntimeError, match="Auth object is not initialized"):
            await flow._async_create_device_entry(MOCK_DEVICE_1)

    @pytest.mark.asyncio
    async def test_reconfigure_entry_without_auth(self) -> None:
        flow = ActronairNeoConfigFlow()
        with pytest.raises(RuntimeError, match="Auth object is not initialized"):
            await flow._async_reconfigure_entry()


class TestConfigFlowDirectMethods:
    """Direct method tests for branches hard to hit via flow manager."""

    @pytest.mark.asyncio
    async def test_timeout_step_paths(self):
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow.async_show_form = MagicMock(return_value={"step_id": "timeout"})
        result = await flow.async_step_timeout()
        assert result["step_id"] == "timeout"

        flow.async_step_user = AsyncMock(return_value={"type": "progress"})
        flow.login_task = object()
        result = await flow.async_step_timeout(user_input={})
        assert result["type"] == "progress"
        assert flow.login_task is None

    @pytest.mark.asyncio
    async def test_connection_error_step_paths(self):
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow.async_show_form = MagicMock(return_value={"step_id": "connection_error"})
        result = await flow.async_step_connection_error()
        assert result["step_id"] == "connection_error"

        flow._auth = object()
        flow._device_code_response = object()
        flow.login_task = object()
        flow.async_step_user = AsyncMock(return_value={"type": "progress"})
        result = await flow.async_step_connection_error(user_input={})
        assert result["type"] == "progress"
        assert flow._auth is None
        assert flow._device_code_response is None
        assert flow.login_task is None

    @pytest.mark.asyncio
    async def test_select_device_not_found_error_branch(self):
        flow = ActronairNeoConfigFlow()
        flow._devices = [MOCK_DEVICE_1]
        flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
        result = await flow.async_step_select_device({"device": "MISSING"})
        assert result["errors"]["base"] == "device_not_found"

    @pytest.mark.asyncio
    async def test_finish_auth_reauth_token_expiry_none(self):
        flow = ActronairNeoConfigFlow()
        flow.context = {"source": config_entries.SOURCE_REAUTH}
        flow._auth = MagicMock()
        flow._auth.access_token = "token"
        flow._auth.refresh_token_value = "refresh"
        flow._auth.token_expires_at = None
        flow._get_reauth_entry = MagicMock(return_value=MagicMock())
        flow.async_update_reload_and_abort = MagicMock(return_value={"type": "abort"})

        result = await flow.async_step_finish_auth()
        assert result["type"] == "abort"
        call_kwargs = flow.async_update_reload_and_abort.call_args.kwargs
        assert call_kwargs["data_updates"]["token_expires_at"] == 0.0

    def test_async_get_options_flow_static(self):
        entry = MagicMock()
        flow = ActronairNeoConfigFlow.async_get_options_flow(entry)
        assert flow is not None

    @pytest.mark.asyncio
    async def test_user_step_done_task_timeout_path(self):
        """Test async_step_user handles completed task with non-connect exception."""
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow._auth = MagicMock()
        flow._device_code_response = MOCK_DEVICE_CODE_RESPONSE
        future = asyncio.get_running_loop().create_future()
        future.set_exception(RuntimeError("timeout"))
        flow.login_task = future
        flow.async_show_progress_done = MagicMock(return_value={"step_id": "timeout"})

        result = await flow.async_step_user()
        assert result["step_id"] == "timeout"

    @pytest.mark.asyncio
    async def test_finish_auth_exception_abort(self):
        """Test finish auth aborts when get_devices raises unexpected exception."""
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow._auth = _mock_auth_instance()
        flow._session = MagicMock()
        flow._session.closed = False
        flow._session.close = AsyncMock()
        flow.context = {"source": config_entries.SOURCE_USER}
        flow.async_abort = MagicMock(return_value={"reason": "cannot_connect"})

        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(side_effect=Exception("boom"))
        with patch(_PATCH_API, return_value=mock_api):
            result = await flow.async_step_finish_auth()
        assert result["reason"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_select_device_success_path(self):
        """Test select device calls create entry for matching serial."""
        flow = ActronairNeoConfigFlow()
        flow._devices = [MOCK_DEVICE_1]
        flow._async_create_device_entry = AsyncMock(
            return_value={"type": "create_entry"}
        )

        result = await flow.async_step_select_device({"device": MOCK_SERIAL})
        assert result["type"] == "create_entry"

    @pytest.mark.asyncio
    async def test_reauth_confirm_with_user_input(self):
        """Test reauth confirm routes to user step when confirmed."""
        flow = ActronairNeoConfigFlow()
        flow.async_step_user = AsyncMock(return_value={"type": "progress"})
        result = await flow.async_step_reauth_confirm(user_input={})
        assert result["type"] == "progress"

    @pytest.mark.asyncio
    async def test_reconfigure_shows_form(self):
        """Reconfigure with no input shows the confirm form."""
        flow = ActronairNeoConfigFlow()
        flow.async_show_form = MagicMock(side_effect=lambda **kwargs: kwargs)
        result = await flow.async_step_reconfigure()
        assert result["step_id"] == "reconfigure"

    @pytest.mark.asyncio
    async def test_reconfigure_routes_to_user(self):
        """Reconfigure confirm routes to the device-code auth step."""
        flow = ActronairNeoConfigFlow()
        flow.async_step_user = AsyncMock(return_value={"type": "progress"})
        result = await flow.async_step_reconfigure(user_input={})
        assert result["type"] == "progress"

    @pytest.mark.asyncio
    async def test_finish_auth_reconfigure_dispatches(self):
        """finish_auth routes to the reconfigure handler for that source."""
        flow = ActronairNeoConfigFlow()
        flow.context = {"source": config_entries.SOURCE_RECONFIGURE}
        flow._auth = _mock_auth_instance()
        flow._async_reconfigure_entry = AsyncMock(return_value={"type": "abort"})
        result = await flow.async_step_finish_auth()
        assert result["type"] == "abort"
        flow._async_reconfigure_entry.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconfigure_entry_success(self):
        """Reconfigure updates tokens + metadata in place for the same device."""
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow._auth = _mock_auth_instance()
        flow._session = MagicMock()
        flow._session.closed = False
        flow._session.close = AsyncMock()

        entry = MagicMock()
        entry.unique_id = MOCK_SERIAL
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_mismatch = MagicMock()
        flow.async_update_reload_and_abort = MagicMock(
            return_value={"type": "abort", "reason": "reconfigure_successful"}
        )

        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1])
        with patch(_PATCH_API, return_value=mock_api):
            result = await flow._async_reconfigure_entry()

        assert result["reason"] == "reconfigure_successful"
        flow.async_set_unique_id.assert_awaited_once_with(MOCK_SERIAL)
        flow._abort_if_unique_id_mismatch.assert_called_once_with(
            reason="wrong_account"
        )
        data_updates = flow.async_update_reload_and_abort.call_args.kwargs[
            "data_updates"
        ]
        assert data_updates[CONF_ACCESS_TOKEN] == "mock_access_token"
        assert data_updates[CONF_REFRESH_TOKEN] == "mock_refresh_token"

    @pytest.mark.asyncio
    async def test_reconfigure_entry_wrong_account(self):
        """Reconfigure aborts when the re-authorized account lacks the device."""
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow._auth = _mock_auth_instance()
        flow._session = MagicMock()
        flow._session.closed = False
        flow._session.close = AsyncMock()

        entry = MagicMock()
        entry.unique_id = MOCK_SERIAL
        flow._get_reconfigure_entry = MagicMock(return_value=entry)
        flow.async_abort = MagicMock(return_value={"reason": "wrong_account"})

        mock_api = MagicMock()
        # Account returns a different system than the one being reconfigured.
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_2])
        with patch(_PATCH_API, return_value=mock_api):
            result = await flow._async_reconfigure_entry()

        assert result["reason"] == "wrong_account"

    @pytest.mark.asyncio
    async def test_reconfigure_entry_cannot_connect(self):
        """Reconfigure aborts when device fetch fails."""
        flow = ActronairNeoConfigFlow()
        flow.hass = MagicMock()
        flow._auth = _mock_auth_instance()
        flow._session = MagicMock()
        flow._session.closed = False
        flow._session.close = AsyncMock()
        flow._get_reconfigure_entry = MagicMock(return_value=MagicMock())
        flow.async_abort = MagicMock(return_value={"reason": "cannot_connect"})

        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(side_effect=Exception("boom"))
        with patch(_PATCH_API, return_value=mock_api):
            result = await flow._async_reconfigure_entry()

        assert result["reason"] == "cannot_connect"
