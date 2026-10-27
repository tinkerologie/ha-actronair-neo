"""Tests for the ActronAir Neo __init__ module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
    ServiceValidationError,
)

import custom_components.actronair_neo as integration
from custom_components.actronair_neo.const import (
    CONF_ENABLE_PUSH,
    CONF_ENABLE_ZONE_CONTROL,
    DOMAIN,
)
from custom_components.actronair_neo.exceptions import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
)

# Patch target for the internal API factory
_PATCH_CREATE_API = "custom_components.actronair_neo._create_api_client"


async def test_setup_entry_success(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Test successful setup of a config entry."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)

    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert hasattr(mock_config_entry, "runtime_data")
    assert mock_config_entry.runtime_data is not None


async def test_setup_entry_auth_error(
    hass, mock_config_entry, mock_api, enable_custom_integrations
):
    """Test setup raises ConfigEntryNotReady on auth error."""
    mock_api.initialize = AsyncMock(side_effect=AuthenticationError("Auth failed"))

    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # AuthenticationError → ConfigEntryAuthFailed → SETUP_ERROR
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_api_error(
    hass, mock_config_entry, mock_api, enable_custom_integrations
):
    """Test setup retries on API error."""
    mock_api.initialize = AsyncMock(side_effect=ApiError("Connection error"))

    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # ApiError → ConfigEntryNotReady → SETUP_RETRY
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Test unloading a config entry."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)

    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_async_migrate_entry_v1_updates_data(hass, mock_config_entry):
    """Test v1 config entry migration to v2."""
    entry = MagicMock()
    entry.version = 1
    entry.data = {"serial_number": "ABC", "system_id": "123"}
    hass.config_entries.async_update_entry = MagicMock()

    result = await integration.async_migrate_entry(hass, entry)
    assert result is True
    hass.config_entries.async_update_entry.assert_called_once()


async def test_async_migrate_entry_newer_version_returns_false(hass):
    """Test migration fails for unsupported newer version."""
    entry = MagicMock()
    entry.version = 3
    entry.data = {}
    assert await integration.async_migrate_entry(hass, entry) is False


def test_build_migration_mappings():
    """Test unique-id migration mappings include zones."""
    coordinator = MagicMock()
    coordinator.device_id = "ABC123"
    coordinator.data = {
        "zones": {
            "zone_1": {"name": "Living Room"},
            "zone_2": {"name": "Main Bed"},
        }
    }
    mappings = integration._build_migration_mappings(coordinator)
    assert mappings["ABC123_main_temperature"] == "ABC123_sensor_indoor_temperature"
    assert mappings["ABC123_zone_zone_1"] == "ABC123_climate_zone_living_room"


def test_find_coordinator_from_list():
    """Test coordinator lookup helper function."""
    hass = MagicMock()
    coordinator_1 = MagicMock(device_id="ABC123")
    coordinator_2 = MagicMock(device_id="XYZ999")
    with patch(
        "custom_components.actronair_neo._get_coordinators",
        return_value=[coordinator_1, coordinator_2],
    ):
        assert integration._find_coordinator(hass, "ABC123") is coordinator_1
        assert integration._find_coordinator(hass, "MISSING") is None


def test_require_coordinator_errors(hass):
    """Test require coordinator error paths."""
    with (
        patch("custom_components.actronair_neo._find_coordinator", return_value=None),
        pytest.raises(ServiceValidationError),
    ):
        integration._require_coordinator(hass, "missing")

    coordinator = MagicMock()
    coordinator.enable_zone_control = False
    with (
        patch(
            "custom_components.actronair_neo._find_coordinator",
            return_value=coordinator,
        ),
        pytest.raises(ServiceValidationError),
    ):
        integration._require_coordinator(hass, "ABC")


async def test_handle_force_update_errors_without_devices(hass):
    """Test force update raises when no devices are configured."""
    call = MagicMock()
    call.hass = hass
    with (
        patch("custom_components.actronair_neo._get_coordinators", return_value=[]),
        pytest.raises(HomeAssistantError),
    ):
        await integration._handle_force_update(call)


async def test_handle_zone_preset_service_errors(hass):
    """Test create/apply preset handlers map errors to HA errors."""
    coordinator = MagicMock()
    coordinator.enable_zone_control = True
    coordinator.async_create_zone_preset_from_current = AsyncMock(
        side_effect=ConfigurationError("boom")
    )
    coordinator.async_apply_zone_preset = AsyncMock(
        side_effect=ConfigurationError("boom")
    )

    with patch(
        "custom_components.actronair_neo._require_coordinator",
        return_value=coordinator,
    ):
        create_call = MagicMock()
        create_call.hass = hass
        create_call.data = {"device_id": "ABC", "name": "Sleep", "description": "d"}
        with pytest.raises(HomeAssistantError):
            await integration._handle_create_zone_preset(create_call)

        apply_call = MagicMock()
        apply_call.hass = hass
        apply_call.data = {"device_id": "ABC", "name": "Sleep"}
        with pytest.raises(HomeAssistantError):
            await integration._handle_apply_zone_preset(apply_call)


async def test_handle_bulk_zone_operation(hass):
    """Test bulk zone operation passes kwargs and handles errors."""
    coordinator = MagicMock()
    coordinator.enable_zone_control = True
    coordinator.async_bulk_zone_operation = AsyncMock(
        return_value=[{"status": "success"}]
    )

    with patch(
        "custom_components.actronair_neo._require_coordinator",
        return_value=coordinator,
    ):
        call = MagicMock()
        call.hass = hass
        call.data = {
            "device_id": "ABC",
            "operation": "set_temperature",
            "zones": ["zone_1"],
            "temperature": 23.0,
            "temp_key": "temp_setpoint_cool",
        }
        await integration._handle_bulk_zone_operation(call)
        coordinator.async_bulk_zone_operation.assert_called_once()

    coordinator.async_bulk_zone_operation = AsyncMock(
        side_effect=ConfigurationError("bad")
    )
    with (
        patch(
            "custom_components.actronair_neo.__init__._require_coordinator",
            return_value=coordinator,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await integration._handle_bulk_zone_operation(call)


async def test_update_listener_zone_disable_removes_entities(hass):
    """Test options update removes zone entities when disabling zone control."""
    coordinator = MagicMock()
    coordinator.device_id = "ABC123"
    coordinator.enable_zone_control = True
    coordinator.set_enable_zone_control = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.entry_id = "entry1"
    entry.options = {CONF_ENABLE_ZONE_CONTROL: False}

    entity_registry = MagicMock()
    entity_registry.async_remove = MagicMock()
    entity_entries = [
        MagicMock(unique_id="ABC123_zone_1_switch", entity_id="switch.zone_1"),
        MagicMock(unique_id="ABC123_sensor_main", entity_id="sensor.main"),
    ]

    hass.config_entries.async_reload = AsyncMock()

    with (
        patch(
            "custom_components.actronair_neo.er.async_get", return_value=entity_registry
        ),
        patch(
            "custom_components.actronair_neo.er.async_entries_for_config_entry",
            return_value=entity_entries,
        ),
    ):
        await integration.update_listener(hass, entry)

    entity_registry.async_remove.assert_called_once_with("switch.zone_1")
    hass.config_entries.async_reload.assert_called_once_with("entry1")


async def test_async_remove_config_entry_device(hass):
    """Test device removal helper returns based on active identifier."""
    entry = MagicMock()
    entry.runtime_data = MagicMock(device_id="ABC")
    device = MagicMock()
    device.identifiers = {(DOMAIN, "XYZ")}
    assert (
        await integration.async_remove_config_entry_device(hass, entry, device) is True
    )
    device.identifiers = {(DOMAIN, "ABC")}
    assert (
        await integration.async_remove_config_entry_device(hass, entry, device) is False
    )


async def test_setup_entry_missing_access_token_raises(hass):
    """Test setup entry fails with auth-required message when token missing."""
    entry = MagicMock()
    entry.data = {"serial_number": "ABC"}
    entry.options = {}
    with pytest.raises(ConfigEntryAuthFailed):
        await integration.async_setup_entry(hass, entry)


async def test_async_migrate_entities_updates_registry(hass):
    """Test entity migration updates matching unique IDs."""
    coordinator = MagicMock()
    coordinator.device_id = "ABC123"
    coordinator.data = {"zones": {"zone_1": {"name": "Living"}}}

    entry = MagicMock()
    entry.runtime_data = coordinator
    entry.entry_id = "entry1"

    reg = MagicMock()
    old = MagicMock(entity_id="sensor.old", unique_id="ABC123_main_temperature")
    unchanged = MagicMock(entity_id="sensor.same", unique_id="not_mapped")

    with (
        patch("custom_components.actronair_neo.er.async_get", return_value=reg),
        patch(
            "custom_components.actronair_neo.er.async_entries_for_config_entry",
            return_value=[old, unchanged],
        ),
    ):
        await integration.async_migrate_entities(hass, entry)

    reg.async_update_entity.assert_called_once()


def test_register_services_registers_all():
    """Test service registration registers expected service handlers."""
    hass = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    integration._register_services(hass)
    assert hass.services.async_register.call_count == 4


def test_register_services_skips_if_already_registered():
    """Test service registration exits early when service already exists."""
    hass = MagicMock()
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_register = MagicMock()
    integration._register_services(hass)
    hass.services.async_register.assert_not_called()


async def test_handle_force_update_success(hass):
    """Test force update refreshes all coordinators."""
    call = MagicMock()
    call.hass = hass
    coordinator_a = MagicMock()
    coordinator_a.async_request_refresh = AsyncMock()
    coordinator_b = MagicMock()
    coordinator_b.async_request_refresh = AsyncMock()
    with patch(
        "custom_components.actronair_neo._get_coordinators",
        return_value=[coordinator_a, coordinator_b],
    ):
        await integration._handle_force_update(call)
    coordinator_a.async_request_refresh.assert_called_once()
    coordinator_b.async_request_refresh.assert_called_once()


async def test_create_api_client_token_refresh_callback_updates_entry(hass):
    """Test token refresh callback writes refreshed tokens to config entry."""
    entry = MagicMock()
    entry.data = {
        "access_token": "a",
        "refresh_token": "r",
        "token_expires_at": 1.0,
    }
    hass.config_entries.async_update_entry = MagicMock()

    captured: dict[str, object] = {}

    class _FakeAuth:
        def __init__(self, session):
            self.session = session

        def set_tokens(self, access_token, refresh_token, expires_at):
            captured["tokens"] = (access_token, refresh_token, expires_at)

        def set_token_refresh_callback(self, callback):
            captured["callback"] = callback

    with (
        patch("custom_components.actronair_neo.ActronAirNeoAuth", _FakeAuth),
        patch(
            "custom_components.actronair_neo.async_create_clientsession",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "custom_components.actronair_neo.ActronAirNeoApiClient",
            return_value=MagicMock(),
        ),
    ):
        await integration._create_api_client(hass, entry)

    callback = captured["callback"]
    await callback("new_a", "new_r", 9.0)
    hass.config_entries.async_update_entry.assert_called_once()


def test_require_coordinator_success(hass):
    """Test require coordinator returns coordinator when valid and enabled."""
    coordinator = MagicMock()
    coordinator.enable_zone_control = True
    with patch(
        "custom_components.actronair_neo._find_coordinator", return_value=coordinator
    ):
        assert integration._require_coordinator(hass, "ABC") is coordinator


async def test_handle_bulk_zone_operation_zone_error_maps_to_ha_error(hass):
    """Test bulk zone operation maps ZoneError to HomeAssistantError."""
    coordinator = MagicMock()
    coordinator.enable_zone_control = True
    coordinator.async_bulk_zone_operation = AsyncMock(
        side_effect=ConfigurationError("boom")
    )
    call = MagicMock()
    call.hass = hass
    call.data = {"device_id": "ABC", "operation": "enable", "zones": ["zone_1"]}
    with (
        patch(
            "custom_components.actronair_neo._require_coordinator",
            return_value=coordinator,
        ),
        pytest.raises(HomeAssistantError),
    ):
        await integration._handle_bulk_zone_operation(call)


async def test_setup_entry_starts_push(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """async_setup_entry starts the push transport."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with (
        patch(_PATCH_CREATE_API, return_value=mock_api),
        patch(
            "custom_components.actronair_neo.coordinator.ActronDataCoordinator.async_start_push",
            new_callable=AsyncMock,
        ) as start_push,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    start_push.assert_awaited()


