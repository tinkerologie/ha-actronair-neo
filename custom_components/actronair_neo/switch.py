"""Support for ActronAir Neo switches."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .dashboard import DashboardRole
from .entity import ActronAirNeoEntity, ActronZoneEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ActronDataCoordinator
    from .types import ScheduleEventData

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up ActronAir Neo switches from a config entry."""
    coordinator: ActronDataCoordinator = entry.runtime_data
    main_data = coordinator.data["main"]

    entities: list[SwitchEntity] = [
        ActronAwayModeSwitch(coordinator),
        ActronContinuousFanSwitch(coordinator),
        ActronAfterHoursSwitch(coordinator),
    ]

    # Only add quiet mode switch if the unit supports it
    if main_data.get("quiet_mode_supported", True):
        entities.append(ActronQuietModeSwitch(coordinator))

    # Only add turbo mode switch if the unit supports it
    if main_data.get("turbo_mode_supported", False):
        entities.append(ActronTurboModeSwitch(coordinator))

    # Add zone switches
    entities.extend(
        ActronZoneSwitch(coordinator, zone_id) for zone_id in coordinator.data["zones"]
    )

    async_add_entities(entities)
    _async_setup_schedule_switches(hass, entry, coordinator, async_add_entities)


@callback
def _async_setup_schedule_switches(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinator: ActronDataCoordinator,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add schedule switches and reconcile events for this config entry."""
    prefix = f"{coordinator.device_id}_switch_schedule_event_"
    added_ids: set[int] = set()
    scheduler_added = False
    checked_registry = False

    @callback
    def reconcile() -> None:
        nonlocal scheduler_added, checked_registry
        if not coordinator.last_update_success or not coordinator.data:
            return
        if (schedule := coordinator.data.get("schedule")) is None:
            return

        events = schedule["events"]
        removed_ids = added_ids - events.keys()
        if schedule["events_complete"] and (removed_ids or not checked_registry):
            registry = er.async_get(hass)
            if not checked_registry:
                # Look for events removed from the controller while HA was offline.
                current_unique_ids = {f"{prefix}{event_id}" for event_id in events}
                for registered in er.async_entries_for_config_entry(
                    registry, entry.entry_id
                ):
                    if (
                        registered.domain == "switch"
                        and registered.platform == DOMAIN
                        and registered.unique_id.startswith(prefix)
                        and registered.unique_id not in current_unique_ids
                    ):
                        registry.async_remove(registered.entity_id)
                checked_registry = True

            for event_id in removed_ids:
                entity_id = registry.async_get_entity_id(
                    "switch", DOMAIN, f"{prefix}{event_id}"
                )
                if entity_id is not None:
                    registry.async_remove(entity_id)
            added_ids.intersection_update(events)

        new_entities: list[SwitchEntity] = []
        if not scheduler_added:
            scheduler_added = True
            new_entities.append(ActronSchedulerSwitch(coordinator))
        for event_id in events:
            if event_id in added_ids:
                continue
            new_entities.append(ActronScheduleEventSwitch(coordinator, event_id))
            added_ids.add(event_id)
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(coordinator.async_add_listener(reconcile))
    reconcile()


class ActronSchedulerSwitch(ActronAirNeoEntity, SwitchEntity):
    """Switch for the controller scheduler."""

    _attr_translation_key = "scheduler"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the scheduler switch."""
        super().__init__(coordinator, "switch", "Scheduler")

    @property
    def available(self) -> bool:
        """Return whether the scheduler state is available."""
        return super().available and bool(
            self.coordinator.data and "schedule" in self.coordinator.data
        )

    @property
    def is_on(self) -> bool | None:
        """Return the reported scheduler state."""
        schedule = (
            self.coordinator.data.get("schedule") if self.coordinator.data else None
        )
        return schedule["enabled"] if schedule is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Enable the scheduler."""
        await self.coordinator.set_schedule_enabled(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable the scheduler."""
        await self.coordinator.set_schedule_enabled(enabled=False)


class ActronScheduleEventSwitch(ActronAirNeoEntity, SwitchEntity):
    """Switch for one controller schedule event."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator, event_id: int) -> None:
        """Initialize an event switch with an ID that survives renames."""
        super().__init__(coordinator, "switch", f"schedule_event_{event_id}")
        self._event_id = event_id
        self._attr_name = self._event_name(self._event)

    @property
    def _event(self) -> ScheduleEventData | None:
        """Return the current event, if present."""
        schedule = (
            self.coordinator.data.get("schedule") if self.coordinator.data else None
        )
        return schedule["events"].get(self._event_id) if schedule is not None else None

    def _event_name(self, event: ScheduleEventData | None) -> str:
        """Return the controller name or the fallback name."""
        return (event.get("name") if event else None) or f"Schedule {self._event_id}"

    @property
    def suggested_object_id(self) -> str:
        """Keep a different event with the same name from reusing this ID."""
        return f"schedule_event_{self._event_id}"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update the name before Home Assistant writes the switch state."""
        if (event := self._event) is not None:
            self._attr_name = self._event_name(event)
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        """Return whether the event state is available."""
        return super().available and self._event is not None

    @property
    def is_on(self) -> bool | None:
        """Return the reported event state."""
        return event["enabled"] if (event := self._event) is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the event settings that the controller reports."""
        if (event := self._event) is None:
            return None
        return {
            key: value
            for key, value in event.items()
            if key not in {"id", "position", "name", "enabled"}
        }

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Enable this event."""
        await self.coordinator.set_schedule_event_enabled(self._event_id, enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Disable this event."""
        await self.coordinator.set_schedule_event_enabled(self._event_id, enabled=False)


class ActronAwayModeSwitch(ActronAirNeoEntity, SwitchEntity):
    """Away mode switch."""

    dashboard_role = DashboardRole.AWAY_MODE

    _attr_translation_key = "away_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the away mode switch."""
        super().__init__(coordinator, "switch", "Away Mode")

    @property
    def is_on(self) -> bool:
        """Return true if away mode is on."""
        return self.coordinator.data["main"]["away_mode"]

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch on."""
        await self.coordinator.set_away_mode(state=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch off."""
        await self.coordinator.set_away_mode(state=False)


class ActronQuietModeSwitch(ActronAirNeoEntity, SwitchEntity):
    """Quiet mode switch."""

    dashboard_role = DashboardRole.QUIET_MODE

    _attr_translation_key = "quiet_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the quiet mode switch."""
        super().__init__(coordinator, "switch", "Quiet Mode")

    @property
    def is_on(self) -> bool:
        """Return true if quiet mode is on."""
        return self.coordinator.data["main"]["quiet_mode"]

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch on."""
        await self.coordinator.set_quiet_mode(state=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch off."""
        await self.coordinator.set_quiet_mode(state=False)


class ActronTurboModeSwitch(ActronAirNeoEntity, SwitchEntity):
    """Turbo mode switch (only created when hardware supports it)."""

    dashboard_role = DashboardRole.TURBO_MODE

    _attr_translation_key = "turbo_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the turbo mode switch."""
        super().__init__(coordinator, "switch", "Turbo Mode")

    @property
    def is_on(self) -> bool:
        """Return true if turbo mode is on."""
        return self.coordinator.data["main"].get("turbo_mode_enabled", False)

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn turbo mode on."""
        await self.coordinator.set_turbo_mode(state=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn turbo mode off."""
        await self.coordinator.set_turbo_mode(state=False)


class ActronAfterHoursSwitch(ActronAirNeoEntity, SwitchEntity):
    """After hours timer switch."""

    dashboard_role = DashboardRole.AFTER_HOURS

    _attr_translation_key = "after_hours"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the after hours switch."""
        super().__init__(coordinator, "switch", "After Hours")

    @property
    def is_on(self) -> bool:
        """Return true if after hours timer is active."""
        return self.coordinator.data["main"].get("after_hours_enabled", False)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "duration_minutes": self.coordinator.data["main"].get(
                "after_hours_duration", 120
            ),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn after hours timer on."""
        await self.coordinator.set_after_hours(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn after hours timer off."""
        await self.coordinator.set_after_hours(enabled=False)


class ActronContinuousFanSwitch(ActronAirNeoEntity, SwitchEntity):
    """Continuous fan mode switch."""

    dashboard_role = DashboardRole.CONTINUOUS_FAN

    _attr_translation_key = "continuous_fan"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the continuous fan mode switch."""
        super().__init__(coordinator, "switch", "Continuous Fan")

    @property
    def is_on(self) -> bool:
        """Return true if continuous fan mode is on."""
        current_mode = self.coordinator.data["main"].get("fan_mode", "")
        return "+CONT" in current_mode

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch on."""
        # Get current fan mode and strip any existing suffixes
        current_mode = self.coordinator.data["main"].get("fan_mode", "")
        base_mode = current_mode.split("+")[0] if "+" in current_mode else current_mode
        base_mode = base_mode.split("-")[0] if "-" in base_mode else base_mode

        # Validate base mode
        valid_modes = ["LOW", "MED", "HIGH", "AUTO"]
        if base_mode not in valid_modes:
            _LOGGER.warning("Invalid fan mode %s, using current base mode", base_mode)
            base_mode = self.coordinator.data["main"].get("base_fan_mode", "LOW")
            if base_mode not in valid_modes:
                _LOGGER.warning(
                    "Invalid base fan mode %s, defaulting to LOW", base_mode
                )
                base_mode = "LOW"

        # Set fan mode with continuous enabled
        await self.coordinator.set_fan_mode(base_mode, continuous=True)

        # Request refresh to update state
        await asyncio.sleep(1)  # Short delay for API processing
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the switch off."""
        # Get current fan mode and strip continuous suffix
        current_mode = self.coordinator.data["main"].get("fan_mode", "")
        base_mode = current_mode.split("+")[0] if "+" in current_mode else current_mode
        base_mode = base_mode.split("-")[0] if "-" in base_mode else base_mode

        # Validate base mode
        valid_modes = ["LOW", "MED", "HIGH", "AUTO"]
        if base_mode not in valid_modes:
            _LOGGER.warning("Invalid fan mode %s, using current base mode", base_mode)
            base_mode = self.coordinator.data["main"].get("base_fan_mode", "LOW")
            if base_mode not in valid_modes:
                _LOGGER.warning(
                    "Invalid base fan mode %s, defaulting to LOW", base_mode
                )
                base_mode = "LOW"

        # Set fan mode with continuous disabled
        await self.coordinator.set_fan_mode(base_mode, continuous=False)

        # Request refresh to update state
        await asyncio.sleep(1)  # Short delay for API processing
        await self.coordinator.async_request_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        current_mode = self.coordinator.data["main"].get("fan_mode", "")
        base_mode = current_mode.split("+")[0] if "+" in current_mode else current_mode

        return {
            "base_fan_mode": base_mode,
            "fan_mode": current_mode,
        }


class ActronZoneSwitch(ActronZoneEntity, SwitchEntity):
    """Zone switch."""

    dashboard_role = DashboardRole.ZONE_ENABLE

    _attr_translation_key = "zone"

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone switch."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(coordinator, "switch", f"Zone {zone_name}")
        self._attr_translation_placeholders = {"zone_name": zone_name}
        self.zone_id = zone_id
        self.zone_index = int(zone_id.split("_")[1]) - 1

    @property
    def is_on(self) -> bool:
        """Return true if the zone is enabled."""
        return self.coordinator.data["zones"][self.zone_id]["is_enabled"]

    async def async_turn_on(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the zone on."""
        await self.coordinator.set_zone_state(self.zone_index, enable=True)

    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        """Turn the zone off."""
        await self.coordinator.set_zone_state(self.zone_index, enable=False)
