"""Tests for the ActronAir Neo climate platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.climate.const import FAN_AUTO
from homeassistant.const import ATTR_TEMPERATURE

from custom_components.actronair_neo.climate import (
    ActronClimate,
    ActronZoneClimate,
    async_setup_entry,
)

from .conftest import MOCK_SERIAL, create_mock_coordinator


@pytest.fixture
def coordinator(mock_api, mock_status):
    """Create a coordinator for testing."""
    return create_mock_coordinator(MagicMock(), mock_api, mock_status)


@pytest.fixture
def system_climate(coordinator):
    """Create a system climate entity."""
    return ActronClimate(coordinator)


@pytest.fixture
def zone_climate(coordinator):
    """Create a zone climate entity."""
    climate = ActronZoneClimate(coordinator, "zone_1")
    # Mock async_write_ha_state for unit tests (no HA platform setup)
    climate.async_write_ha_state = MagicMock()
    return climate


# ── System Climate Tests ─────────────────────────────────────────


class TestActronClimate:
    """Tests for the system climate entity."""

    def test_unique_id(self, system_climate):
        """Test unique ID contains serial number."""
        assert MOCK_SERIAL in system_climate.unique_id

    def test_hvac_mode_cool(self, system_climate, mock_status):
        """Test HVAC mode when system is on in COOL mode."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        assert system_climate.hvac_mode == HVACMode.COOL

    def test_hvac_mode_heat(self, system_climate, mock_status):
        """Test HVAC mode when system is on in HEAT mode."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "HEAT"
        assert system_climate.hvac_mode == HVACMode.HEAT

    def test_hvac_mode_auto(self, system_climate, mock_status):
        """Test HVAC mode when system is on in AUTO mode."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "AUTO"
        assert system_climate.hvac_mode == HVACMode.AUTO

    def test_hvac_mode_fan(self, system_climate, mock_status):
        """Test HVAC mode when system is on in FAN mode."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "FAN"
        assert system_climate.hvac_mode == HVACMode.FAN_ONLY

    def test_hvac_mode_off(self, system_climate, mock_status):
        """Test HVAC mode when system is off."""
        mock_status["main"]["is_on"] = False
        assert system_climate.hvac_mode == HVACMode.OFF

    def test_current_temperature(self, system_climate, mock_status):
        """Test current temperature."""
        assert system_climate.current_temperature == 22.5

    def test_current_humidity(self, system_climate, mock_status):
        """Test current humidity."""
        assert system_climate.current_humidity == 45.0

    def test_target_temperature_cool(self, system_climate, mock_status):
        """Test target temperature in COOL mode."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        assert system_climate.target_temperature == 21.0

    def test_target_temperature_heat(self, system_climate, mock_status):
        """Test target temperature in HEAT mode."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "HEAT"
        assert system_climate.target_temperature == 24.0

    def test_target_temperature_off(self, system_climate, mock_status):
        """Test target temperature when system is off (no target)."""
        mock_status["main"]["is_on"] = False
        assert system_climate.target_temperature is None

    def test_fan_mode(self, system_climate, mock_status):
        """Test fan mode returns mapped value."""
        mock_status["main"]["fan_mode"] = "MED"
        assert system_climate.fan_mode == "medium"

    def test_fan_mode_with_cont(self, system_climate, mock_status):
        """Test fan mode strips +CONT suffix."""
        mock_status["main"]["fan_mode"] = "HIGH+CONT"
        assert system_climate.fan_mode == "high"

    def test_min_temp(self, system_climate):
        """Test minimum temperature."""
        assert system_climate.min_temp == 10

    def test_max_temp(self, system_climate):
        """Test maximum temperature."""
        assert system_climate.max_temp == 30

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off(self, system_climate, coordinator):
        """Test setting HVAC mode to OFF."""
        await system_climate.async_set_hvac_mode(HVACMode.OFF)
        coordinator.turn_off.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_cool(self, system_climate, coordinator, mock_status):
        """Test setting HVAC mode to COOL."""
        # Ensure current mode is different
        mock_status["main"]["is_on"] = False
        await system_climate.async_set_hvac_mode(HVACMode.COOL)
        coordinator.set_hvac_mode.assert_called_with("COOL")

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat(self, system_climate, coordinator, mock_status):
        """Test setting HVAC mode to HEAT."""
        mock_status["main"]["is_on"] = False
        await system_climate.async_set_hvac_mode(HVACMode.HEAT)
        coordinator.set_hvac_mode.assert_called_with("HEAT")

    @pytest.mark.asyncio
    async def test_set_temperature(self, system_climate, coordinator, mock_status):
        """Test setting target temperature."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        await system_climate.async_set_temperature(**{ATTR_TEMPERATURE: 24.0})
        coordinator.set_temperature.assert_called_once_with(24.0, is_cooling=True)

    @pytest.mark.asyncio
    async def test_set_temperature_no_value(self, system_climate, coordinator):
        """Test setting temperature without value does nothing."""
        await system_climate.async_set_temperature()
        coordinator.set_temperature.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode(self, system_climate, coordinator, mock_status):
        """Test setting fan mode."""
        mock_status["main"]["fan_mode"] = "LOW"
        mock_status["main"]["model"] = "NEO-12"
        await system_climate.async_set_fan_mode("low")
        coordinator.set_fan_mode.assert_called_once_with("LOW", continuous=False)

    @pytest.mark.asyncio
    async def test_turn_on(self, system_climate, coordinator, mock_status):
        """Test turning on the system."""
        mock_status["main"]["is_on"] = False
        await system_climate.async_turn_on()
        coordinator.turn_on.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_off(self, system_climate, coordinator, mock_status):
        """Test turning off the system."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        await system_climate.async_turn_off()
        coordinator.turn_off.assert_called_once()

    def test_supported_features(self, system_climate):
        """Test supported features."""
        features = system_climate.supported_features
        assert features & ClimateEntityFeature.TARGET_TEMPERATURE
        assert features & ClimateEntityFeature.FAN_MODE
        assert features & ClimateEntityFeature.TURN_ON
        assert features & ClimateEntityFeature.TURN_OFF

    def test_hvac_modes_list(self, system_climate):
        """Test HVAC modes list."""
        assert HVACMode.OFF in system_climate.hvac_modes
        assert HVACMode.COOL in system_climate.hvac_modes
        assert HVACMode.HEAT in system_climate.hvac_modes
        assert HVACMode.AUTO in system_climate.hvac_modes
        assert HVACMode.FAN_ONLY in system_climate.hvac_modes

    def test_fan_modes_list(self, system_climate):
        """Test fan modes list is not empty."""
        assert system_climate.fan_modes is not None
        assert len(system_climate.fan_modes) >= 3

    def test_fan_modes_fallback_on_bad_data(self, system_climate, coordinator):
        """Test fan modes fallback when coordinator data is invalid."""
        coordinator.data = None
        assert system_climate.fan_modes == ["low", "medium", "high"]

    def test_extra_state_attributes(self, system_climate, mock_status):
        """Test extra state attributes."""
        attrs = system_climate.extra_state_attributes
        assert attrs["away_mode"] is False
        assert attrs["quiet_mode"] is False

    @pytest.mark.asyncio
    async def test_set_hvac_mode_no_change(
        self, system_climate, coordinator, mock_status
    ):
        """Test setting same HVAC mode is a no-op."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        await system_climate.async_set_hvac_mode(HVACMode.COOL)
        coordinator.api.send_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode_auto_unsupported_returns(
        self, system_climate, coordinator, mock_status
    ):
        """Test AUTO fan mode is blocked for unsupported model."""
        mock_status["main"]["fan_mode"] = "LOW"
        mock_status["main"]["model"] = "Classic"
        await system_climate.async_set_fan_mode("auto")
        coordinator.set_fan_mode.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode_value_error_auto_unsupported(
        self, system_climate, coordinator, mock_status
    ):
        """Test specific AUTO unsupported ValueError is swallowed."""
        mock_status["main"]["model"] = "CRV17AS"
        coordinator.set_fan_mode = AsyncMock(
            side_effect=ValueError("AUTO fan mode is not supported")
        )
        await system_climate.async_set_fan_mode("auto")

    @pytest.mark.asyncio
    async def test_set_fan_mode_other_value_error_reraises(
        self, system_climate, coordinator, mock_status
    ):
        """Test non-AUTO ValueError in fan mode setter is re-raised."""
        mock_status["main"]["fan_mode"] = "LOW"
        mock_status["main"]["model"] = "NEO-12"
        coordinator.set_fan_mode = AsyncMock(side_effect=ValueError("different"))
        with pytest.raises(ValueError, match="different"):
            await system_climate.async_set_fan_mode("low")

    @pytest.mark.asyncio
    async def test_turn_on_turn_off_early_return(
        self, system_climate, coordinator, mock_status
    ):
        """Test turn_on/turn_off no-op when already in requested state."""
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        await system_climate.async_turn_on()
        coordinator.api.send_command.assert_not_called()

        mock_status["main"]["is_on"] = False
        await system_climate.async_turn_off()
        coordinator.api.send_command.assert_not_called()

    def test_hvac_mapping_fallbacks(self, system_climate):
        """Test HVAC conversion fallback paths."""
        assert system_climate._actron_to_ha_hvac_mode("bad") == HVACMode.OFF
        assert system_climate._ha_to_actron_hvac_mode("bad") == "OFF"


