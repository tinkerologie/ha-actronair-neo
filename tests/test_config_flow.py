"""Tests for the ActronAir Neo config flow (device code auth)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData

from custom_components.actronair_neo.api.auth import DeviceCodeResponse
from custom_components.actronair_neo.api.models import DeviceInfo
from custom_components.actronair_neo.config_flow import ActronairNeoConfigFlow
from custom_components.actronair_neo.const import (
    CONF_ACCESS_TOKEN,
    CONF_ENABLE_ZONE_CONTROL,
    CONF_REFRESH_TOKEN,
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
            patch(_PATCH_SETUP, return_value=True),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            # Task may complete immediately with mock — advance to final state
            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["title"] == f"ActronAir Neo ({MOCK_DEVICE_1.name})"
        assert result["data"]["serial_number"] == MOCK_SERIAL
        assert result["data"]["system_id"] == "12345"
        assert result["data"][CONF_ACCESS_TOKEN] == "mock_access_token"
        assert result["data"][CONF_REFRESH_TOKEN] == "mock_refresh_token"
        assert result["options"][CONF_ENABLE_ZONE_CONTROL] is False

    @pytest.mark.asyncio
    async def test_multiple_devices_shows_selection(self, hass: HomeAssistant) -> None:
        """Test device selection step when multiple devices found."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1, MOCK_DEVICE_2])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
        ):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "select_device"

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

    @pytest.mark.asyncio
    async def test_authorization_timeout_shows_error_step(
        self, hass: HomeAssistant
    ) -> None:
        """Test that auth failure transitions to connection_error step."""
        mock_auth = _mock_auth_instance()
        mock_auth.poll_for_token = AsyncMock(
            side_effect=AuthenticationError("Device code authorization timed out")
        )

        with patch(_PATCH_AUTH, return_value=mock_auth):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )

            result = await _advance_flow(hass, result["flow_id"])

        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "connection_error"

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_select_device_invalid_data_raises(self, hass: HomeAssistant) -> None:
        """Test select device schema rejects unknown serial values."""
        mock_auth = _mock_auth_instance()
        mock_api = MagicMock()
        mock_api.get_devices = AsyncMock(return_value=[MOCK_DEVICE_1, MOCK_DEVICE_2])

        with (
            patch(_PATCH_AUTH, return_value=mock_auth),
            patch(_PATCH_API, return_value=mock_api),
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


class TestOptionsFlow:
    """Test the options flow handler."""

    @pytest.mark.asyncio
    async def test_options_flow(self, hass: HomeAssistant, mock_config_entry) -> None:
        """Test options flow shows form and saves changes."""
        result = await hass.config_entries.options.async_init(
            mock_config_entry.entry_id
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "init"

        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {CONF_ENABLE_ZONE_CONTROL: False},
        )

        assert result["type"] == FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_ENABLE_ZONE_CONTROL] is False


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
