"""Support for ActronAir Neo climate devices."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_LOW,
    FAN_MEDIUM,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.helpers import entity_registry as er

from .const import (
    ADVANCE_FAN_MODES,
    ADVANCE_SERIES_MODELS,
    ADVANCED_FAN_MODE_ORDER,
    BASE_FAN_MODE_ORDER,
    BASE_FAN_MODES,
    MAX_TEMP,
    MIN_TEMP,
)
from .entity import ActronAirNeoEntity, ActronZoneEntity

if TYPE_CHECKING:
    from collections.abc import Mapping

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ActronDataCoordinator

PARALLEL_UPDATES = 0

_LOGGER = logging.getLogger(__name__)

BASE_HVAC_MODES = [
    HVACMode.OFF,
    HVACMode.COOL,
    HVACMode.HEAT,
    HVACMode.FAN_ONLY,
    HVACMode.AUTO,
]
FAN_MODES = [FAN_LOW, FAN_MEDIUM, FAN_HIGH, FAN_AUTO]

FAN_MODE_MAP = {
    FAN_LOW: "LOW",
    FAN_MEDIUM: "MED",
    FAN_HIGH: "HIGH",
    FAN_AUTO: "AUTO",
}

REVERSE_FAN_MODE_MAP = {v: k for k, v in FAN_MODE_MAP.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the ActronAir Neo climate device from a config entry."""
    coordinator: ActronDataCoordinator = config_entry.runtime_data
    entities: list[ClimateEntity] = [ActronClimate(coordinator)]

    entity_registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(entity_registry, config_entry.entry_id)

    if coordinator.enable_zone_control:
        entities.extend(
            ActronZoneClimate(coordinator, zone_id)
            for zone_id in coordinator.data["zones"]
        )
    else:
        # Remove any existing zone climate entities
        # Check both old and new unique_id formats
        zone_prefixes = (
            f"{coordinator.device_id}_zone_",
            f"{coordinator.device_id}_climate_zone_",
        )
        for entry in entries:
            if entry.unique_id.startswith(zone_prefixes):
                entity_registry.async_remove(entry.entity_id)

    async_add_entities(entities)