async def test_unload_entry_stops_push(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Unloading the entry stops the push transport."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with (
        patch(_PATCH_CREATE_API, return_value=mock_api),
        patch(
            "custom_components.actronair_neo.coordinator.ActronDataCoordinator.async_stop_push",
            new_callable=AsyncMock,
        ) as stop_push,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
        await hass.config_entries.async_unload(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    stop_push.assert_awaited()


async def test_setup_entry_push_disabled_skips_discovery(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """With enable_push=False, setup completes and no push discovery runs."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_ENABLE_ZONE_CONTROL: False, CONF_ENABLE_PUSH: False},
    )
    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data
    assert coordinator.enable_push is False
    assert coordinator._push_transport is None
    mock_api.get_realtime_connection_details.assert_not_awaited()


async def test_async_remove_entry_deletes_power_format_store(hass):
    """Removing the entry deletes the stored compressor power format (#200)."""
    entry = MagicMock()
    entry.data = {"serial_number": "ABC123"}
    with patch.object(integration, "Store") as store_cls:
        store_cls.return_value.async_remove = AsyncMock()
        await integration.async_remove_entry(hass, entry)

    assert store_cls.call_args.args[2] == "actronair_neo.power_format_ABC123"
    store_cls.return_value.async_remove.assert_awaited_once()


async def test_async_remove_entry_without_serial_is_noop(hass):
    """An entry without a serial number has no store to delete."""
    entry = MagicMock()
    entry.data = {}
    with patch.object(integration, "Store") as store_cls:
        await integration.async_remove_entry(hass, entry)

    store_cls.assert_not_called()
