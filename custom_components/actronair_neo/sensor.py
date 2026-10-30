"""Support for ActronAir Neo sensors."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfRatio,
    UnitOfTemperature,
)

from .const import (
    ATTR_BATTERY_LEVEL,
    ATTR_LAST_UPDATED,
    ATTR_ZONE_NAME,
    ATTR_ZONE_TYPE,
    WATTS_PER_KILOWATT,
)
from .entity import ActronAirNeoEntity, ActronZoneEntity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from .coordinator import ActronDataCoordinator

PARALLEL_UPDATES = 0


def _format_power(value: float | str | None) -> str:
    """
    Format a power value (watts) to a human-readable string.

    Values of 1000 W or above are displayed in kW with one decimal place;
    lower values are displayed in whole watts.  ``None`` and ``"Unknown"``
    are returned as ``"Unknown"``.
    """
    if value is None or value == "Unknown":
        return "Unknown"
    try:
        power = float(value)
    except (ValueError, TypeError):
        return str(value)
    if power >= WATTS_PER_KILOWATT:
        return f"{power / WATTS_PER_KILOWATT:.1f} kW"
    return f"{power:.0f} W"


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ActronAir Neo sensors from a config entry."""
    coordinator: ActronDataCoordinator = entry.runtime_data

    entities: list[SensorEntity] = [
        ActronMainSensor(coordinator),
        # Enhanced diagnostic sensors
        ActronSystemDiagnosticSensor(coordinator),
        ActronConnectivitySensor(coordinator),
        ActronPerformanceSensor(coordinator),
        ActronServiceReminderSensor(coordinator),
    ]

    # Add outdoor temperature sensor if data is available
    outdoor_temp = coordinator.data["main"].get("outdoor_temp")
    if outdoor_temp is not None:
        entities.append(ActronOutdoorTemperatureSensor(coordinator))

    # Only add power sensors if hardware supports power monitoring
    if coordinator.supports_power_monitoring():
        entities.extend(
            [
                ActronCompressorPowerSensor(coordinator),
                ActronCompressorEnergySensor(coordinator),
            ]
        )

    # Add zone sensors
    for zone_id, zone_data in coordinator.data["zones"].items():
        entities.append(ActronZoneSensor(coordinator, zone_id))

        # Non-YourZone systems expose the live damper position as a read-only
        # percentage sensor rather than a controllable cover entity.
        if not zone_data.get("airflow_control_enabled"):
            entities.append(ActronZoneDamperPositionSensor(coordinator, zone_id))

        # Add humidity sensor if zone reports humidity
        if zone_data.get("humidity") is not None:
            entities.append(ActronZoneHumiditySensor(coordinator, zone_id))

        # Add battery sensor only for wireless zones (battery_level populated)
        if zone_data.get("battery_level") is not None:
            entities.append(ActronZoneBatterySensor(coordinator, zone_id))

    async_add_entities(entities)