class TestClimateSetupEntry:
    """Tests for climate async_setup_entry."""

    @pytest.mark.asyncio
    async def test_setup_removes_zone_entities_when_disabled(self, coordinator):
        """Test setup removes existing zone climates when zone control disabled."""
        coordinator.enable_zone_control = False
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        mock_entry.entry_id = "entry"
        entity_registry = MagicMock()
        entity_entry = MagicMock()
        entity_entry.unique_id = f"{coordinator.device_id}_zone_1_old"
        entity_entry.entity_id = "climate.old_zone"

        add_entities = MagicMock()
        with (
            patch(
                "custom_components.actronair_neo.climate.er.async_get",
                return_value=entity_registry,
            ),
            patch(
                "custom_components.actronair_neo.climate.er.async_entries_for_config_entry",
                return_value=[entity_entry],
            ),
        ):
            await async_setup_entry(MagicMock(), mock_entry, add_entities)

        entity_registry.async_remove.assert_called_once_with("climate.old_zone")
        args = add_entities.call_args.args[0]
        assert any(isinstance(entity, ActronClimate) for entity in args)

    @pytest.mark.asyncio
    async def test_setup_adds_zone_entities_when_enabled(self, coordinator):
        """Test setup includes zone climates when zone control is enabled."""
        coordinator.enable_zone_control = True
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        mock_entry.entry_id = "entry"
        add_entities = MagicMock()
        with (
            patch(
                "custom_components.actronair_neo.climate.er.async_get",
                return_value=MagicMock(),
            ),
            patch(
                "custom_components.actronair_neo.climate.er.async_entries_for_config_entry",
                return_value=[],
            ),
        ):
            await async_setup_entry(MagicMock(), mock_entry, add_entities)
        added = add_entities.call_args.args[0]
        assert any(isinstance(entity, ActronZoneClimate) for entity in added)


