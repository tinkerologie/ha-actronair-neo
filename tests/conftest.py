"""Fixtures for ActronAir Neo tests."""

from __future__ import annotations

import logging
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.actronair_neo.api.models import ZoneCapabilities
from custom_components.actronair_neo.const import (
    CONF_ACCESS_TOKEN,
    CONF_ENABLE_ZONE_CONTROL,
    CONF_REFRESH_TOKEN,
    CONF_SERIAL_NUMBER,
    CONF_TOKEN_EXPIRES_AT,
    DOMAIN,
)

# ── Constants ────────────────────────────────────────────────────

MOCK_SERIAL = "ABC123"

# The HA harness has no switch for failing on these deprecation log formats.
HA_DEPRECATION_PATTERNS = (
    re.compile(r"Detected that custom integration 'actronair_neo'"),
    re.compile(r"The deprecated .* was used from actronair_neo\b"),
    re.compile(
        r"custom_components\.actronair_neo\.[\w.]+::\w+ provides the deprecated "
    ),
)


@pytest.fixture(autouse=True)
def fail_on_ha_deprecations(caplog):
    """Fail for HA deprecation reports naming this integration."""
    caplog.set_level(logging.WARNING)
    yield
    # Import-time class migrations precede fixtures; HA Next's import check covers them.
    messages = {
        record.getMessage()
        for phase in ("setup", "call", "teardown")
        for record in caplog.get_records(phase)
        if any(
            pattern.search(record.getMessage()) for pattern in HA_DEPRECATION_PATTERNS
        )
    }
    if messages:
        pytest.fail("Home Assistant deprecations:\n" + "\n".join(sorted(messages)))


# ── Helpers ──────────────────────────────────────────────────────


def _create_mock_zone(
    index: int,
    name: str,
    *,
    is_active: bool = True,
    temp: float = 22.0,
    humidity: float = 45.0,
) -> dict:
    """Create a mock zone data dict matching CoordinatorData zone format."""
    return {
        "name": name,
        "temp": temp,
        "setpoint": 24.0,
        "is_on": is_active,
        "capabilities": ZoneCapabilities(
            exists=True,
            can_operate=is_active,
            has_temp_control=True,
            has_separate_targets=False,
            target_temp_cool=24.0,
            target_temp_heat=22.0,
            peripheral_capabilities=None,
        ),
        "humidity": humidity,
        "is_enabled": is_active,
        "temp_setpoint_cool": 24.0,
        "temp_setpoint_heat": 22.0,
        "battery_level": 80,
        "signal_strength": 2,
        "peripheral_type": "WallSensor",
        "last_connection": "2025-01-01T00:00:00Z",
        "connection_state": "CONNECTED",
        "damper_position": 75,
        "airflow_setpoint": 50,
        "airflow_control_enabled": False,
        "airflow_control_locked": False,
        "zone_max_position": 100,
        "zone_min_position": 10,
    }