class ActronMainSensor(ActronAirNeoEntity, SensorEntity):
    """Main temperature sensor."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the main temperature sensor."""
        super().__init__(coordinator, "sensor", "Avg. Inside Temp")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        return self.coordinator.data["main"]["indoor_temp"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return entity specific state attributes."""
        return {
            "Inside Humidity": self.coordinator.data["main"]["indoor_humidity"],
        }


class ActronZoneSensor(ActronZoneEntity, SensorEntity):
    """Zone temperature sensor."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone sensor."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(coordinator, "sensor", f"Zone {zone_name}")
        self.zone_id = zone_id
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    def _format_signal_strength(self, signal: float | None) -> str:
        """Format signal strength with quality rating."""
        if not isinstance(signal, (int, float)):
            return "Unknown"

        if signal > -50:  # noqa: PLR2004
            quality = "Excellent"
        elif signal > -60:  # noqa: PLR2004
            quality = "Good"
        elif signal > -70:  # noqa: PLR2004
            quality = "Fair"
        else:
            quality = "Poor"

        return f"{signal} dBm ({quality})"

    @property
    def native_value(self) -> StateType:
        """Return the temperature of the zone."""
        try:
            return self.coordinator.data["zones"][self.zone_id]["temp"]
        except KeyError:
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.zone_id in self.coordinator.data["zones"]
            and self.coordinator.data["zones"][self.zone_id].get("temp") is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return zone specific attributes including humidity and battery level."""
        try:
            zone_data = self.coordinator.data["zones"][self.zone_id]
            peripheral_data = self.coordinator.get_zone_peripheral(self.zone_id)
            attributes = self._build_zone_attributes(zone_data)
            if peripheral_data:
                self._enrich_from_peripheral(attributes, peripheral_data)
        except (KeyError, TypeError, ValueError):
            return {}
        else:
            return attributes

    def _build_zone_attributes(self, zone_data: Mapping[str, Any]) -> dict[str, Any]:
        """Build base zone attributes from zone data."""
        attributes: dict[str, Any] = {
            ATTR_ZONE_NAME: zone_data["name"],
            "humidity": zone_data["humidity"],
            "enabled": zone_data["is_enabled"],
        }

        if zone_data.get("battery_level") is not None:
            attributes[ATTR_BATTERY_LEVEL] = zone_data["battery_level"]

        if zone_data.get("peripheral_type") is not None:
            attributes[ATTR_ZONE_TYPE] = zone_data["peripheral_type"]

        if zone_data.get("last_connection") is not None:
            attributes[ATTR_LAST_UPDATED] = zone_data["last_connection"]
        if zone_data.get("connection_state") is not None:
            attributes["connection_state"] = zone_data["connection_state"]

        if zone_data.get("signal_strength") is not None:
            signal = zone_data["signal_strength"]
            attributes["signal_strength"] = self._format_signal_strength(signal)

        return attributes

    def _enrich_from_peripheral(
        self,
        attributes: dict[str, Any],
        peripheral_data: Mapping[str, Any],
    ) -> None:
        """Enrich zone attributes from peripheral data."""
        if (
            ATTR_BATTERY_LEVEL not in attributes
            and "RemainingBatteryCapacity_pc" in peripheral_data
        ):
            attributes[ATTR_BATTERY_LEVEL] = peripheral_data[
                "RemainingBatteryCapacity_pc"
            ]

        if ATTR_ZONE_TYPE not in attributes and "DeviceType" in peripheral_data:
            attributes[ATTR_ZONE_TYPE] = peripheral_data["DeviceType"]

        if (
            "signal_strength" not in attributes
            and "Signal_of3" in peripheral_data
            and peripheral_data["Signal_of3"] != "NA"
        ):
            try:
                signal = int(peripheral_data["Signal_of3"])
                if 0 <= signal <= 3:  # noqa: PLR2004
                    # Signal_of3 is a 0-3 bars scale, not dBm
                    bars_map = {
                        0: "Poor (0 bars)",
                        1: "Fair (1 bar)",
                        2: "Good (2 bars)",
                        3: "Excellent (3 bars)",
                    }
                    attributes["signal_strength"] = bars_map[signal]
                else:
                    # Assume dBm value
                    attributes["signal_strength"] = self._format_signal_strength(signal)
            except (ValueError, TypeError):
                attributes["signal_strength"] = peripheral_data["Signal_of3"]

        if (
            ATTR_LAST_UPDATED not in attributes
            and "LastConnectionTime" in peripheral_data
        ):
            attributes[ATTR_LAST_UPDATED] = peripheral_data["LastConnectionTime"]

        if (
            "connection_state" not in attributes
            and "ConnectionState" in peripheral_data
        ):
            attributes["connection_state"] = peripheral_data["ConnectionState"]


class ActronZoneDamperPositionSensor(ActronZoneEntity, SensorEntity):
    """Read-only sensor exposing the current zone damper position."""

    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone damper position sensor."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(coordinator, "sensor", f"{zone_name} Damper Position")
        self.zone_id = zone_id
        self._attr_icon = "mdi:valve"

    @property
    def native_value(self) -> StateType:
        """Return the live damper position percentage."""
        try:
            return self.coordinator.data["zones"][self.zone_id].get("damper_position")
        except KeyError:
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.zone_id in self.coordinator.data["zones"]
            and self.coordinator.data["zones"][self.zone_id].get("damper_position")
            is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return damper-specific attributes."""
        try:
            zone_data = self.coordinator.data["zones"][self.zone_id]
        except KeyError:
            return {}

        return {
            "zone_id": self.zone_id,
            "zone_name": zone_data.get("name"),
            "zone_max_position": zone_data.get("zone_max_position"),
            "zone_min_position": zone_data.get("zone_min_position"),
            "yourzone_enabled": zone_data.get("airflow_control_enabled"),
            "airflow_setpoint": zone_data.get("airflow_setpoint"),
        }


class ActronZoneHumiditySensor(ActronZoneEntity, SensorEntity):
    """Zone humidity sensor."""

    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "zone_humidity"

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone humidity sensor."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(coordinator, "sensor", f"Zone {zone_name} Humidity")
        self._attr_translation_placeholders = {"zone_name": zone_name}
        self.zone_id = zone_id

    @property
    def native_value(self) -> StateType:
        """Return the humidity of the zone."""
        try:
            return self.coordinator.data["zones"][self.zone_id].get("humidity")
        except KeyError:
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.zone_id in self.coordinator.data["zones"]
            and self.coordinator.data["zones"][self.zone_id].get("humidity") is not None
        )


