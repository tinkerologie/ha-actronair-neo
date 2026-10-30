"""Number platform for ActronAir Neo integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.number import NumberEntity
from homeassistant.const import EntityCategory, UnitOfTime

from .dashboard import DashboardRole
from .entity import ActronAirNeoEntity

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
    """Set up ActronAir Neo number entities."""
    coordinator: ActronDataCoordinator = entry.runtime_data

    entities: list[NumberEntity] = [
        ActronAfterHoursDurationNumber(coordinator),
    ]

    async_add_entities(entities)


class ActronAfterHoursDurationNumber(ActronAirNeoEntity, NumberEntity):
    """Number entity for after hours timer duration."""

    dashboard_role = DashboardRole.AFTER_HOURS_DURATION

    _attr_native_min_value = 30
    _attr_native_max_value = 480
    _attr_native_step = 30
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_entity_category = EntityCategory.CONFIG
    _attr_translation_key = "after_hours_duration"

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the after hours duration number."""
        super().__init__(
            coordinator,
            "number",
            "After Hours Duration",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current after hours duration in minutes."""
        return self.coordinator.data["main"].get("after_hours_duration", 120)

    async def async_set_native_value(self, value: float) -> None:
        """Set new after hours duration."""
        await self.coordinator.set_after_hours_duration(int(value))
        await self.coordinator.async_request_refresh()
