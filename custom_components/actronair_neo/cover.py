"""Cover platform for ActronAir Neo integration (zone dampers)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.cover import (  # type: ignore[import-untyped]
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)

from .dashboard import DashboardRole
from .entity import ActronZoneEntity

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
    """Set up ActronAir Neo cover entities (zone dampers)."""
    coordinator: ActronDataCoordinator = entry.runtime_data

    entities = [
        ActronZoneDamperCover(coordinator, zone_id)
        for zone_id, zone_data in coordinator.data["zones"].items()
        if zone_data.get("airflow_control_enabled")
    ]

    async_add_entities(entities)


class ActronZoneDamperCover(ActronZoneEntity, CoverEntity):
    """
    Cover entity representing a zone damper (YourZone airflow control).

    Uses CoverDeviceClass.DAMPER to model the physical zone damper.
    current_cover_position reflects the actual damper position (read-only),
    while set_cover_position sets the target airflow setpoint.
    """

    dashboard_role = DashboardRole.ZONE_DAMPER

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_supported_features = (
        CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
    )
    _attr_translation_key = "zone_damper"

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone damper cover entity."""
        zone_info = coordinator.data.get("zones", {}).get(zone_id)
        zone_name = (
            zone_info.get("name", f"Zone {zone_id}")
            if zone_info is not None
            else f"Zone {zone_id}"
        )
        super().__init__(
            coordinator,
            "cover",
            f"{zone_name} Damper",
        )
        self._attr_translation_placeholders = {"zone_name": zone_name}
        self.zone_id = zone_id
        self.zone_index = int(zone_id.split("_")[1]) - 1

    @property
    def current_cover_position(self) -> int | None:
        """Return the current damper position (0-100%)."""
        return self.coordinator.data["zones"][self.zone_id].get("damper_position")

    @property
    def is_closed(self) -> bool:
        """Return True if the damper is fully closed."""
        position = self.current_cover_position
        return position is not None and position == 0

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        zone_data = self.coordinator.data["zones"].get(self.zone_id)
        if zone_data is None:
            return False
        return (
            self.coordinator.last_update_success
            and bool(zone_data.get("airflow_control_enabled", False))
            and not bool(zone_data.get("airflow_control_locked", False))
        )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the damper to a specific position (rounded to 5% increments)."""
        position = kwargs[ATTR_POSITION]
        # Round to nearest 5% increment per API requirement
        rounded = round(position / 5) * 5
        await self.coordinator.set_zone_airflow(self.zone_index, rounded)

    async def async_open_cover(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Fully open the damper (100% airflow)."""
        await self.coordinator.set_zone_airflow(self.zone_index, 100)

    async def async_close_cover(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Fully close the damper (0% airflow)."""
        await self.coordinator.set_zone_airflow(self.zone_index, 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        zone_data = self.coordinator.data["zones"].get(self.zone_id)
        if zone_data is None:
            return {"zone_id": self.zone_id}
        return {
            "zone_id": self.zone_id,
            "zone_name": zone_data.get("name"),
            "airflow_setpoint": zone_data.get("airflow_setpoint"),
            "yourzone_enabled": zone_data.get("airflow_control_enabled"),
            "yourzone_locked": zone_data.get("airflow_control_locked"),
            "zone_max_position": zone_data.get("zone_max_position"),
            "zone_min_position": zone_data.get("zone_min_position"),
        }