class ActronZoneBatterySensor(ActronZoneEntity, SensorEntity):
    """
    Zone sensor battery level.

    Only created for wireless zone sensors that report battery level.
    Wired sensors do not have battery data.
    """

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "zone_battery"

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone battery sensor."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(coordinator, "sensor", f"Zone {zone_name} Battery")
        self._attr_translation_placeholders = {"zone_name": zone_name}
        self.zone_id = zone_id

    @property
    def native_value(self) -> StateType:
        """Return the battery level of the zone sensor."""
        try:
            return self.coordinator.data["zones"][self.zone_id].get("battery_level")
        except KeyError:
            return None

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.zone_id in self.coordinator.data["zones"]
            and self.coordinator.data["zones"][self.zone_id].get("battery_level")
            is not None
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes about the wireless sensor."""
        try:
            zone_data = self.coordinator.data["zones"][self.zone_id]
        except KeyError:
            return {}

        attrs: dict[str, Any] = {}
        if zone_data.get("peripheral_type") is not None:
            attrs["sensor_type"] = zone_data["peripheral_type"]
        if zone_data.get("signal_strength") is not None:
            attrs["signal_strength_dbm"] = zone_data["signal_strength"]
        if zone_data.get("connection_state") is not None:
            attrs["connection_state"] = zone_data["connection_state"]
        if zone_data.get("last_connection") is not None:
            attrs["last_connection"] = zone_data["last_connection"]
        return attrs


class ActronSystemDiagnosticSensor(ActronAirNeoEntity, SensorEntity):
    """Enhanced system diagnostic sensor with live data and user-friendly formatting."""

    _attr_translation_key = "system_diagnostics"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the system diagnostic sensor."""
        super().__init__(
            coordinator, "sensor", "System Diagnostics", is_diagnostic=True
        )
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None
        self._attr_state_class = None

    @property
    def native_value(self) -> str:
        """Return the overall system status."""
        try:
            main_data = self.coordinator.data["main"]
        except (KeyError, TypeError):
            return "Unknown"
        else:
            if main_data.get("is_on", False):
                mode = main_data.get("mode", "Unknown").title()
                return f"Running ({mode})"
            return "Standby"

    def _format_uptime(self, seconds: Any) -> str:
        """Format uptime to human readable string."""
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "Unknown"

        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _format_temperature(self, value: Any) -> str:
        """Format temperature value."""
        if value is None or value == "Unknown":
            return "Unknown"
        try:
            return f"{float(value):.1f}°C"
        except (ValueError, TypeError):
            return str(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enhanced diagnostic attributes with live data."""
        try:
            main_data = self.coordinator.data["main"]
            live_aircon = self.coordinator.data["live_aircon"]
            outdoor_unit = self.coordinator.data["outdoor_unit"]
            system_status = self.coordinator.data["system_status"]
            connection_meta = self.coordinator.data["connection_meta"]
            vft = self.coordinator.data["vft"]

            return {
                # System Information
                "model": main_data.get("model", "Unknown"),
                "firmware_version": main_data.get("firmware_version", "Unknown"),
                "serial_number": main_data.get("serial_number", "Unknown"),
                # Live System Status
                "system_uptime": self._format_uptime(
                    system_status.get("uptime_seconds", 0)
                ),
                "operating_mode": main_data.get("mode", "Unknown").title(),
                "fan_mode": main_data.get("fan_mode", "Unknown").title(),
                "quiet_mode_active": main_data.get("quiet_mode", False),
                "away_mode_active": main_data.get("away_mode", False),
                # Live Performance Data (Enhanced for GitHub Issue #16)
                "compressor_running": live_aircon.get("system_on", False),
                "compressor_capacity": f"{live_aircon.get('compressor_capacity', 0)}%",
                "compressor_usage": live_aircon.get(
                    "compressor_capacity", 0
                ),  # Raw percentage for automations
                "fan_running": live_aircon.get("am_running_fan", False),
                "fan_speed": f"{live_aircon.get('fan_rpm', 0)} RPM",
                "fan_speed_rpm": live_aircon.get(
                    "fan_rpm", 0
                ),  # Raw RPM for automations
                "current_fan_speed": live_aircon.get(
                    "fan_rpm", 0
                ),  # Alias for user request
                # Power and Electrical Data (GitHub Issue #16)
                "compressor_power": _format_power(outdoor_unit.get("comp_power", 0)),
                "supply_voltage": (f"{outdoor_unit.get('supply_voltage', 0):.1f} VAC"),
                "supply_current": (f"{outdoor_unit.get('supply_current', 0):.1f} A"),
                "supply_power": _format_power(outdoor_unit.get("supply_power", 0)),
                "system_capacity": f"{outdoor_unit.get('capacity_kw', 0):.1f} kW",
                # Air Volume Data (if available)
                "air_volume": f"{vft.get('airflow', 0):.1f} m\u00b3/h"
                if vft.get("supported", False)
                else "Not Supported",
                # Live Temperature Readings
                "indoor_temperature": self._format_temperature(
                    main_data.get("indoor_temp")
                ),
                "indoor_humidity": f"{main_data.get('indoor_humidity', 0):.1f}%",
                "coil_inlet_temperature": self._format_temperature(
                    live_aircon.get("coil_inlet")
                ),
                "ambient_temperature": self._format_temperature(
                    system_status.get("board_temp")
                ),
                # System Health
                "filter_status": "Needs Cleaning"
                if main_data.get("filter_clean_required")
                else "Clean",
                "defrosting_active": main_data.get("defrosting", False),
                "error_code": live_aircon.get("err_code", 0),
                # Last Update Information
                "last_api_update": connection_meta.get("last_status_update", "Unknown"),
                "data_freshness": "Live"
                if self.coordinator.last_update_success
                else "Stale",
            }

        except (KeyError, TypeError, ValueError):
            return {
                "error": "Failed to retrieve system diagnostics",
            }

    def _format_power_value(self, power_value: float) -> str:
        """
        Format power value with appropriate units.

        Delegates to the module-level :func:`_format_power` helper.
        Kept for backwards compatibility with any callers that reference
        this method directly (e.g. existing tests).
        """
        return _format_power(power_value)


class ActronConnectivitySensor(ActronAirNeoEntity, SensorEntity):
    """Enhanced connectivity sensor with signal quality and connection health."""

    _attr_translation_key = "connectivity_status"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the connectivity sensor."""
        super().__init__(
            coordinator, "sensor", "Connectivity Status", is_diagnostic=True
        )
        self._attr_native_unit_of_measurement = None
        self._attr_device_class = None
        self._attr_state_class = None

    @property
    def native_value(self) -> str:
        """Return the connectivity status."""
        try:
            status = self._determine_connectivity_status()
        except (KeyError, TypeError):
            return "Unknown"
        else:
            return status

    def _determine_connectivity_status(self) -> str:
        """Determine connectivity status from parsed data."""
        connection_meta = self.coordinator.data.get("connection_meta", {})
        cloud = self.coordinator.data.get("cloud", {})

        device_online = connection_meta.get("is_online", False)
        connection_state = cloud.get("connection_state", "Unknown")

        if device_online and self.coordinator.last_update_success:
            if connection_state == "Connected":
                return "Online"
            if connection_state == "Unknown":
                return "Online (Cloud Status Unknown)"
            return f"Online (Cloud: {connection_state})"
        if device_online:
            return "Online (Limited Connectivity)"
        if connection_state != "Unknown":
            return f"Offline ({connection_state})"
        return "Offline"

    def _format_wifi_signal(self, signal: float | None) -> dict[str, str]:
        """Format WiFi signal strength with quality rating."""
        if not isinstance(signal, (int, float)):
            return {"strength": "Unknown", "quality": "Unknown", "bars": "0/4"}

        if signal > -50:  # noqa: PLR2004
            quality = "Excellent"
            bars = "4/4"
        elif signal > -60:  # noqa: PLR2004
            quality = "Good"
            bars = "3/4"
        elif signal > -70:  # noqa: PLR2004
            quality = "Fair"
            bars = "2/4"
        else:
            quality = "Poor"
            bars = "1/4"

        return {"strength": f"{signal} dBm", "quality": quality, "bars": bars}

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enhanced connectivity attributes."""
        try:
            system_status = self.coordinator.data["system_status"]
            cloud = self.coordinator.data["cloud"]
            connection_meta = self.coordinator.data["connection_meta"]

            # WiFi signal analysis
            wifi_signal = self._format_wifi_signal(system_status.get("wifi_strength"))

            return {
                # Connection Status
                "cloud_connection": cloud.get("connection_state", "Unknown"),
                "connection_uptime": self._format_uptime(
                    cloud.get("session_uptime", 0)
                ),
                # WiFi Information
                "wifi_network": system_status.get("wifi_ssid", "Unknown"),
                "wifi_signal_strength": wifi_signal["strength"],
                "wifi_signal_quality": wifi_signal["quality"],
                "wifi_signal_bars": wifi_signal["bars"],
                "wifi_channel": system_status.get("wifi_channel", "Unknown"),
                "wifi_firmware": system_status.get("wifi_firmware", "Unknown"),
                # Connection Statistics
                "packets_sent": cloud.get("sent_packets", 0),
                "packets_received": cloud.get("received_packets", 0),
                "failed_packets": cloud.get("failed_sent_packets", 0),
                "connection_sessions": cloud.get("session_count_since_reset", 0),
                # Error Monitoring
                "wifi_hardware_errors": system_status.get("wifi_hw_errors", 0),
                "dns_failures": cloud.get("dns_failures", 0),
                "socket_errors": cloud.get("aborted_sockets", 0),
                # Data Freshness
                "last_contact": connection_meta.get(
                    "time_since_last_contact", "Unknown"
                ),
                "last_status_update": connection_meta.get(
                    "last_status_update", "Unknown"
                ),
                "device_online": connection_meta.get("is_online", False),
            }

        except (KeyError, TypeError, ValueError):
            return {
                "error": "Failed to retrieve connectivity data",
            }

    def _format_uptime(self, seconds: Any) -> str:
        """Format uptime to human readable string."""
        if not isinstance(seconds, (int, float)) or seconds < 0:
            return "Unknown"

        days, remainder = divmod(int(seconds), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"


class ActronPerformanceSensor(ActronAirNeoEntity, SensorEntity):
    """Enhanced performance sensor with real-time operational metrics."""

    _attr_translation_key = "performance_metrics"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the performance sensor."""
        super().__init__(
            coordinator, "sensor", "Performance Metrics", is_diagnostic=True
        )
        self._attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
        self._attr_device_class = None
        self._attr_state_class = None
        # Explicitly disable polling - coordinator handles updates
        self._attr_should_poll = False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        try:
            if not super().available:
                return False

            live_aircon = self.coordinator.data.get("live_aircon", {})
            has_data = bool(live_aircon)
        except (KeyError, TypeError, AttributeError):
            return False
        else:
            return has_data

    @property
    def native_value(self) -> float | None:
        """Return the overall system efficiency percentage."""
        try:
            live_aircon = self.coordinator.data.get("live_aircon", {})

            if not live_aircon:
                return None

            # Calculate efficiency based on compressor capacity and system status
            # Return capacity even when system is off (0%) for consistent updates
            capacity = live_aircon.get("compressor_capacity") or 0
            return float(capacity)

        except (KeyError, TypeError, ValueError):
            return None

    def _format_temperature(self, value: Any) -> str:
        """Format temperature value."""
        if value is None or value == "Unknown":
            return "Unknown"
        try:
            return f"{float(value):.1f}°C"
        except (ValueError, TypeError):
            return str(value)

    def _format_power(self, value: Any) -> str:
        """
        Format power value.

        Delegates to the module-level :func:`_format_power` helper.
        Kept for backwards compatibility with any callers that reference
        this method directly (e.g. existing tests).
        """
        return _format_power(value)

    def _get_operational_status(self, live_aircon: Mapping[str, Any]) -> str:
        """Determine operational status from live data."""
        if not live_aircon.get("system_on", False):
            return "Standby"

        compressor_on = live_aircon.get("compressor_mode", "OFF") != "OFF"
        fan_running = live_aircon.get("am_running_fan", False)

        if compressor_on and fan_running:
            return "Active Cooling/Heating"
        if fan_running:
            return "Fan Only"
        if compressor_on:
            return "Compressor Only"
        return "System On (Idle)"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return enhanced performance attributes with live operational data."""
        try:
            main_data = self.coordinator.data.get("main", {})
            live_aircon = self.coordinator.data.get("live_aircon", {})
            outdoor_unit = self.coordinator.data.get("outdoor_unit", {})
            system_status = self.coordinator.data.get("system_status", {})

            if not live_aircon:
                return {"status": "No live data available"}

            return {
                # Operational Status
                "operational_status": self._get_operational_status(live_aircon),
                "system_running": live_aircon.get("system_on", False),
                "defrosting": main_data.get("defrosting", False),
                # Compressor Performance
                "compressor_mode": live_aircon.get("compressor_mode", "Unknown"),
                "compressor_capacity": (
                    f"{live_aircon.get('compressor_capacity', 0)}%"
                ),
                "compressor_power": self._format_power(
                    outdoor_unit.get("comp_power", 0)
                ),
                "compressor_speed": f"{outdoor_unit.get('comp_speed', 0)} RPM",
                "compressor_running": outdoor_unit.get("compressor_on", False),
                # Fan Performance
                "fan_running": live_aircon.get("am_running_fan", False),
                "fan_speed": f"{live_aircon.get('fan_rpm', 0)} RPM",
                "fan_power": f"{live_aircon.get('fan_pwm', 0)}%",
                # Temperature Control
                "target_temperature": self._format_temperature(
                    live_aircon.get("compressor_chasing_temp")
                ),
                "current_temperature": self._format_temperature(
                    live_aircon.get("compressor_live_temp")
                ),
                "coil_inlet_temp": self._format_temperature(
                    live_aircon.get("coil_inlet")
                ),
                "outdoor_coil_temp": self._format_temperature(
                    outdoor_unit.get("coil_temp")
                ),
                # System Efficiency Metrics
                "indoor_temp": self._format_temperature(main_data.get("indoor_temp")),
                "indoor_humidity": f"{main_data.get('indoor_humidity', 0):.1f}%",
                "ambient_temp": self._format_temperature(
                    system_status.get("board_temp")
                ),
                "outdoor_ambient_temp": self._format_temperature(
                    outdoor_unit.get("amb_temp")
                ),
                # Valve and Control
                "reverse_valve_position": outdoor_unit.get(
                    "reverse_valve_position", "Unknown"
                ),
                "defrost_mode": outdoor_unit.get("defrost_mode", 0),
                "drm_active": outdoor_unit.get("drm", False),
                # Error Monitoring
                "error_code": live_aircon.get("err_code", 0),
                "outdoor_errors": {
                    f"error_{i}": code
                    for i, code in enumerate(
                        outdoor_unit.get("err_codes", [0, 0, 0, 0, 0]), start=1
                    )
                },
                # Zone Performance Summary
                "active_zones": sum(
                    1
                    for zone in self.coordinator.data.get("zones", {}).values()
                    if zone.get("is_enabled", False)
                ),
                "total_zones": len(self.coordinator.data.get("zones", {})),
                # Power Management
                "quiet_mode": main_data.get("quiet_mode", False),
                "away_mode": main_data.get("away_mode", False),
                "continuous_fan": main_data.get("fan_continuous", False),
            }

        except (KeyError, TypeError, ValueError):
            return {
                "error": "Failed to retrieve performance data",
            }


class ActronCompressorPowerSensor(ActronAirNeoEntity, SensorEntity):
    """Compressor power sensor for energy dashboard compatibility."""

    _attr_translation_key = "compressor_power"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the compressor power sensor."""
        super().__init__(coordinator, "sensor", "Compressor Power")
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the compressor power in watts."""
        try:
            live_aircon = self.coordinator.data.get("live_aircon", {})
            outdoor_unit = self.coordinator.data.get("outdoor_unit", {})

            if not live_aircon:
                return None

            # Check if compressor is running
            compressor_running = live_aircon.get("system_on", False)

            if not compressor_running:
                return 0.0

            # Get compressor power from outdoor unit
            compressor_power = outdoor_unit.get("comp_power") or 0

            # Return power as float, ensuring it's not negative
            return max(0.0, float(compressor_power))

        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        try:
            live_aircon = self.coordinator.data.get("live_aircon", {})
            outdoor_unit = self.coordinator.data.get("outdoor_unit", {})

            if not live_aircon:
                return {"error": "No live aircon data available"}

            return {
                "compressor_running": live_aircon.get("system_on", False),
                "compressor_capacity": (
                    f"{live_aircon.get('compressor_capacity', 0)}%"
                ),
                "compressor_mode": live_aircon.get("compressor_mode", "Unknown"),
                "system_mode": self.coordinator.data.get("main", {}).get(
                    "mode", "Unknown"
                ),
                "raw_power_value": outdoor_unit.get("comp_power", 0),
            }

        except (KeyError, TypeError):
            return {"error": "Failed to retrieve power data"}


class ActronCompressorEnergySensor(ActronAirNeoEntity, RestoreSensor):
    """Compressor energy sensor for energy dashboard compatibility."""

    _attr_translation_key = "compressor_energy"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the compressor energy sensor."""
        super().__init__(coordinator, "sensor", "Compressor Energy")
        self._attr_device_class = SensorDeviceClass.ENERGY
        self._attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING

        # Initialize energy tracking variables
        self._last_power = 0.0
        self._last_update: datetime | None = None
        self._total_energy = 0.0

    async def async_added_to_hass(self) -> None:
        """Restore previous total energy consumption state on startup."""
        await super().async_added_to_hass()
        if (
            last_sensor_data := await self.async_get_last_sensor_data()
        ) is not None and last_sensor_data.native_value is not None:
            with contextlib.suppress(ValueError, TypeError):
                self._total_energy = max(0.0, float(str(last_sensor_data.native_value)))

    @property
    def native_value(self) -> float | None:
        """Return the total energy consumption in kWh."""
        try:
            # Get current power reading
            live_aircon = self.coordinator.data.get("live_aircon", {})
            outdoor_unit = self.coordinator.data.get("outdoor_unit", {})

            if not live_aircon:
                return None

            # Check if compressor is running
            compressor_running = live_aircon.get("system_on", False)

            if not compressor_running:
                current_power = 0.0
            else:
                # Get compressor power from outdoor unit
                compressor_power = outdoor_unit.get("comp_power") or 0
                current_power = max(0.0, float(compressor_power))

            # Calculate energy using trapezoidal integration
            current_time = datetime.now(UTC)

            if self._last_update is not None:
                # Calculate time difference in hours
                time_diff = (current_time - self._last_update).total_seconds() / 3600.0

                # Use trapezoidal rule for integration
                # (average of current and last power * time)
                if time_diff > 0 and time_diff < 1.0:  # Ignore large gaps (> 1 hour)
                    avg_power = (current_power + self._last_power) / 2.0
                    energy_increment = (
                        avg_power * time_diff
                    ) / 1000.0  # Convert W*h to kWh
                    self._total_energy += energy_increment

            # Update tracking variables
            self._last_power = current_power
            self._last_update = current_time

            return round(self._total_energy, 3)

        except (KeyError, TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        try:
            live_aircon = self.coordinator.data.get("live_aircon", {})

            if not live_aircon:
                return {"error": "No live aircon data available"}

            return {
                "current_power_w": self._last_power,
                "compressor_running": live_aircon.get("system_on", False),
                "compressor_capacity": (
                    f"{live_aircon.get('compressor_capacity', 0)}%"
                ),
                "integration_method": "trapezoidal",
                "last_update": self._last_update.isoformat()
                if self._last_update
                else None,
            }

        except (KeyError, TypeError):
            return {"error": "Failed to retrieve energy data"}


class ActronOutdoorTemperatureSensor(ActronAirNeoEntity, SensorEntity):
    """Outdoor temperature sensor."""

    _attr_translation_key = "outdoor_temperature"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the outdoor temperature sensor."""
        super().__init__(coordinator, "sensor", "Outdoor Temperature")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> StateType:
        """Return the outdoor temperature."""
        return self.coordinator.data["main"].get("outdoor_temp")

    @property
    def available(self) -> bool:
        """Return if entity is available (None means sensor unavailable)."""
        return (
            super().available
            and self.coordinator.data["main"].get("outdoor_temp") is not None
        )


class ActronServiceReminderSensor(ActronAirNeoEntity, SensorEntity):
    """Service reminder sensor."""

    _attr_translation_key = "service_reminder"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the service reminder sensor."""
        super().__init__(coordinator, "sensor", "Service Reminder", is_diagnostic=True)

    @property
    def native_value(self) -> StateType:
        """Return the service reminder time."""
        return self.coordinator.data["main"].get("service_reminder_time", "NA")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "enabled": self.coordinator.data["main"].get(
                "service_reminder_enabled", False
            ),
        }