def create_mock_coordinator(
    hass: HomeAssistant,
    mock_api: MagicMock,
    mock_status: dict | None = None,
    *,
    enable_zone_control: bool = False,
) -> MagicMock:
    """
    Create a mock coordinator with proper attributes for entity tests.

    Returns a MagicMock that behaves like ActronDataCoordinator without
    needing a real HA setup.
    """
    coord = MagicMock()
    coord.hass = hass
    coord.api = mock_api
    coord.device_id = MOCK_SERIAL
    coord.enable_zone_control = enable_zone_control
    coord.data = mock_status
    coord.config_entry = MagicMock()
    coord.config_entry.entry_id = "test_entry_id"
    # Coordinator methods
    coord.set_hvac_mode = AsyncMock()
    coord.set_temperature = AsyncMock()
    coord.set_fan_mode = AsyncMock()
    coord.set_zone_state = AsyncMock()
    coord.set_zone_temperature = AsyncMock()
    coord.set_away_mode = AsyncMock()
    coord.set_quiet_mode = AsyncMock()
    coord.set_enable_zone_control = AsyncMock()
    coord.set_climate_mode = AsyncMock()
    coord.turn_on = AsyncMock()
    coord.turn_off = AsyncMock()
    coord.validate_fan_mode = MagicMock(return_value="LOW")
    coord.async_request_refresh = AsyncMock()
    return coord


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def mock_api():
    """Create a mock ActronApi / API client instance."""
    api = MagicMock()
    api.get_ac_status = AsyncMock()
    api.send_command = AsyncMock()
    api.create_command = MagicMock()
    api.is_api_healthy = MagicMock(return_value=True)
    api.initialize = AsyncMock()
    api.set_system = AsyncMock()
    api.close = AsyncMock()
    api.get_devices = AsyncMock()
    api.get_ac_systems = AsyncMock(return_value=[{"serial": MOCK_SERIAL}])
    api.get_zone_capabilities = MagicMock(
        return_value=ZoneCapabilities(
            exists=True,
            can_operate=True,
            has_temp_control=True,
            has_separate_targets=False,
            target_temp_cool=24.0,
            target_temp_heat=22.0,
            peripheral_capabilities=None,
        )
    )
    api.set_zone_airflow = AsyncMock()
    api.set_zone_temperature = AsyncMock()
    api.clear_all_caches = AsyncMock()
    api._invalidate_status_cache = AsyncMock()
    api.cleanup_expired_cache = AsyncMock()
    api.refresh_token_value = "mock_token"
    api.error_count = 0
    api.get_realtime_connection_details = AsyncMock(return_value=None)
    api.get_realtime_access_token = AsyncMock(return_value="mock_token")
    api.platform = "neo"
    return api


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ACCESS_TOKEN: "mock_access_token",
            CONF_REFRESH_TOKEN: "mock_refresh_token",
            CONF_TOKEN_EXPIRES_AT: 9999999999.0,
            CONF_SERIAL_NUMBER: MOCK_SERIAL,
            "system_id": "12345",
        },
        options={
            CONF_ENABLE_ZONE_CONTROL: False,
        },
        unique_id=MOCK_SERIAL,
        title="ActronAir Neo",
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_config_entry_with_zones(hass: HomeAssistant) -> MockConfigEntry:
    """Create a mock config entry with zone control enabled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ACCESS_TOKEN: "mock_access_token",
            CONF_REFRESH_TOKEN: "mock_refresh_token",
            CONF_TOKEN_EXPIRES_AT: 9999999999.0,
            CONF_SERIAL_NUMBER: MOCK_SERIAL,
            "system_id": "12345",
        },
        options={
            CONF_ENABLE_ZONE_CONTROL: True,
        },
        unique_id=f"{MOCK_SERIAL}_zones",
        title="ActronAir Neo",
        version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_status() -> dict:
    """Create mock coordinator data matching CoordinatorData format."""
    return {
        "main": {
            "is_on": True,
            "mode": "COOL",
            "fan_mode": "AUTO",
            "fan_continuous": False,
            "base_fan_mode": "AUTO",
            "supported_fan_modes": ["LOW", "MED", "HIGH", "AUTO"],
            "temp_setpoint_cool": 21.0,
            "temp_setpoint_heat": 24.0,
            "indoor_temp": 22.5,
            "indoor_humidity": 45.0,
            "compressor_state": "COOL",
            "EnabledZones": [True, True, False, False, False, False, False, False],
            "model": "NEO-12",
            "indoor_model": "NEO-12",
            "serial_number": MOCK_SERIAL,
            "firmware_version": "1.2.3",
            "away_mode": False,
            "quiet_mode": False,
            "filter_clean_required": False,
            "defrosting": False,
        },
        "zones": {
            "zone_1": _create_mock_zone(0, "Living Room"),
            "zone_2": _create_mock_zone(1, "Bedroom"),
        },
        "live_aircon": {
            "system_on": True,
            "compressor_capacity": 40,
            "compressor_mode": "COOL",
            "am_running_fan": True,
            "fan_rpm": 800,
            "fan_pwm": 60,
            "coil_inlet": 18.0,
            "err_code": 0,
            "compressor_chasing_temp": 21.0,
            "compressor_live_temp": 22.5,
        },
        "outdoor_unit": {
            "comp_power": 700,
            "compressor_on": True,
            "comp_speed": 3000,
            "coil_temp": 15.0,
            "amb_temp": 25.0,
            "supply_voltage": 230.0,
            "supply_current": 3.0,
            "supply_power": 690.0,
            "reverse_valve_position": "Normal",
            "defrost_mode": 0,
            "drm": False,
            "err_codes": [0, 0, 0, 0, 0],
            "family": "Advance",
            "ctrl_board_type": "Type 300",
            "capacity_kw": 12.5,
        },
        "system_status": {
            "uptime_seconds": 86400,
            "board_temp": 25.0,
            "wifi_strength": 3,
            "wifi_ssid": "HomeNetwork",
            "wifi_channel": "6",
            "wifi_firmware": "1.0.0",
            "wifi_hw_errors": 0,
        },
        "cloud": {
            "connection_state": "Connected",
            "session_uptime": 3600,
            "sent_packets": 100,
            "received_packets": 200,
            "failed_sent_packets": 0,
            "session_count_since_reset": 5,
            "dns_failures": 0,
            "aborted_sockets": 0,
        },
        "servicing": {
            "error_history": [],
            "event_history": [],
        },
        "connection_meta": {
            "is_online": True,
            "last_status_update": "2025-01-01T00:00:00Z",
            "time_since_last_contact": "5 minutes",
        },
        "vft": {
            "supported": False,
            "airflow": 0.0,
        },
        "raw_data": {
            "lastKnownState": {
                f"<{MOCK_SERIAL.upper()}>": {
                    "LiveAircon": {
                        "ErrCode": 0,
                        "CompressorMode": "COOL",
                        "Filter": {
                            "NeedsAttention": False,
                            "TimeToClean_days": 30,
                        },
                        "OutdoorUnit": {
                            "ErrCode_1": 0,
                            "ErrCode_2": 0,
                            "ErrCode_3": 0,
                            "ErrCode_4": 0,
                            "ErrCode_5": 0,
                            "CoilInletTemp_oC": 18.0,
                            "FanPWM": 60,
                            "FanIsRunning": True,
                        },
                        "IndoorFanRPM": 800,
                        "IndoorFanIsRunning": True,
                    },
                    "Servicing": {
                        "NV_ErrorHistory": [],
                        "NV_AC_EventHistory": [],
                    },
                },
                "MasterInfo": {"LiveTemp_oC": 22.5, "LiveHumidity_pc": 45.0},
                "LiveAircon": {
                    "CompressorMode": "COOL",
                    "Filter": {"NeedsAttention": False, "TimeToClean_days": 30},
                },
                "UserAirconSettings": {
                    "isOn": True,
                    "Mode": "COOL",
                    "FanMode": "AUTO",
                    "TemperatureSetpoint_Cool_oC": 21.0,
                    "TemperatureSetpoint_Heat_oC": 24.0,
                    "EnabledZones": [
                        True,
                        True,
                        False,
                        False,
                        False,
                        False,
                        False,
                        False,
                    ],
                    "AwayMode": False,
                    "QuietMode": False,
                },
                "AirconSystem": {
                    "MasterSerial": MOCK_SERIAL,
                    "MasterWCFirmwareVersion": "1.2.3",
                    "IndoorUnit": {"NV_ModelNumber": "NEO-12"},
                },
                "Alerts": {"CleanFilter": False, "Defrosting": False},
                "RemoteZoneInfo": [
                    {
                        "NV_Title": "Living Room",
                        "LiveTemp_oC": 22.0,
                        "TemperatureSetpoint_oC": 24.0,
                        "CanOperate": True,
                        "LiveHumidity_pc": 45.0,
                        "ZonePosition": 15,
                    },
                    {
                        "NV_Title": "Bedroom",
                        "LiveTemp_oC": 22.0,
                        "TemperatureSetpoint_oC": 24.0,
                        "CanOperate": True,
                        "LiveHumidity_pc": 45.0,
                        "ZonePosition": 15,
                    },
                ],
            },
            "lastStatusUpdate": "2025-01-01T00:00:00Z",
        },
    }


@pytest.fixture
def mock_ac_status_response():
    """Return a mock AC status response (raw API format)."""
    return {
        "lastKnownState": {
            "MasterInfo": {"LiveTemp_oC": 22.5, "LiveHumidity_pc": 45.0},
            "LiveAircon": {
                "CompressorMode": "COOL",
                "Filter": {"NeedsAttention": False, "TimeToClean_days": 30},
            },
            "UserAirconSettings": {
                "isOn": True,
                "Mode": "COOL",
                "FanMode": "AUTO",
                "TemperatureSetpoint_Cool_oC": 21.0,
                "TemperatureSetpoint_Heat_oC": 24.0,
                "EnabledZones": [True, True, False, False, False, False, False, False],
                "AwayMode": False,
                "QuietMode": False,
            },
            "AirconSystem": {
                "MasterSerial": MOCK_SERIAL,
                "MasterWCFirmwareVersion": "1.2.3",
                "IndoorUnit": {"NV_ModelNumber": "NEO-12"},
            },
            "Alerts": {"CleanFilter": False, "Defrosting": False},
        },
    }


@pytest.fixture
def mock_devices_response():
    """Create a mock devices response."""
    return [
        {"serial": MOCK_SERIAL, "name": "Living Room AC", "type": "Neo", "id": "12345"},
        {"serial": "DEF456", "name": "Bedroom AC", "type": "Neo", "id": "67890"},
    ]


@pytest.fixture
def mock_token_response():
    """Create a mock token response."""
    return {
        "access_token": "mock_access_token",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "mock_refresh_token",
    }


@pytest.fixture
def mock_command_response():
    """Create a mock command response."""
    return {"success": True, "message": "Command executed successfully"}


@pytest.fixture
def mock_api_response():
    """
    Return a comprehensive mock API response for coordinator tests.

    This fixture mirrors the raw format returned by get_ac_status and is
    consumed by ActronDataCoordinator._parse_data.
    """
    # Use the same device ID that coordinator tests create with:
    # device_id="TEST123456"
    device_id = "TEST123456"
    return {
        "lastKnownState": {
            "MasterInfo": {
                "LiveTemp_oC": 23.5,
                "LiveHumidity_pc": 45,
            },
            "LiveAircon": {
                "CompressorMode": "COOLING",
            },
            "UserAirconSettings": {
                "isOn": True,
                "Mode": "COOL",
                "FanMode": "AUTO",
                "TemperatureSetpoint_Cool_oC": 22.0,
                "TemperatureSetpoint_Heat_oC": 20.0,
                "EnabledZones": [
                    True,
                    True,
                    False,
                    False,
                    False,
                    False,
                    False,
                    False,
                ],
                "AwayMode": False,
                "QuietMode": False,
            },
            "AirconSystem": {
                "MasterSerial": device_id,
                "MasterWCFirmwareVersion": "1.2.3",
                "MasterWCModel": "",
                "IndoorUnit": {
                    "NV_ModelNumber": "NEO-12",
                    "NV_SupportedFanModes": 15,
                },
                "Peripherals": [
                    {
                        "SerialNumber": "23E01206",
                        "DeviceType": "ZoneSensor",
                        "RemainingBatteryCapacity_pc": 85,
                        "RSSI": {"Local": 2},
                        "LastConnectionTime": "2025-01-01T00:00:00Z",
                        "ConnectionState": "Connected",
                    },
                    {
                        "SerialNumber": "23E01207",
                        "DeviceType": "ZoneSensor",
                        "RemainingBatteryCapacity_pc": 90,
                        "RSSI": {"Local": 3},
                        "LastConnectionTime": "2025-01-01T00:00:00Z",
                        "ConnectionState": "Connected",
                    },
                ],
            },
            "Alerts": {"CleanFilter": False, "Defrosting": False},
            "RemoteZoneInfo": [
                {
                    "NV_Title": "Living Room",
                    "LiveTemp_oC": 22.0,
                    "LiveHumidity_pc": 40,
                    "TemperatureSetpoint_oC": 22.0,
                    "CanOperate": True,
                    "ZonePosition": 15,
                    "Sensors": {
                        device_id: {"NV_Kind": "ZS: 23E01206"},
                    },
                },
                {
                    "NV_Title": "Bedroom",
                    "LiveTemp_oC": 21.0,
                    "LiveHumidity_pc": 42,
                    "TemperatureSetpoint_oC": 21.0,
                    "CanOperate": True,
                    "ZonePosition": 10,
                    "Sensors": {
                        device_id: {"NV_Kind": "ZS: 23E01207"},
                    },
                },
            ],
        },
    }
