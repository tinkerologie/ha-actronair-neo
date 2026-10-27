"""Support for ActronAir Neo diagnostic sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)

from .entity import ActronAirNeoEntity, ActronZoneEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ActronDataCoordinator

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ActronAir Neo diagnostic sensors."""
    coordinator: ActronDataCoordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        ActronHealthMonitorSensor(coordinator),
        ActronFastHeatingSensor(coordinator),
        ActronActiveWarningsSensor(coordinator),
    ]

    # Add YourZone enabled binary sensors for each zone
    entities.extend(
        ActronZoneYourZoneEnabledSensor(coordinator, zone_id)
        for zone_id in coordinator.data["zones"]
    )

    async_add_entities(entities)


class ActronHealthMonitorSensor(ActronAirNeoEntity, BinarySensorEntity):
    """System health monitor."""

    _attr_translation_key = "system_health"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the health monitor."""
        super().__init__(
            coordinator, "binary_sensor", "System Health", is_diagnostic=True
        )
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return True if there are system issues."""
        try:
            live_aircon = self.coordinator.data["live_aircon"]
            servicing = self.coordinator.data["servicing"]

            # Check for various error conditions
            return bool(live_aircon.get("err_code", 0) != 0) or bool(
                servicing.get("error_history", [])
            )

        except (KeyError, TypeError, ValueError):
            return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return simplified health-related attributes focusing on unique data."""
        try:
            servicing = self.coordinator.data["servicing"]
            connection_meta = self.coordinator.data["connection_meta"]

            # Focus on unique health data not available in enhanced sensors
            error_history = servicing.get("error_history", [])
            recent_events = servicing.get("event_history", [])[:5]

            return {
                # Unique health monitoring data
                "error_history": error_history,
                "recent_events": recent_events,
                "total_errors": len(error_history),
                "last_error": error_history[-1] if error_history else "None",
                # Health status summary
                "health_status": "Issues Detected" if self.is_on else "Healthy",
                "last_health_check": connection_meta.get(
                    "last_status_update", "Unknown"
                ),
                # Note: error_code now available in system_diagnostics sensor
                "note": "Current error code available in system_diagnostics sensor",
            }

        except (KeyError, TypeError, ValueError):
            return {
                "error": "Failed to get health attributes",
            }


class ActronZoneYourZoneEnabledSensor(ActronZoneEntity, BinarySensorEntity):
    """Binary sensor for YourZone enabled status."""

    _attr_translation_key = "yourzone_enabled"

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the YourZone enabled sensor."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(
            coordinator,
            "binary_sensor",
            f"{zone_name} YourZone Enabled",
            is_diagnostic=True,
        )
        self._attr_translation_placeholders = {"zone_name": zone_name}
        self.zone_id = zone_id
        self._attr_device_class = None

    @property
    def is_on(self) -> bool:
        """Return True if YourZone is enabled for this zone."""
        try:
            return self.coordinator.data["zones"][self.zone_id].get(
                "airflow_control_enabled", False
            )
        except KeyError:
            return False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available and self.zone_id in self.coordinator.data["zones"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return YourZone-specific attributes."""
        try:
            zone_data = self.coordinator.data["zones"][self.zone_id]
            return {
                "zone_id": self.zone_id,
                "zone_name": zone_data.get("name"),
                "airflow_setpoint": zone_data.get("airflow_setpoint"),
                "airflow_control_locked": zone_data.get("airflow_control_locked"),
                "damper_position": zone_data.get("damper_position"),
            }
        except KeyError:
            return {}


class ActronFastHeatingSensor(ActronAirNeoEntity, BinarySensorEntity):
    """Fast heating binary sensor."""

    _attr_translation_key = "fast_heating"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the fast heating sensor."""
        super().__init__(
            coordinator, "binary_sensor", "Fast Heating", is_diagnostic=True
        )
        self._attr_device_class = BinarySensorDeviceClass.HEAT

    @property
    def is_on(self) -> bool:
        """Return True if fast heating is active."""
        return self.coordinator.data["main"].get("fast_heating", False)


class ActronActiveWarningsSensor(ActronAirNeoEntity, BinarySensorEntity):
    """Active warnings binary sensor."""

    _attr_translation_key = "active_warnings"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the active warnings sensor."""
        super().__init__(
            coordinator, "binary_sensor", "Active Warnings", is_diagnostic=True
        )
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return True if there are active warnings."""
        warnings = self.coordinator.data["main"].get("warnings", [])
        return len(warnings) > 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return warning details including historical error codes."""
        warnings = self.coordinator.data["main"].get("warnings", [])
        attrs: dict[str, Any] = {
            "warning_count": len(warnings),
            "warnings": warnings,
        }

        # Expose historical error codes from outdoor unit for diagnostics
        # (err_codes are stored error logs, not active warnings)
        outdoor_unit = self.coordinator.data.get("outdoor_unit", {})
        err_codes = outdoor_unit.get("err_codes", [])
        historical_codes = {}
        for i, code in enumerate(err_codes, start=1):
            if code and code != 0:
                historical_codes[f"ErrCode_{i}"] = code
        if historical_codes:
            attrs["historical_error_codes"] = historical_codes

        return attrs
