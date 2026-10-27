"""Diagnostics support for ActronAir Neo."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import (
    async_redact_data,  # pyright: ignore[reportUnknownVariableType]
)
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

TO_REDACT = {
    "access_token",
    "refresh_token",
    "token_expires_at",
    "username",
    "password",
    "devices",
    "unique_id",
    "MAC",
    "mac",
    "serial",
    "serial_number",
    "SerialNumber",
    "MasterSerial",
    "id",
    "system_id",
    "ip_address",
    "MACAddress",
    "endpoint",
    "user_id",
    "userId",
}

# Marker emitted in place of sensitive scalar values. Mirrors the constant used
# by homeassistant.components.diagnostics.async_redact_data.
REDACTED = "**REDACTED**"


def _redact_value(value: Any) -> Any:
    """
    Redact a single sensitive scalar value.

    ``async_redact_data`` only redacts keys inside a mapping/list, so passing it
    a bare string (e.g. a serial number) returns the value unchanged. Use this
    helper for scalar values, preserving "not available" markers so the output
    still distinguishes "present but hidden" from "absent".
    """
    if value in (None, "", "Not Available"):
        return value
    return REDACTED


def _electrical_diagnostics(
    coordinator: Any, ou_live: dict[str, Any], ou_system: dict[str, Any]
) -> dict[str, Any]:
    """Return raw and normalised outdoor-unit electrical telemetry."""
    outdoor = coordinator.data.get("outdoor_unit", {})
    return {
        "raw": {
            "CompPower": ou_live.get("CompPower", "Not Available"),
            "SupplyVoltage_Vac": ou_live.get("SupplyVoltage_Vac", "Not Available"),
            "SupplyCurrentRMS_A": ou_live.get(
                "SupplyCurrentRMS_A", ou_live.get("SuppyCurrentRMS_A", "Not Available")
            ),
            "SupplyPowerRMS_W": ou_live.get(
                "SupplyPowerRMS_W", ou_live.get("SuppyPowerRMS_W", "Not Available")
            ),
            "OutputPowerRMS_W": ou_live.get("OutputPowerRMS_W", "Not Available"),
            "Capacity_kW": ou_system.get("Capacity_kW", "Not Available"),
            "Family": ou_system.get("Family", "Not Available"),
            "CtrlBoardType": ou_system.get("CtrlBoardType", "Not Available"),
        },
        "normalised": {
            "comp_power": outdoor.get("comp_power", "Not Available"),
            "supply_voltage": outdoor.get("supply_voltage", "Not Available"),
        },
        "power_format": getattr(coordinator, "power_format", "Not Available"),
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    if not coordinator or not coordinator.data:
        msg = "No coordinator data available"
        raise ValueError(msg)

    try:
        # Get raw API response snapshot for diagnostics
        # (private, not in coordinator.data)
        raw_data = coordinator.get_diagnostics_snapshot()
        full_state = raw_data.get("lastKnownState", {})
        # Use device serial to access the serial-keyed device section
        # (contains SystemStatus_Local, Cloud, etc.)
        device_serial = (
            coordinator.data["main"].get("serial_number") or coordinator.device_id or ""
        )
        device_section: dict[str, Any] = (
            full_state.get(f"<{str(device_serial).upper()}>", {})
            if device_serial
            else {}
        )
        # Top-level sections (AirconSystem, LiveAircon, etc.)
        aircon_system = full_state.get("AirconSystem", {})
        live_aircon = full_state.get("LiveAircon", {})
        indoor_unit = aircon_system.get("IndoorUnit", {})
        outdoor_unit = aircon_system.get("OutdoorUnit", {})

        push_transport = getattr(
            coordinator,
            "push_transport",
            coordinator._push_transport,  # noqa: SLF001
        )
        diagnostics_data: dict[str, Any] = {
            "entry": async_redact_data(entry.as_dict(), TO_REDACT),
            "data": {
                "info": {
                    "model": coordinator.data["main"]["model"],
                    "firmware_version": coordinator.data["main"]["firmware_version"],
                    "indoor_unit": {
                        "model": indoor_unit.get("NV_ModelNumber", "Not Available"),
                        "firmware": indoor_unit.get("IndoorFW", "Not Available"),
                        "serial": _redact_value(
                            indoor_unit.get("SerialNumber", "Not Available")
                        ),
                        "supported_fan_modes": indoor_unit.get(
                            "NV_SupportedFanModes", "Not Available"
                        ),
                        "auto_fan_enabled": indoor_unit.get("NV_AutoFanEnabled", False),
                    },
                    "outdoor_unit": {
                        "family": outdoor_unit.get("Family", "Not Available"),
                        "firmware": outdoor_unit.get(
                            "SoftwareVersion", "Not Available"
                        ),
                        "model": outdoor_unit.get("ModelNumber", "Not Available"),
                        "serial": _redact_value(
                            outdoor_unit.get("SerialNumber", "Not Available")
                        ),
                    },
                    "controller": {
                        "model": aircon_system.get("MasterWCModel", "Not Available"),
                        "serial": _redact_value(
                            aircon_system.get("MasterSerial", "Not Available")
                        ),
                        "firmware": aircon_system.get(
                            "MasterWCFirmwareVersion", "Not Available"
                        ),
                    },
                    "last_update": dt_util.now().isoformat(),
                },
                "system_status": {
                    "filter_clean_required": coordinator.data["main"].get(
                        "filter_clean_required", False
                    ),
                    "defrosting": coordinator.data["main"].get("defrosting", False),
                    "system_on": coordinator.data["main"].get("is_on", False),
                    "mode": coordinator.data["main"].get("mode", "OFF"),
                    "fan_mode": coordinator.data["main"].get("fan_mode", "OFF"),
                    "quiet_mode": coordinator.data["main"].get("quiet_mode", False),
                    "away_mode": coordinator.data["main"].get("away_mode", False),
                    "connection": {
                        "state": device_section.get("Cloud", {}).get(
                            "ConnectionState", "Unknown"
                        ),
                        "wifi_signal": device_section.get("SystemStatus_Local", {}).get(
                            "WifiStrength_of3", "No Signal"
                        ),
                        "wifi_ssid": "**REDACTED**",
                    },
                    "compressor": {
                        "state": coordinator.data["main"].get(
                            "compressor_state", "OFF"
                        ),
                        "capacity": live_aircon.get(
                            "CompressorCapacity", "Not Available"
                        ),
                        "current_temp": live_aircon.get(
                            "CompressorLiveTemperature", "Not Available"
                        ),
                        "target_temp": live_aircon.get(
                            "CompressorChasingTemperature", "Not Available"
                        ),
                    },
                    "fan": {
                        "running": live_aircon.get("AmRunningFan", False),
                        "pwm": live_aircon.get("FanPWM", "Not Available"),
                        "rpm": live_aircon.get("FanRPM", "Not Available"),
                    },
                },
                "environmental": {
                    "indoor": {
                        "temperature": coordinator.data["main"].get(
                            "indoor_temp", "Not Available"
                        ),
                        "humidity": coordinator.data["main"].get(
                            "indoor_humidity", "Not Available"
                        ),
                    },
                    "system": {
                        "coil_inlet": live_aircon.get("CoilInlet", "Not Available"),
                        "coil_temp": live_aircon.get("OutdoorUnit", {}).get(
                            "CoilTemp", "Not Available"
                        ),
                        "ambient_temp": device_section.get("SystemStatus_Local", {})
                        .get("SensorInputs", {})
                        .get("SHTC1", {})
                        .get("Temperature_oC", "Not Available"),
                    },
                },
                "electrical": _electrical_diagnostics(
                    coordinator, live_aircon.get("OutdoorUnit", {}), outdoor_unit
                ),
                "zones": {},
                "peripherals": [],
            },
            "push": {
                "transport": "mqtt",
                "state": str(coordinator.push_state),
                "last_heartbeat": (
                    push_transport.last_heartbeat.isoformat()
                    if push_transport and push_transport.last_heartbeat
                    else None
                ),
                "reconnect_count": (
                    push_transport.reconnect_count if push_transport else 0
                ),
                "last_error": push_transport.last_error if push_transport else None,
            },
        }

        # Get RemoteZoneInfo for zone capabilities (top-level in lastKnownState)
        remote_zone_info: list[dict[str, Any]] = full_state.get("RemoteZoneInfo", [])

        # Add zone information with enhanced capability details
        for zone_id, zone_data in coordinator.data["zones"].items():
            zone_info = {
                "name": zone_data["name"],
                "enabled": zone_data["is_enabled"],
                "temperature": zone_data["temp"],
                "humidity": zone_data["humidity"],
                "controller": {
                    "type": "Zone Temperature Sensor",
                    "status": "Enabled" if zone_data["is_enabled"] else "Disabled",
                },
                "capabilities": {},
            }

            # Find matching RemoteZoneInfo for this zone
            empty_zone_info: dict[str, Any] = {}
            matching_zone_info: dict[str, Any] = next(
                (
                    zone
                    for zone in remote_zone_info
                    if zone.get("NV_Title") == zone_data["name"]
                ),
                empty_zone_info,
            )

            # Add capability information
            if matching_zone_info:
                zone_info["capabilities"] = {
                    "variable_air_volume": matching_zone_info.get("NV_VAV", False),
                    "individual_temp_control": matching_zone_info.get("NV_ITC", False),
                    "individual_temp_display": matching_zone_info.get("NV_ITD", False),
                    "temperature_setpoints": {
                        "cool": matching_zone_info.get("TemperatureSetpoint_Cool_oC"),
                        "heat": matching_zone_info.get("TemperatureSetpoint_Heat_oC"),
                    },
                }

            # Add wireless sensor information if available
            peripheral = coordinator.get_zone_peripheral(zone_id)
            if peripheral:
                zone_info["wireless_sensor"] = {
                    "type": peripheral.get("DeviceType", "Unknown"),
                    "battery_level": peripheral.get(
                        "RemainingBatteryCapacity_pc", "Not Available"
                    ),
                    "signal_strength": peripheral.get("Signal_of3", "Not Available"),
                    "firmware": peripheral.get("Firmware", {})
                    .get("InstalledVersion", {})
                    .get("NRF52", "Not Available"),
                    "last_connection": peripheral.get(
                        "LastConnectionTime", "Not Available"
                    ),
                    "connection_state": peripheral.get("ConnectionState", "Unknown"),
                    "readings": {
                        "temperature": peripheral.get("SensorInputs", {})
                        .get("SHTC1", {})
                        .get("Temperature_oC", "Not Available"),
                        "humidity": peripheral.get("SensorInputs", {})
                        .get("SHTC1", {})
                        .get("RelativeHumidity_pc", "Not Available"),
                        "ambient": peripheral.get("SensorInputs", {})
                        .get("Thermistors", {})
                        .get("Ambient_oC", "Not Available"),
                    },
                }

            diagnostics_data["data"]["zones"][zone_id] = zone_info

    except KeyError:
        return {
            "error": {
                "type": "KeyError",
                "coordinator_available": bool(coordinator),
                "has_data": bool(coordinator and coordinator.data),
                "timestamp": dt_util.utcnow().isoformat(),
            },
            "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        }
    except ValueError:
        return {
            "error": {
                "type": "ValueError",
                "coordinator_available": bool(coordinator),
                "has_data": bool(coordinator and coordinator.data),
                "timestamp": dt_util.utcnow().isoformat(),
            },
            "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        }
    except (TypeError, AttributeError):
        return {
            "error": {
                "type": "unexpected",
                "coordinator_available": bool(coordinator),
                "has_data": bool(coordinator and coordinator.data),
                "timestamp": dt_util.utcnow().isoformat(),
            },
            "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        }
    else:
        return diagnostics_data
