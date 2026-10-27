"""
Config flow for ActronAir Neo integration.

Uses OAuth2 Device Code Flow (RFC 8628) — the user authorizes via a
browser URL + code instead of entering username/password.

Modelled after the official HA ``actron_air`` integration config flow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .api import ActronAirNeoApiClient, ActronAirNeoAuth
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_ENABLE_PUSH,
    CONF_ENABLE_ZONE_CONTROL,
    CONF_REFRESH_TOKEN,
    CONF_SERIAL_NUMBER,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_ENABLE_PUSH,
    DOMAIN,
)
from .exceptions import AuthenticationError

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Mapping

    import aiohttp

    from .api.auth import DeviceCodeResponse


class ActronairNeoConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for ActronAir Neo (device code auth)."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._auth: ActronAirNeoAuth | None = None
        self._session: aiohttp.ClientSession | None = None
        self._devices: list[Any] = []
        self._device_code_response: DeviceCodeResponse | None = None
        self.login_task: asyncio.Task[None] | None = None

    async def _async_get_session(self) -> aiohttp.ClientSession:
        """
        Return a private aiohttp session backed by the certifi CA bundle.

        Required because HA 2026.4 switched the default trust store to the OS
        CA store which lacks the DigiCert root used by the ActronAir API
        (issue #96).
        """
        from .ssl_helper import async_create_clientsession  # noqa: PLC0415

        if self._session is None or self._session.closed:
            self._session = await async_create_clientsession(self.hass)
        return self._session

    async def _async_close_session(self) -> None:
        """Close the private aiohttp session if one was created."""
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    # ── User step (entry-point) ──────────────────────────────────

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle the initial step — request a device code and poll."""
        if self._auth is None:
            session = await self._async_get_session()
            self._auth = ActronAirNeoAuth(session=session)

            try:
                self._device_code_response = await self._auth.request_device_code()
            except AuthenticationError:
                await self._async_close_session()
                return self.async_abort(reason="cannot_connect")

        async def _wait_for_authorization() -> None:
            """Wait for the user to authorize the device."""
            if self._auth is None:
                msg = "Auth object is not initialized"
                raise RuntimeError(msg)
            if self._device_code_response is None:
                msg = "Device code response is not initialized"
                raise RuntimeError(msg)
            try:
                await self._auth.poll_for_token(
                    self._device_code_response.device_code,
                    self._device_code_response.interval,
                    self._device_code_response.expires_in,
                )
            except AuthenticationError as ex:
                raise CannotConnectError from ex

        if self.login_task is None:
            self.login_task = self.hass.async_create_task(_wait_for_authorization())

        if self.login_task.done():
            if exception := self.login_task.exception():
                if isinstance(exception, CannotConnectError):
                    return self.async_show_progress_done(
                        next_step_id="connection_error"
                    )
                return self.async_show_progress_done(next_step_id="timeout")
            return self.async_show_progress_done(next_step_id="finish_auth")

        if self._device_code_response is None:
            msg = "Device code response is not initialized"
            raise RuntimeError(msg)
        return self.async_show_progress(
            step_id="user",
            progress_action="wait_for_authorization",
            description_placeholders={
                "user_code": self._device_code_response.user_code,
                "verification_uri": (
                    self._device_code_response.verification_uri_complete
                ),
                "expires_minutes": str(
                    max(1, self._device_code_response.expires_in // 60)
                ),
            },
            progress_task=self.login_task,
        )

    # ── Finish auth — fetch devices ──────────────────────────────

    async def async_step_finish_auth(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Fetch devices after successful authorization."""
        if self._auth is None:
            msg = "Auth object is not initialized"
            raise RuntimeError(msg)

        # For reauth, just update tokens and reload
        if self.source == SOURCE_REAUTH:
            reauth_entry = self._get_reauth_entry()
            await self._async_close_session()
            return self.async_update_reload_and_abort(
                reauth_entry,
                data_updates={
                    CONF_ACCESS_TOKEN: self._auth.access_token,
                    CONF_REFRESH_TOKEN: self._auth.refresh_token_value,
                    CONF_TOKEN_EXPIRES_AT: (
                        self._auth.token_expires_at.timestamp()
                        if self._auth.token_expires_at
                        else 0.0
                    ),
                },
            )

        # For reconfigure, re-authorize but keep the same device/entry.
        if self.source == SOURCE_RECONFIGURE:
            return await self._async_reconfigure_entry()

        session = await self._async_get_session()
        api = ActronAirNeoApiClient(auth=self._auth, session=session)

        try:
            devices = await api.get_devices()
        except Exception:  # noqa: BLE001
            await self._async_close_session()
            return self.async_abort(reason="cannot_connect")

        if not devices:
            await self._async_close_session()
            return self.async_abort(reason="no_devices")

        self._devices = devices

        if len(devices) == 1:
            return await self._async_create_device_entry(devices[0])

        return await self.async_step_select_device()

    # ── Error recovery steps ─────────────────────────────────────

    async def async_step_timeout(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle authentication timeout."""
        if user_input is None:
            return self.async_show_form(step_id="timeout")
        # Reset task and retry
        self.login_task = None
        return await self.async_step_user()

    async def async_step_connection_error(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle connection error during authorization."""
        if user_input is None:
            return self.async_show_form(step_id="connection_error")
        # Reset all state and retry
        self._auth = None
        self._device_code_response = None
        self.login_task = None
        return await self.async_step_user()

    # ── Device selection ─────────────────────────────────────────

    async def async_step_select_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the device selection step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected_serial = user_input["device"]
            selected_device = next(
                (d for d in self._devices if d.serial == selected_serial),
                None,
            )

            if selected_device:
                return await self._async_create_device_entry(selected_device)
            errors["base"] = "device_not_found"

        device_schema = probatio.Schema(
            {
                probatio.Required("device"): probatio.In(
                    {
                        device.serial: f"{device.name} ({device.serial})"
                        for device in self._devices
                    }
                )
            }
        )

        return self.async_show_form(
            step_id="select_device", data_schema=device_schema, errors=errors
        )

    async def _async_create_device_entry(self, device: Any) -> ConfigFlowResult:
        """Create a config entry for a discovered device."""
        if self._auth is None:
            msg = "Auth object is not initialized"
            raise RuntimeError(msg)

        await self.async_set_unique_id(device.serial)
        self._abort_if_unique_id_configured()

        # Close the private auth session — the integration setup will create
        # its own certifi-backed session on entry load.
        await self._async_close_session()

        return self.async_create_entry(
            title=f"ActronAir Neo ({device.name})",
            data={
                CONF_ACCESS_TOKEN: self._auth.access_token,
                CONF_REFRESH_TOKEN: self._auth.refresh_token_value,
                CONF_TOKEN_EXPIRES_AT: (
                    self._auth.token_expires_at.timestamp()
                    if self._auth.token_expires_at
                    else 0.0
                ),
                CONF_SERIAL_NUMBER: device.serial,
                CONF_BASE_URL: device.base_url,
                "system_id": device.id,
            },
            options={
                CONF_ENABLE_ZONE_CONTROL: False,
            },
        )

    # ── Reconfigure flow ────────────────────────────────────────

    async def async_step_reconfigure(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Re-authorize an existing entry without deleting it."""
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(step_id="reconfigure")

    async def _async_reconfigure_entry(self) -> ConfigFlowResult:
        """
        Finish a reconfigure: re-authorize and keep the same device.

        After the user re-authorizes, confirm the chosen account still owns the
        entry's device (matching unique ID), then refresh the stored tokens and
        connection metadata in place rather than creating a new entry.
        """
        if self._auth is None:
            msg = "Auth object is not initialized"
            raise RuntimeError(msg)

        reconfigure_entry = self._get_reconfigure_entry()
        session = await self._async_get_session()
        api = ActronAirNeoApiClient(auth=self._auth, session=session)

        try:
            devices = await api.get_devices()
        except Exception:  # noqa: BLE001
            return self.async_abort(reason="cannot_connect")
        finally:
            await self._async_close_session()

        existing_serial = reconfigure_entry.unique_id
        device = next((d for d in devices if d.serial == existing_serial), None)
        if device is None:
            return self.async_abort(reason="wrong_account")

        await self.async_set_unique_id(existing_serial)
        self._abort_if_unique_id_mismatch(reason="wrong_account")

        return self.async_update_reload_and_abort(
            reconfigure_entry,
            data_updates={
                CONF_ACCESS_TOKEN: self._auth.access_token,
                CONF_REFRESH_TOKEN: self._auth.refresh_token_value,
                CONF_TOKEN_EXPIRES_AT: (
                    self._auth.token_expires_at.timestamp()
                    if self._auth.token_expires_at
                    else 0.0
                ),
                CONF_BASE_URL: device.base_url,
                "system_id": device.id,
            },
        )

    # ── Reauth flow ─────────────────────────────────────────────

    async def async_step_reauth(
        self,
        entry_data: Mapping[str, Any],  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle reauthentication request."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Confirm reauth dialog."""
        if user_input is not None:
            return await self.async_step_user()

        return self.async_show_form(step_id="reauth_confirm")

    # ── Options flow ────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,  # noqa: ARG004
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=probatio.Schema(
                {
                    probatio.Optional(
                        CONF_ENABLE_ZONE_CONTROL,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_ZONE_CONTROL, False
                        ),
                    ): bool,
                    probatio.Optional(
                        CONF_ENABLE_PUSH,
                        default=self.config_entry.options.get(
                            CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH
                        ),
                    ): bool,
                }
            ),
        )


class CannotConnectError(HomeAssistantError):
    """Error to indicate we cannot connect."""
