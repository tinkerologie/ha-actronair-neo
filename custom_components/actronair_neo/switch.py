"""Support for ActronAir Neo switches."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory  # type: ignore[import-untyped]

from .entity import ActronAirNeoEntity, ActronZoneEntity

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ActronDataCoordinator

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
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


class ActronAwayModeSwitch(ActronAirNeoEntity, SwitchEntity):
    """Away mode switch."""

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
