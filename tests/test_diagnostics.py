"""Tests for the ActronAir Neo diagnostics."""

from __future__ import annotations

import datetime as dt
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState

from custom_components.actronair_neo.diagnostics import (
    TO_REDACT,
    _redact_value,
    async_get_config_entry_diagnostics,
)

# Patch target for the internal API factory
_PATCH_CREATE_API = "custom_components.actronair_neo._create_api_client"


async def test_diagnostics(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Test diagnostics output."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)

    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert "entry" in result
    assert "data" in result


async def test_diagnostics_no_coordinator_data(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Test diagnostics when coordinator data is None."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)

    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Clear coordinator data
    coordinator = mock_config_entry.runtime_data
    coordinator.data = None

    with pytest.raises(ValueError, match="No coordinator data available"):
        await async_get_config_entry_diagnostics(hass, mock_config_entry)


def test_to_redact_contents():
    """Test the TO_REDACT set contains expected keys."""
    assert "access_token" in TO_REDACT
    assert "refresh_token" in TO_REDACT
    assert "serial" in TO_REDACT
    assert "MAC" in TO_REDACT


def test_redact_value_helper():
    """_redact_value hides real values but preserves absence markers."""
    assert _redact_value("REAL-SERIAL") == "**REDACTED**"
    assert _redact_value("Not Available") == "Not Available"
    assert _redact_value(None) is None
    assert _redact_value("") == ""


async def test_diagnostics_redacts_device_serials(
    hass,
    mock_config_entry,
):
    """Indoor/outdoor/controller serials must be redacted in the output.

    Regression test: scalar serial values were previously passed to
    async_redact_data (which only redacts mapping keys), leaking them verbatim.
    """
    coordinator = MagicMock()
    coordinator.data = {
        "main": {
            "model": "Neo",
            "firmware_version": "1.0",
            "serial_number": "ABC123",
            "compressor_state": "COOL",
            "is_on": True,
            "mode": "COOL",
            "fan_mode": "AUTO",
            "indoor_temp": 22.0,
            "indoor_humidity": 45.0,
        },
        "zones": {},
    }
    coordinator.get_diagnostics_snapshot = MagicMock(
        return_value={
            "lastKnownState": {
                "<ABC123>": {"SystemStatus_Local": {}, "Cloud": {}},
                "AirconSystem": {
                    "IndoorUnit": {"SerialNumber": "INDOOR-SECRET-1"},
                    "OutdoorUnit": {"SerialNumber": "OUTDOOR-SECRET-2"},
                    "MasterSerial": "MASTER-SECRET-3",
                },
                "LiveAircon": {},
                "RemoteZoneInfo": [],
            }
        }
    )
    coordinator.get_zone_peripheral = MagicMock(return_value=None)
    mock_config_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    info = result["data"]["info"]
    assert info["indoor_unit"]["serial"] == "**REDACTED**"
    assert info["outdoor_unit"]["serial"] == "**REDACTED**"
    assert info["controller"]["serial"] == "**REDACTED**"

    # The raw serial values must never appear anywhere in the serialized output.
    serialized = json.dumps(result, default=str)
    assert "INDOOR-SECRET-1" not in serialized
    assert "OUTDOOR-SECRET-2" not in serialized
    assert "MASTER-SECRET-3" not in serialized


async def test_diagnostics_includes_zone_wireless_sensor(
    hass,
    mock_config_entry,
):
    """Test diagnostics includes enhanced zone peripheral details."""
    coordinator = MagicMock()
    coordinator.data = {
        "main": {
            "model": "Neo",
            "firmware_version": "1.0",
            "serial_number": "ABC123",
            "compressor_state": "COOL",
            "is_on": True,
            "mode": "COOL",
            "fan_mode": "AUTO",
            "indoor_temp": 22.0,
            "indoor_humidity": 45.0,
        },
        "zones": {
            "zone_1": {
                "name": "Living",
                "is_enabled": True,
                "temp": 22.0,
                "humidity": 45.0,
            }
        },
    }
    coordinator.get_diagnostics_snapshot = MagicMock(
        return_value={
            "lastKnownState": {
                "<ABC123>": {"SystemStatus_Local": {}, "Cloud": {}},
                "AirconSystem": {
                    "IndoorUnit": {},
                    "OutdoorUnit": {},
                    "MasterSerial": "ABC123",
                },
                "LiveAircon": {},
                "RemoteZoneInfo": [{"NV_Title": "Living"}],
            }
        }
    )
    coordinator.get_zone_peripheral = MagicMock(
        return_value={
            "DeviceType": "WallSensor",
            "RemainingBatteryCapacity_pc": 78,
            "Signal_of3": "2",
            "Firmware": {"InstalledVersion": {"NRF52": "1.0.0"}},
            "SensorInputs": {
                "SHTC1": {"Temperature_oC": 22.0, "RelativeHumidity_pc": 45.0},
                "Thermistors": {"Ambient_oC": 21.0},
            },
        }
    )
    mock_config_entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    zone_1 = result["data"]["zones"]["zone_1"]
    assert "wireless_sensor" in zone_1
    assert zone_1["wireless_sensor"]["type"] == "WallSensor"


async def test_diagnostics_type_error_path(hass, mock_config_entry):
    """Test diagnostics handles unexpected structure with TypeError payload."""
    mock_config_entry.runtime_data = MagicMock()
    mock_config_entry.runtime_data.data = {
        "main": None,
        "zones": {},
    }
    mock_config_entry.runtime_data.get_diagnostics_snapshot = MagicMock(return_value={})

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["error"]["type"] == "unexpected"


async def test_diagnostics_key_error_path(hass, mock_config_entry):
    """Test diagnostics handles missing keys with KeyError payload."""
    mock_config_entry.runtime_data = MagicMock()
    mock_config_entry.runtime_data.data = {
        "main": {},
        "zones": {},
    }
    mock_config_entry.runtime_data.get_diagnostics_snapshot = MagicMock(
        return_value={"lastKnownState": {}}
    )

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["error"]["type"] == "KeyError"


async def test_diagnostics_value_error_path(hass, mock_config_entry):
    """Test diagnostics handles value formatting failures with ValueError payload."""
    mock_config_entry.runtime_data = MagicMock()
    mock_config_entry.runtime_data.get_zone_peripheral = MagicMock(
        side_effect=ValueError("bad")
    )
    mock_config_entry.runtime_data.data = {
        "main": {
            "model": "Neo",
            "firmware_version": "1.0",
            "serial_number": "ABC123",
            "indoor_humidity": "bad-humidity",
        },
        "zones": {
            "zone_1": {
                "name": "Living",
                "is_enabled": True,
                "temp": 22.0,
                "humidity": 45.0,
            }
        },
    }
    mock_config_entry.runtime_data.get_diagnostics_snapshot = MagicMock(
        return_value={
            "lastKnownState": {
                "<ABC123>": {},
                "AirconSystem": {},
                "LiveAircon": {},
            }
        }
    )

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert result["error"]["type"] == "ValueError"


async def test_diagnostics_includes_push_block(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Diagnostics output includes a push health block."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert "push" in result
    push = result["push"]
    assert push["transport"] == "mqtt"
    assert "state" in push
    assert "last_heartbeat" in push
    assert "reconnect_count" in push
    assert "last_error" in push


async def test_diagnostics_push_redacts_sensitive_keys(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Sensitive push/connection keys are in the redaction set and tokens don't leak."""
    assert {"endpoint", "user_id", "userId"}.issubset(TO_REDACT)

    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    # The raw access token must never appear anywhere in the serialized output.
    serialized = json.dumps(result, default=str)
    assert "mock_token" not in serialized


async def test_diagnostics_push_block_live_transport(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Diagnostics serialize a live transport's heartbeat/reconnect/error."""
    from custom_components.actronair_neo.api.push.models import PushState

    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data
    hb = dt.datetime(2026, 6, 1, 12, 0, 0)  # noqa: DTZ001
    transport = MagicMock()
    transport.last_heartbeat = hb
    transport.reconnect_count = 3
    transport.last_error = "timeout"
    transport.state = PushState.CONNECTED
    transport.stop = AsyncMock()
    coordinator._push_transport = transport
    coordinator.enable_push = True

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    push = result["push"]
    assert push["transport"] == "mqtt"
    assert push["last_heartbeat"] == hb.isoformat()
    assert push["reconnect_count"] == 3
    assert push["last_error"] == "timeout"
    # Heartbeat is 2026-06-01 (older than HEARTBEAT_STALE_AFTER), so push_state
    # resolves to STALE even though the transport reports CONNECTED.
    assert push["state"] == str(PushState.STALE)


async def test_diagnostics_includes_electrical_block(
    hass,
    mock_config_entry,
    mock_api,
    mock_ac_status_response,
    enable_custom_integrations,
):
    """Diagnostics export raw and normalised electrical telemetry (#200)."""
    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    electrical = result["data"]["electrical"]
    assert set(electrical["raw"]) == {
        "CompPower",
        "SupplyVoltage_Vac",
        "SupplyCurrentRMS_A",
        "SupplyPowerRMS_W",
        "OutputPowerRMS_W",
        "Capacity_kW",
        "Family",
        "CtrlBoardType",
    }
    assert set(electrical["normalised"]) == {"comp_power", "supply_voltage"}
    assert electrical["power_format"] == "unresolved"
    assert "Serial" not in json.dumps(electrical)