class ActronClimate(ActronAirNeoEntity, ClimateEntity):
    """Main climate entity with model-aware fan modes."""

    def __init__(self, coordinator: ActronDataCoordinator) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, "climate")
        # Main feature entity of the device: leave the entity name unset so it
        # takes the device name (has-entity-name rule) instead of duplicating
        # it ("ActronAir Neo ActronAir Neo").
        self._attr_name = None
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature supported by the unit."""
        try:
            main_data = self.coordinator.data["main"]
            if self.hvac_mode == HVACMode.HEAT:
                return float(main_data.get("min_temp_heat", MIN_TEMP))
            return float(main_data.get("min_temp_cool", MIN_TEMP))
        except (KeyError, TypeError, ValueError):
            return MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature supported by the unit."""
        try:
            main_data = self.coordinator.data["main"]
            if self.hvac_mode == HVACMode.HEAT:
                return float(main_data.get("max_temp_heat", MAX_TEMP))
            return float(main_data.get("max_temp_cool", MAX_TEMP))
        except (KeyError, TypeError, ValueError):
            return MAX_TEMP

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available HVAC modes for this unit."""
        try:
            main_data = self.coordinator.data["main"]
            if supported := main_data.get("supported_hvac_modes"):
                modes: list[HVACMode] = [HVACMode.OFF]
                for actron_mode in supported:
                    ha_mode = self._actron_to_ha_hvac_mode(actron_mode)
                    if ha_mode not in modes:
                        modes.append(ha_mode)
                if (
                    main_data.get("dry_mode_supported", False)
                    and HVACMode.DRY not in modes
                ):
                    modes.append(HVACMode.DRY)
                return modes
            modes = list(BASE_HVAC_MODES)
            if main_data.get("dry_mode_supported", False):
                modes.append(HVACMode.DRY)
        except (KeyError, TypeError):
            return list(BASE_HVAC_MODES)
        else:
            return modes

    @property
    def fan_modes(self) -> list[str]:
        """Return the list of available fan modes based on model capabilities."""
        try:
            supported_modes = self.coordinator.data["main"].get(
                "supported_fan_modes", BASE_FAN_MODES
            )
            # Compare as frozensets so list/frozenset sources match by membership.
            mode_set = frozenset(supported_modes)
            if mode_set == ADVANCE_FAN_MODES:
                supported_modes = ADVANCED_FAN_MODE_ORDER
            elif mode_set == BASE_FAN_MODES:
                supported_modes = BASE_FAN_MODE_ORDER

            # Map Actron modes to HA modes
            mode_map = {
                "LOW": FAN_LOW,
                "MED": FAN_MEDIUM,
                "HIGH": FAN_HIGH,
                "AUTO": FAN_AUTO,
            }

            available_modes = [
                ha_mode for mode in supported_modes if (ha_mode := mode_map.get(mode))
            ]

        except (KeyError, TypeError, ValueError):
            return [FAN_LOW, FAN_MEDIUM, FAN_HIGH]  # Safe fallback
        else:
            return available_modes or [FAN_LOW, FAN_MEDIUM, FAN_HIGH]

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.coordinator.data["main"]["indoor_temp"]

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if self.hvac_mode == HVACMode.COOL:
            return self.coordinator.data["main"]["temp_setpoint_cool"]
        if self.hvac_mode == HVACMode.HEAT:
            return self.coordinator.data["main"]["temp_setpoint_heat"]
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode."""
        if not self.coordinator.data["main"]["is_on"]:
            return HVACMode.OFF
        mode = self.coordinator.data["main"]["mode"]
        return self._actron_to_ha_hvac_mode(mode)

    @property
    def fan_mode(self) -> str | None:
        """Return the fan setting."""
        actron_fan_mode = self.coordinator.data["main"]["fan_mode"]
        # Remove +CONT suffix and get base mode
        base_mode = actron_fan_mode.split("+")[0] if actron_fan_mode else "LOW"
        base_mode = base_mode.split("-")[0] if "-" in base_mode else base_mode
        return REVERSE_FAN_MODE_MAP.get(base_mode, FAN_LOW)

    @property
    def current_humidity(self) -> float | None:
        """Return the current humidity."""
        return self.coordinator.data["main"]["indoor_humidity"]

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        is_cooling = self.hvac_mode in [HVACMode.COOL, HVACMode.AUTO]
        await self.coordinator.set_temperature(temperature, is_cooling=is_cooling)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if hvac_mode == self.hvac_mode:
            return  # No change needed

        if hvac_mode == HVACMode.OFF:
            await self.coordinator.turn_off()
        else:
            actron_mode = self._ha_to_actron_hvac_mode(hvac_mode)
            await self.coordinator.set_hvac_mode(actron_mode)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode with model-specific validation."""
        try:
            # Convert HA fan mode to Actron mode
            actron_mode = FAN_MODE_MAP.get(fan_mode, "LOW")

            # Get current continuous state
            current_fan_mode = self.coordinator.data["main"]["fan_mode"]
            continuous = "+CONT" in current_fan_mode

            # Check model support for AUTO mode
            model = self.coordinator.data["main"].get("model")
            if actron_mode == "AUTO" and model not in ADVANCE_SERIES_MODELS:
                _LOGGER.warning(
                    "Cannot set AUTO fan mode on model %s (Advance Series only)", model
                )
                return

            # Set fan mode while preserving continuous state
            await self.coordinator.set_fan_mode(actron_mode, continuous=continuous)

        except ValueError as err:
            # Handle specific error for unsupported AUTO mode
            if "AUTO fan mode is not supported" in str(err):
                return
            raise
        except Exception:
            raise

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if self.hvac_mode != HVACMode.OFF:
            return  # Already on

        await self.coordinator.turn_on()

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        if self.hvac_mode == HVACMode.OFF:
            return  # Already off

        await self.coordinator.turn_off()

    def _actron_to_ha_hvac_mode(self, mode: str) -> HVACMode:
        """Convert Actron HVAC mode to HA HVAC mode."""
        mode_map = {
            "AUTO": HVACMode.AUTO,
            "HEAT": HVACMode.HEAT,
            "COOL": HVACMode.COOL,
            "FAN": HVACMode.FAN_ONLY,
            "DRY": HVACMode.DRY,
            "OFF": HVACMode.OFF,
        }
        return mode_map.get(mode.upper(), HVACMode.OFF)

    def _ha_to_actron_hvac_mode(self, mode: HVACMode) -> str:
        """Convert HA HVAC mode to Actron HVAC mode."""
        mode_map = {
            HVACMode.AUTO: "AUTO",
            HVACMode.HEAT: "HEAT",
            HVACMode.COOL: "COOL",
            HVACMode.FAN_ONLY: "FAN",
            HVACMode.DRY: "DRY",
            HVACMode.OFF: "OFF",
        }
        return mode_map.get(mode, "OFF")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        actron_fan_mode = self.coordinator.data["main"]["fan_mode"]
        return {
            "away_mode": self.coordinator.data["main"]["away_mode"],
            "quiet_mode": self.coordinator.data["main"]["quiet_mode"],
            "continuous_fan": "+CONT" in actron_fan_mode if actron_fan_mode else False,
            "base_fan_mode": actron_fan_mode.split("+")[0]
            if actron_fan_mode
            else "LOW",
        }


class ActronZoneClimate(ActronZoneEntity, ClimateEntity):
    """Zone climate entity with enhanced control capabilities."""

    def __init__(self, coordinator: ActronDataCoordinator, zone_id: str) -> None:
        """Initialize the zone climate entity."""
        zone_name = coordinator.data["zones"][zone_id]["name"]
        super().__init__(coordinator, "climate", f"Zone {zone_name}")

        self.zone_id = zone_id

        # Load capabilities from coordinator data
        zone_data = coordinator.data["zones"][zone_id]
        capabilities = zone_data.get("capabilities")

        self._can_operate = capabilities.can_operate if capabilities else False
        self._exists = capabilities.exists if capabilities else False
        self._has_temp_control = (
            capabilities.has_temp_control if capabilities else False
        )
        self._has_separate_targets = (
            capabilities.has_separate_targets if capabilities else False
        )

        # Set up basic attributes
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        base_zone_modes: list[HVACMode] = [
            HVACMode.OFF,
            HVACMode.COOL,
            HVACMode.HEAT,
            HVACMode.AUTO,
        ]
        if coordinator.data["main"].get("dry_mode_supported", False):
            base_zone_modes.append(HVACMode.DRY)
        self._attr_hvac_modes = base_zone_modes
        self._attr_min_temp = MIN_TEMP
        self._attr_max_temp = MAX_TEMP

        # Initialize hvac_mode based on zone state
        self._attr_hvac_mode = (
            HVACMode.OFF
            if not self.coordinator.data["zones"][zone_id]["is_enabled"]
            else self._actron_to_ha_hvac_mode(self.coordinator.data["main"]["mode"])
        )

        # Set up features based on capabilities
        features = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

        if self._has_temp_control:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
            if self._has_separate_targets:
                features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE

        self._attr_supported_features = features

    @staticmethod
    def _calc_zone_min_bound(
        zone_min: float | None,
        master_target: float | None,
        variance_below: float | None,
        legacy_variance: float,
        abs_min: float,
    ) -> float:
        """
        Calculate zone minimum setpoint bound.

        Precedence: explicit zone minimum, then master target minus the
        signed NV_Limits variance, then master target minus the legacy
        variance, then the system minimum. A zero signed variance means
        "no constraint" (Neo controllers report 0.0) and falls through.
        """
        if zone_min is not None:
            return max(abs_min, float(zone_min))
        if isinstance(master_target, (int, float)):
            if variance_below:
                return max(abs_min, float(master_target) - abs(float(variance_below)))
            if legacy_variance > 0:
                return max(abs_min, float(master_target) - legacy_variance)
        return abs_min

    @staticmethod
    def _calc_zone_max_bound(
        zone_max: float | None,
        master_target: float | None,
        variance_above: float | None,
        legacy_variance: float,
        abs_max: float,
    ) -> float:
        """
        Calculate zone maximum setpoint bound.

        Precedence: explicit zone maximum, then master target plus the
        signed NV_Limits variance, then master target plus the legacy
        variance, then the system maximum. A zero signed variance means
        "no constraint" (Neo controllers report 0.0) and falls through.
        """
        if zone_max is not None:
            return min(abs_max, float(zone_max))
        if isinstance(master_target, (int, float)):
            if variance_above:
                return min(abs_max, float(master_target) + abs(float(variance_above)))
            if legacy_variance > 0:
                return min(abs_max, float(master_target) + legacy_variance)
        return abs_max

    def _get_zone_temp_bounds(self) -> tuple[float, float]:
        """
        Calculate zone min/max temperature bounds.

        Resolution order:
        1. The zone's own Min/Max setpoint published by the controller
           (MinHeatSetpoint/MaxHeatSetpoint in heat mode,
            MinCoolSetpoint/MaxCoolSetpoint otherwise).
        2. Master setpoint +/- NV_Limits signed variances
           (VarianceAboveMaster*/VarianceBelowMaster*). Only non-zero
           variances apply; zero means "no constraint".
        3. Master setpoint +/- legacy zone_temp_variance.
        Each side (min and max) resolves independently.
        Always clamped to system min/max limits.
        """
        try:
            main_data = self.coordinator.data["main"]
            zones_data: dict[str, Any] = self.coordinator.data.get("zones", {})
            zone_data: dict[str, Any] = zones_data.get(self.zone_id, {})
            mode = str(main_data.get("mode", "COOL")).upper()
            is_heat = mode == "HEAT" or (
                mode == "AUTO"
                and str(main_data.get("compressor_state", "")).upper() == "HEAT"
            )
            abs_min = float(
                main_data.get("min_temp_heat", MIN_TEMP)
                if is_heat
                else main_data.get("min_temp_cool", MIN_TEMP)
            )
            abs_max = float(
                main_data.get("max_temp_heat", MAX_TEMP)
                if is_heat
                else main_data.get("max_temp_cool", MAX_TEMP)
            )
            raw_master = (
                main_data.get("temp_setpoint_heat")
                if is_heat
                else main_data.get("temp_setpoint_cool")
            )
            master_target: float | None = (
                float(raw_master) if isinstance(raw_master, (int, float)) else None
            )
            legacy_variance = float(main_data.get("zone_temp_variance") or 0.0)

            raw_min = (
                zone_data.get("min_heat_setpoint")
                if is_heat
                else zone_data.get("min_cool_setpoint")
            )
            zone_min: float | None = (
                float(raw_min) if isinstance(raw_min, (int, float)) else None
            )
            raw_var_below = (
                main_data.get("variance_below_heat")
                if is_heat
                else main_data.get("variance_below_cool")
            )
            var_below: float | None = (
                float(raw_var_below)
                if isinstance(raw_var_below, (int, float))
                else None
            )
            min_bound = self._calc_zone_min_bound(
                zone_min, master_target, var_below, legacy_variance, abs_min
            )

            raw_max = (
                zone_data.get("max_heat_setpoint")
                if is_heat
                else zone_data.get("max_cool_setpoint")
            )
            zone_max: float | None = (
                float(raw_max) if isinstance(raw_max, (int, float)) else None
            )
            raw_var_above = (
                main_data.get("variance_above_heat")
                if is_heat
                else main_data.get("variance_above_cool")
            )
            var_above: float | None = (
                float(raw_var_above)
                if isinstance(raw_var_above, (int, float))
                else None
            )
            max_bound = self._calc_zone_max_bound(
                zone_max, master_target, var_above, legacy_variance, abs_max
            )
        except (KeyError, TypeError, ValueError):
            return MIN_TEMP, MAX_TEMP
        else:
            if min_bound > max_bound:
                return abs_min, abs_max
            return min_bound, max_bound

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature allowed for this zone."""
        return self._get_zone_temp_bounds()[0]

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature allowed for this zone."""
        return self._get_zone_temp_bounds()[1]

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return (
            super().available
            and self.coordinator.enable_zone_control
            and self._exists
            and self._can_operate
            and self.coordinator.data["zones"].get(self.zone_id) is not None
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode."""
        # Return OFF if zone is disabled
        if not self.coordinator.data["zones"][self.zone_id]["is_enabled"]:
            return HVACMode.OFF

        # Return OFF if main system is off (even if zone is enabled)
        if not self.coordinator.data["main"]["is_on"]:
            return HVACMode.OFF

        # Otherwise use main unit's mode
        mode = self.coordinator.data["main"]["mode"]
        return self._actron_to_ha_hvac_mode(mode)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self.coordinator.data["zones"][self.zone_id]["temp"]

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        if not self._has_temp_control:
            return None

        zone_data = self.coordinator.data["zones"][self.zone_id]
        main_mode = self.coordinator.data["main"]["mode"]

        try:
            temp = self._resolve_zone_target_temp(zone_data, main_mode)
        except (KeyError, TypeError, ValueError):
            return None
        else:
            return temp

    def _resolve_zone_target_temp(
        self, zone_data: Mapping[str, Any], main_mode: str
    ) -> float | None:
        """
        Resolve target temperature for a zone.

        Args:
            zone_data: Zone data from coordinator
            main_mode: Current HVAC mode

        Returns:
            Target temperature or None

        """
        if self._has_separate_targets:
            if main_mode == "COOL":
                return zone_data["temp_setpoint_cool"]
            if main_mode == "HEAT":
                return zone_data["temp_setpoint_heat"]
            if main_mode == "AUTO":
                compressor_state = self.coordinator.data["main"]["compressor_state"]
                if compressor_state == "COOL":
                    return zone_data["temp_setpoint_cool"]
                if compressor_state == "HEAT":
                    return zone_data["temp_setpoint_heat"]
            return None

        # Single target mode
        return zone_data.get("temp_setpoint_heat")

    @property
    def target_temperature_high(self) -> float | None:
        """Return the high target temperature."""
        if not (self._has_temp_control and self._has_separate_targets):
            return None

        return self.coordinator.data["zones"][self.zone_id]["temp_setpoint_cool"]

    @property
    def target_temperature_low(self) -> float | None:
        """Return the low target temperature."""
        if not (self._has_temp_control and self._has_separate_targets):
            return None

        return self.coordinator.data["zones"][self.zone_id]["temp_setpoint_heat"]

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        if not self.coordinator.enable_zone_control:
            return

        if hvac_mode == HVACMode.OFF:
            await self.coordinator.set_zone_state(self.zone_id, enable=False)
        else:
            await self.coordinator.set_zone_state(self.zone_id, enable=True)
            actron_mode = self._ha_to_actron_hvac_mode(hvac_mode)
            await self.coordinator.set_climate_mode(actron_mode)

        self._attr_hvac_mode = hvac_mode
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if not self._has_temp_control:
            return

        if not self.coordinator.enable_zone_control:
            return

        if self._has_separate_targets:
            # Handle separate heat/cool targets
            target_high = kwargs.get("target_temp_high")
            target_low = kwargs.get("target_temp_low")

            if target_high is not None or target_low is not None:
                await self.coordinator.set_zone_temperature(
                    self.zone_id,
                    target_cool=target_high,
                    target_heat=target_low,
                )

            else:
                # Handle single target when separate targets are supported
                temperature = kwargs.get(ATTR_TEMPERATURE)
                if temperature is not None:
                    await self.coordinator.set_zone_temperature(
                        self.zone_id,
                        target_cool=temperature,
                        target_heat=temperature,
                    )

        else:
            # Handle single target
            temperature = kwargs.get(ATTR_TEMPERATURE)
            if temperature is not None:
                await self.coordinator.set_zone_temperature(
                    self.zone_id,
                    temperature=temperature,
                )

    async def async_turn_on(self) -> None:
        """Turn the entity on."""
        if not self.coordinator.enable_zone_control:
            return

        await self.coordinator.set_zone_state(self.zone_id, enable=True)
        main_mode = self.coordinator.data["main"]["mode"]
        self._attr_hvac_mode = self._actron_to_ha_hvac_mode(main_mode)
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Turn the entity off."""
        if not self.coordinator.enable_zone_control:
            return

        await self.coordinator.set_zone_state(self.zone_id, enable=False)
        self._attr_hvac_mode = HVACMode.OFF
        self.async_write_ha_state()

    def _actron_to_ha_hvac_mode(self, mode: str) -> HVACMode:
        """Convert Actron HVAC mode to HA HVAC mode."""
        mode_map = {
            "AUTO": HVACMode.AUTO,
            "HEAT": HVACMode.HEAT,
            "COOL": HVACMode.COOL,
            "FAN": HVACMode.FAN_ONLY,
            "DRY": HVACMode.DRY,
            "OFF": HVACMode.OFF,
        }
        return mode_map.get(mode.upper(), HVACMode.OFF)

    def _ha_to_actron_hvac_mode(self, mode: HVACMode) -> str:
        """Convert HA HVAC mode to Actron HVAC mode."""
        mode_map = {
            HVACMode.AUTO: "AUTO",
            HVACMode.HEAT: "HEAT",
            HVACMode.COOL: "COOL",
            HVACMode.FAN_ONLY: "FAN",
            HVACMode.DRY: "DRY",
            HVACMode.OFF: "OFF",
        }
        return mode_map.get(mode, "OFF")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return zone specific attributes."""
        zone_data = self.coordinator.data["zones"][self.zone_id]
        data: dict[str, Any] = {
            "zone_name": zone_data["name"],
            "supports_temperature_control": self._has_temp_control,
            "supports_separate_targets": self._has_separate_targets,
            "current_humidity": zone_data["humidity"],
        }

        # Add capabilities (convert to dict for serialization)
        if capabilities := zone_data.get("capabilities"):
            data["capabilities"] = (
                capabilities.model_dump()
                if hasattr(capabilities, "model_dump")
                else capabilities
            )

        return data