# ── Zone Climate Tests ───────────────────────────────────────────


class TestActronZoneClimate:
    """Tests for the zone climate entity."""

    def test_unique_id(self, zone_climate):
        """Test unique ID includes serial and zone info."""
        assert MOCK_SERIAL in zone_climate.unique_id

    def test_hvac_mode_active(self, zone_climate, mock_status):
        """Test HVAC mode when zone is enabled reflects system mode."""
        mock_status["zones"]["zone_1"]["is_enabled"] = True
        mock_status["main"]["is_on"] = True
        mock_status["main"]["mode"] = "COOL"
        assert zone_climate.hvac_mode == HVACMode.COOL

    def test_hvac_mode_disabled(self, zone_climate, mock_status):
        """Test HVAC mode when zone is disabled."""
        mock_status["zones"]["zone_1"]["is_enabled"] = False
        assert zone_climate.hvac_mode == HVACMode.OFF

    def test_hvac_mode_system_off(self, zone_climate, mock_status):
        """Test HVAC mode when main system is off."""
        mock_status["zones"]["zone_1"]["is_enabled"] = True
        mock_status["main"]["is_on"] = False
        assert zone_climate.hvac_mode == HVACMode.OFF

    def test_current_temperature(self, zone_climate, mock_status):
        """Test current temperature from zone data."""
        assert zone_climate.current_temperature == 22.0

    def test_current_temperature_matches_zone(self, zone_climate, mock_status):
        """Test temperature updates with data."""
        mock_status["zones"]["zone_1"]["temp"] = 25.5
        assert zone_climate.current_temperature == 25.5

    def test_target_temperature_cool(self, zone_climate, mock_status):
        """Test target temperature in COOL mode."""
        mock_status["main"]["mode"] = "COOL"
        # Zone has temp_setpoint_cool = 24.0 from _create_mock_zone
        assert zone_climate.target_temperature is not None

    def test_zone_target_temps_with_separate_targets(self, coordinator, mock_status):
        """Test zone high/low targets when separate targets are enabled."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_separate_targets": True}
        )
        climate = ActronZoneClimate(coordinator, "zone_1")
        assert climate.target_temperature_high == 24.0
        assert climate.target_temperature_low == 22.0

    def test_zone_target_temperature_auto_compressor_state(
        self, coordinator, mock_status
    ):
        """Test AUTO target resolution from compressor state."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_separate_targets": True}
        )
        mock_status["main"]["mode"] = "AUTO"
        mock_status["main"]["compressor_state"] = "HEAT"
        climate = ActronZoneClimate(coordinator, "zone_1")
        assert climate.target_temperature == 22.0

    def test_zone_target_temperature_auto_cool_state(self, coordinator, mock_status):
        """Test AUTO target resolution when compressor state is COOL."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_separate_targets": True}
        )
        mock_status["main"]["mode"] = "AUTO"
        mock_status["main"]["compressor_state"] = "COOL"
        climate = ActronZoneClimate(coordinator, "zone_1")
        assert climate.target_temperature == 24.0

    def test_zone_target_temperature_no_temp_control(self, coordinator, mock_status):
        """Test target temperature returns None when temp control unsupported."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_temp_control": False}
        )
        climate = ActronZoneClimate(coordinator, "zone_1")
        assert climate.target_temperature is None

    def test_zone_target_temperature_exception_path(self, coordinator, mock_status):
        """Test target temperature handles key/type errors gracefully."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_separate_targets": True}
        )
        del mock_status["zones"]["zone_1"]["temp_setpoint_cool"]
        mock_status["main"]["mode"] = "COOL"
        climate = ActronZoneClimate(coordinator, "zone_1")
        assert climate.target_temperature is None

    def test_resolve_zone_target_temp_heat_and_auto_unknown(self, coordinator):
        """Test _resolve_zone_target_temp heat branch and auto unknown fallback."""
        climate = ActronZoneClimate(coordinator, "zone_1")
        climate._has_separate_targets = True
        zone_data = {"temp_setpoint_cool": 24.0, "temp_setpoint_heat": 21.0}
        assert climate._resolve_zone_target_temp(zone_data, "HEAT") == 21.0
        coordinator.data["main"]["compressor_state"] = "IDLE"
        assert climate._resolve_zone_target_temp(zone_data, "AUTO") is None

    def test_target_high_low_none_when_no_separate_targets(self, zone_climate):
        """Test target high/low are None without separate-target support."""
        assert zone_climate.target_temperature_high is None
        assert zone_climate.target_temperature_low is None

    def test_min_temp(self, zone_climate):
        """Test minimum temperature."""
        assert zone_climate.min_temp == 10

    def test_max_temp(self, zone_climate):
        """Test maximum temperature."""
        assert zone_climate.max_temp == 30

    def test_zone_bounds_all_zero_nv_limits_fall_through(
        self, zone_climate, mock_status
    ):
        """Test all-zero NV_Limits variances fall through to zone_temp_variance."""
        mock_status["main"].update(
            {
                "mode": "COOL",
                "temp_setpoint_cool": 24.0,
                "min_temp_cool": 18.0,
                "max_temp_cool": 28.0,
                "variance_below_cool": 0.0,
                "variance_above_cool": 0.0,
                "variance_below_heat": 0.0,
                "variance_above_heat": 0.0,
                "zone_temp_variance": 4.0,
            }
        )
        assert zone_climate.min_temp == 20.0
        assert zone_climate.max_temp == 28.0

    @pytest.mark.parametrize(
        ("main_overrides", "zone_overrides", "expected"),
        [
            pytest.param(
                {"variance_below_cool": 1.0, "variance_above_cool": 2.0},
                {},
                (23.0, 26.0),
                id="non_zero_signed_variance_beats_legacy",
            ),
            pytest.param(
                {"variance_below_cool": -1.0, "variance_above_cool": -2.0},
                {},
                (23.0, 26.0),
                id="negative_signed_variance_uses_magnitude",
            ),
            pytest.param(
                {"variance_below_cool": 0.0, "variance_above_cool": 2.0},
                {},
                (20.0, 26.0),
                id="mixed_zero_and_non_zero_sides",
            ),
            pytest.param(
                {"variance_below_cool": -0.0, "variance_above_cool": 0.0},
                {},
                (20.0, 28.0),
                id="negative_zero_treated_as_zero",
            ),
            pytest.param(
                {"variance_below_cool": None, "variance_above_cool": None},
                {},
                (20.0, 28.0),
                id="missing_signed_variance_uses_legacy",
            ),
            pytest.param(
                {
                    "variance_below_cool": 0.0,
                    "variance_above_cool": 0.0,
                    "zone_temp_variance": 0.0,
                },
                {},
                (18.0, 28.0),
                id="all_zero_falls_through_to_system_limits",
            ),
            pytest.param(
                {"variance_below_cool": 1.0, "variance_above_cool": 2.0},
                {"min_cool_setpoint": 19.0, "max_cool_setpoint": 27.0},
                (19.0, 27.0),
                id="explicit_zone_limits_take_priority",
            ),
            pytest.param(
                {"variance_below_cool": 10.0, "variance_above_cool": 10.0},
                {},
                (18.0, 28.0),
                id="clamped_to_system_limits",
            ),
            pytest.param(
                {"mode": "HEAT"},
                {},
                (18.0, 26.0),
                id="heat_mode_uses_heat_fields",
            ),
            pytest.param(
                {"mode": "AUTO", "compressor_state": "HEAT"},
                {},
                (18.0, 26.0),
                id="auto_heating_uses_heat_fields",
            ),
        ],
    )
    def test_zone_bounds_resolution(
        self, zone_climate, mock_status, main_overrides, zone_overrides, expected
    ):
        """Test zone bound precedence, zero-variance fall-through and clamping."""
        # Cool and heat fields differ so the mode-specific path is observable:
        # cool gives 20/28 via the legacy variance, heat gives 18/26.
        mock_status["main"].update(
            {
                "mode": "COOL",
                "compressor_state": "COOL",
                "temp_setpoint_cool": 24.0,
                "temp_setpoint_heat": 22.0,
                "min_temp_cool": 18.0,
                "max_temp_cool": 28.0,
                "min_temp_heat": 16.0,
                "max_temp_heat": 30.0,
                "variance_below_cool": 0.0,
                "variance_above_cool": 0.0,
                "variance_below_heat": 0.0,
                "variance_above_heat": 0.0,
                "zone_temp_variance": 4.0,
                **main_overrides,
            }
        )
        mock_status["zones"]["zone_1"].update(zone_overrides)
        assert (zone_climate.min_temp, zone_climate.max_temp) == expected

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off(self, zone_climate, coordinator):
        """Test disabling zone via HVAC mode."""
        coordinator.enable_zone_control = True
        await zone_climate.async_set_hvac_mode(HVACMode.OFF)
        coordinator.set_zone_state.assert_called_with("zone_1", enable=False)

    @pytest.mark.asyncio
    async def test_set_hvac_mode_on(self, zone_climate, coordinator):
        """Test enabling zone via HVAC mode."""
        coordinator.enable_zone_control = True
        await zone_climate.async_set_hvac_mode(HVACMode.AUTO)
        coordinator.set_zone_state.assert_called_with("zone_1", enable=True)
        coordinator.set_climate_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_turn_on(self, zone_climate, coordinator):
        """Test enabling zone via turn on."""
        coordinator.enable_zone_control = True
        await zone_climate.async_turn_on()
        coordinator.set_zone_state.assert_called_with("zone_1", enable=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, zone_climate, coordinator):
        """Test disabling zone via turn off."""
        coordinator.enable_zone_control = True
        await zone_climate.async_turn_off()
        coordinator.set_zone_state.assert_called_with("zone_1", enable=False)

    @pytest.mark.asyncio
    async def test_set_temperature(self, zone_climate, coordinator):
        """Test setting zone temperature."""
        coordinator.enable_zone_control = True
        await zone_climate.async_set_temperature(**{ATTR_TEMPERATURE: 23.0})
        coordinator.set_zone_temperature.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_temperature_separate_targets(self, coordinator, mock_status):
        """Test setting separate high/low target temperatures."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_separate_targets": True}
        )
        climate = ActronZoneClimate(coordinator, "zone_1")
        climate.async_write_ha_state = MagicMock()
        coordinator.enable_zone_control = True
        await climate.async_set_temperature(target_temp_high=24.0, target_temp_low=21.0)
        coordinator.set_zone_temperature.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_temperature_out_of_range_delegates_to_coordinator(
        self, zone_climate, coordinator
    ):
        """Test out-of-range temp is delegated to coordinator."""
        coordinator.enable_zone_control = True
        await zone_climate.async_set_temperature(**{ATTR_TEMPERATURE: 99.0})
        # Validation is now handled by the coordinator, not the entity
        coordinator.set_zone_temperature.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_temperature_returns_when_no_temp_control(
        self, coordinator, mock_status
    ):
        """Test set_temperature exits when zone lacks temp control capability."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_temp_control": False}
        )
        climate = ActronZoneClimate(coordinator, "zone_1")
        coordinator.enable_zone_control = True
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 23.0})
        coordinator.set_zone_temperature.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_temperature_returns_when_zone_control_disabled(
        self, zone_climate, coordinator
    ):
        """Test set_temperature exits when zone control is disabled."""
        coordinator.enable_zone_control = False
        await zone_climate.async_set_temperature(**{ATTR_TEMPERATURE: 23.0})
        coordinator.set_zone_temperature.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_temperature_separate_targets_single_temp_path(
        self, coordinator, mock_status
    ):
        """Test separate-target zones accept single ATTR_TEMPERATURE fallback path."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"has_separate_targets": True}
        )
        climate = ActronZoneClimate(coordinator, "zone_1")
        coordinator.enable_zone_control = True
        await climate.async_set_temperature(**{ATTR_TEMPERATURE: 22.0})
        coordinator.set_zone_temperature.assert_called_once()

    @pytest.mark.asyncio
    async def test_zone_methods_return_when_zone_control_disabled(
        self, zone_climate, coordinator
    ):
        """Test zone on/off and set_hvac_mode guard when zone control disabled."""
        coordinator.enable_zone_control = False
        await zone_climate.async_set_hvac_mode(HVACMode.HEAT)
        await zone_climate.async_turn_on()
        await zone_climate.async_turn_off()
        coordinator.set_zone_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode_generic_exception_propagates(
        self, system_climate, coordinator, mock_status
    ):
        """Test generic exception in fan mode setter is re-raised."""
        mock_status["main"]["fan_mode"] = "LOW"
        mock_status["main"]["model"] = "NEO-12"
        coordinator.set_fan_mode = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await system_climate.async_set_fan_mode("low")

    def test_fan_modes_advance_and_base_order(self, system_climate, mock_status):
        """Test fan_modes ordering branches for advance/base models."""
        mock_status["main"]["supported_fan_modes"] = frozenset(
            {
                "LOW",
                "MED",
                "HIGH",
                "AUTO",
            }
        )
        assert FAN_AUTO in system_climate.fan_modes

        mock_status["main"]["supported_fan_modes"] = frozenset({"LOW", "MED", "HIGH"})
        assert FAN_AUTO not in system_climate.fan_modes

    def test_zone_available_false_paths(self, coordinator, mock_status):
        """Test zone availability false when zone control disabled/non-operable."""
        cap = mock_status["zones"]["zone_1"]["capabilities"]
        mock_status["zones"]["zone_1"]["capabilities"] = cap.model_copy(
            update={"exists": False, "can_operate": False}
        )
        climate = ActronZoneClimate(coordinator, "zone_1")
        coordinator.enable_zone_control = False
        assert climate.available is False

    def test_zone_hvac_modes(self, zone_climate):
        """Test zone supports OFF, COOL, HEAT, and AUTO."""
        assert HVACMode.OFF in zone_climate.hvac_modes
        assert HVACMode.COOL in zone_climate.hvac_modes
        assert HVACMode.HEAT in zone_climate.hvac_modes
        assert HVACMode.AUTO in zone_climate.hvac_modes

    def test_zone_supported_features(self, zone_climate):
        """Test zone supported features."""
        features = zone_climate.supported_features
        assert features & ClimateEntityFeature.TURN_ON
        assert features & ClimateEntityFeature.TURN_OFF

    def test_extra_state_attributes(self, zone_climate, mock_status):
        """Test zone extra state attributes."""
        attrs = zone_climate.extra_state_attributes
        assert attrs["zone_name"] == "Living Room"
        assert "supports_temperature_control" in attrs
