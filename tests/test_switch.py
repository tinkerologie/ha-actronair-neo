"""Tests for the ActronAir Neo switch platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.actronair_neo.api.push.models import RealtimeConnectionDetails
from custom_components.actronair_neo.const import DOMAIN
from custom_components.actronair_neo.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.actronair_neo.switch import (
    ActronAfterHoursSwitch,
    ActronAwayModeSwitch,
    ActronContinuousFanSwitch,
    ActronQuietModeSwitch,
    ActronTurboModeSwitch,
    ActronZoneSwitch,
    async_setup_entry,
)

from .conftest import MOCK_SERIAL, create_mock_coordinator

_SCHEDULE_EVENT = {
    "ID": 0,
    "Enabled": False,
    "Name": "Daytime cooling",
    "StartTime": "T06:00",
    "EndTime": "T22:00",
    "DaysOfOperation": [True, False],
    "EnabledZones": [True, False],
    "Mode": "COOL",
    "FanMode": "AUTO",
    "TemperatureSetpoint_Cool_oC": 23,
    "TemperatureSetpoint_Heat_oC": 24,
}


@pytest.fixture
def coordinator(mock_api, mock_status):
    """Create a coordinator for testing."""
    return create_mock_coordinator(MagicMock(), mock_api, mock_status)


@pytest.fixture
def coordinator_zones(mock_api, mock_status):
    """Create a coordinator with zone control enabled."""
    return create_mock_coordinator(
        MagicMock(), mock_api, mock_status, enable_zone_control=True
    )


# ── Away Mode Switch Tests ──────────────────────────────────────


class TestAwayModeSwitch:
    """Tests for the ActronAwayModeSwitch entity."""

    def test_is_on_false(self, coordinator):
        """Test away mode switch when off."""
        switch = ActronAwayModeSwitch(coordinator)
        assert switch.is_on is False

    def test_is_on_true(self, coordinator, mock_status):
        """Test away mode switch when on."""
        mock_status["main"]["away_mode"] = True
        switch = ActronAwayModeSwitch(coordinator)
        assert switch.is_on is True

    def test_unique_id(self, coordinator):
        """Test unique ID generation."""
        switch = ActronAwayModeSwitch(coordinator)
        assert MOCK_SERIAL in switch.unique_id

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator):
        """Test turning on away mode."""
        switch = ActronAwayModeSwitch(coordinator)
        await switch.async_turn_on()
        coordinator.set_away_mode.assert_called_once_with(state=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator):
        """Test turning off away mode."""
        switch = ActronAwayModeSwitch(coordinator)
        await switch.async_turn_off()
        coordinator.set_away_mode.assert_called_once_with(state=False)


# ── Quiet Mode Switch Tests ─────────────────────────────────────


class TestQuietModeSwitch:
    """Tests for the ActronQuietModeSwitch entity."""

    def test_is_on_false(self, coordinator):
        """Test quiet mode switch when off."""
        switch = ActronQuietModeSwitch(coordinator)
        assert switch.is_on is False

    def test_is_on_true(self, coordinator, mock_status):
        """Test quiet mode switch when on."""
        mock_status["main"]["quiet_mode"] = True
        switch = ActronQuietModeSwitch(coordinator)
        assert switch.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator):
        """Test turning on quiet mode."""
        switch = ActronQuietModeSwitch(coordinator)
        await switch.async_turn_on()
        coordinator.set_quiet_mode.assert_called_once_with(state=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator):
        """Test turning off quiet mode."""
        switch = ActronQuietModeSwitch(coordinator)
        await switch.async_turn_off()
        coordinator.set_quiet_mode.assert_called_once_with(state=False)


# ── Continuous Fan Switch Tests ──────────────────────────────────


class TestContinuousFanSwitch:
    """Tests for the ActronContinuousFanSwitch entity."""

    def test_is_on_false(self, coordinator):
        """Test continuous fan switch when off."""
        switch = ActronContinuousFanSwitch(coordinator)
        assert switch.is_on is False

    def test_is_on_true(self, coordinator, mock_status):
        """Test continuous fan switch when on."""
        mock_status["main"]["fan_mode"] = "LOW+CONT"
        switch = ActronContinuousFanSwitch(coordinator)
        assert switch.is_on is True

    def test_extra_state_attributes(self, coordinator, mock_status):
        """Test extra state attributes include fan mode info."""
        mock_status["main"]["fan_mode"] = "MED+CONT"
        switch = ActronContinuousFanSwitch(coordinator)
        attrs = switch.extra_state_attributes
        assert attrs["base_fan_mode"] == "MED"
        assert attrs["fan_mode"] == "MED+CONT"

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator, mock_status):
        """Test turning on continuous fan."""
        mock_status["main"]["fan_mode"] = "LOW"
        switch = ActronContinuousFanSwitch(coordinator)
        await switch.async_turn_on()
        coordinator.set_fan_mode.assert_called_once_with("LOW", continuous=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator, mock_status):
        """Test turning off continuous fan."""
        mock_status["main"]["fan_mode"] = "LOW+CONT"
        switch = ActronContinuousFanSwitch(coordinator)
        await switch.async_turn_off()
        coordinator.set_fan_mode.assert_called_once_with("LOW", continuous=False)

    @pytest.mark.asyncio
    async def test_turn_on_invalid_mode_fallbacks(self, coordinator, mock_status):
        """Test invalid current and base fan mode fallback to LOW."""
        mock_status["main"]["fan_mode"] = "BAD-MODE"
        mock_status["main"]["base_fan_mode"] = "INVALID"
        switch = ActronContinuousFanSwitch(coordinator)
        with patch(
            "custom_components.actronair_neo.switch.asyncio.sleep", new=AsyncMock()
        ):
            await switch.async_turn_on()
        coordinator.set_fan_mode.assert_called_once_with("LOW", continuous=True)

    @pytest.mark.asyncio
    async def test_turn_off_invalid_mode_fallbacks(self, coordinator, mock_status):
        """Test invalid current/base mode fallback during turn off."""
        mock_status["main"]["fan_mode"] = "UNKNOWN+CONT"
        mock_status["main"]["base_fan_mode"] = "INVALID"
        switch = ActronContinuousFanSwitch(coordinator)
        with patch(
            "custom_components.actronair_neo.switch.asyncio.sleep", new=AsyncMock()
        ):
            await switch.async_turn_off()
        coordinator.set_fan_mode.assert_called_once_with("LOW", continuous=False)


# ── Zone Switch Tests ────────────────────────────────────────────


class TestZoneSwitch:
    """Tests for the ActronZoneSwitch entity."""

    def test_is_on_enabled(self, coordinator_zones):
        """Test zone switch when zone is enabled."""
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        assert switch.is_on is True

    def test_is_on_disabled(self, coordinator_zones, mock_status):
        """Test zone switch when zone is disabled."""
        mock_status["zones"]["zone_1"]["is_enabled"] = False
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        assert switch.is_on is False

    def test_available_when_zone_present(self, coordinator_zones):
        """Zone switch is available while its zone exists in data."""
        coordinator_zones.last_update_success = True
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        assert switch.available is True

    def test_unavailable_when_zone_missing(self, coordinator_zones, mock_status):
        """A dropped zone renders the switch unavailable instead of raising."""
        coordinator_zones.last_update_success = True
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        # Simulate a transient/partial update that dropped the zone.
        mock_status["zones"].pop("zone_1")
        assert switch.available is False

    def test_unique_id(self, coordinator_zones):
        """Test unique ID includes serial and zone info."""
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        assert MOCK_SERIAL in switch.unique_id

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator_zones):
        """Test enabling a zone."""
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        await switch.async_turn_on()
        # zone_1 → zone_index = 0
        coordinator_zones.set_zone_state.assert_called_once_with(0, enable=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator_zones):
        """Test disabling a zone."""
        switch = ActronZoneSwitch(coordinator_zones, "zone_1")
        await switch.async_turn_off()
        coordinator_zones.set_zone_state.assert_called_once_with(0, enable=False)

    def test_second_zone(self, coordinator_zones):
        """Test switch for second zone."""
        switch = ActronZoneSwitch(coordinator_zones, "zone_2")
        assert MOCK_SERIAL in switch.unique_id

    @pytest.mark.asyncio
    async def test_second_zone_index(self, coordinator_zones):
        """Test second zone maps to index 1."""
        switch = ActronZoneSwitch(coordinator_zones, "zone_2")
        await switch.async_turn_on()
        # zone_2 → zone_index = 1
        coordinator_zones.set_zone_state.assert_called_once_with(1, enable=True)


# ── Turbo Mode Switch Tests ─────────────────────────────────────


class TestTurboModeSwitch:
    def test_is_on_false(self, coordinator):
        switch = ActronTurboModeSwitch(coordinator)
        assert switch.is_on is False

    def test_is_on_true(self, coordinator, mock_status):
        mock_status["main"]["turbo_mode_enabled"] = True
        switch = ActronTurboModeSwitch(coordinator)
        assert switch.is_on is True

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator):
        coordinator.set_turbo_mode = AsyncMock()
        switch = ActronTurboModeSwitch(coordinator)
        await switch.async_turn_on()
        coordinator.set_turbo_mode.assert_called_once_with(state=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator):
        coordinator.set_turbo_mode = AsyncMock()
        switch = ActronTurboModeSwitch(coordinator)
        await switch.async_turn_off()
        coordinator.set_turbo_mode.assert_called_once_with(state=False)


# ── After Hours Switch Tests ─────────────────────────────────────


class TestAfterHoursSwitch:
    def test_is_on_false(self, coordinator):
        switch = ActronAfterHoursSwitch(coordinator)
        assert switch.is_on is False

    def test_is_on_true(self, coordinator, mock_status):
        mock_status["main"]["after_hours_enabled"] = True
        switch = ActronAfterHoursSwitch(coordinator)
        assert switch.is_on is True

    def test_extra_state_attributes(self, coordinator, mock_status):
        mock_status["main"]["after_hours_duration"] = 60
        switch = ActronAfterHoursSwitch(coordinator)
        attrs = switch.extra_state_attributes
        assert attrs["duration_minutes"] == 60

    @pytest.mark.asyncio
    async def test_turn_on(self, coordinator):
        coordinator.set_after_hours = AsyncMock()
        switch = ActronAfterHoursSwitch(coordinator)
        await switch.async_turn_on()
        coordinator.set_after_hours.assert_called_once_with(enabled=True)

    @pytest.mark.asyncio
    async def test_turn_off(self, coordinator):
        coordinator.set_after_hours = AsyncMock()
        switch = ActronAfterHoursSwitch(coordinator)
        await switch.async_turn_off()
        coordinator.set_after_hours.assert_called_once_with(enabled=False)


# ── async_setup_entry Tests ──────────────────────────────────────


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_setup_creates_entities(self, coordinator, mock_status):
        mock_status["main"]["quiet_mode_supported"] = True
        mock_status["main"]["turbo_mode_supported"] = True
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        added: list = []
        await async_setup_entry(MagicMock(), mock_entry, added.extend)
        # away + continuous_fan + after_hours + quiet + turbo + 2 zones = 7
        assert len(added) == 7

    @pytest.mark.asyncio
    async def test_setup_without_optional(self, coordinator, mock_status):
        mock_status["main"]["quiet_mode_supported"] = False
        mock_status["main"]["turbo_mode_supported"] = False
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        added: list = []
        await async_setup_entry(MagicMock(), mock_entry, added.extend)
        # away + continuous_fan + after_hours + 2 zones = 5
        assert len(added) == 5


@pytest.fixture
def load_schedules(hass, mock_config_entry, mock_api, mock_ac_status_response):
    """Load the real switch platform with a fake REST client and push transport."""
    mock_api.get_realtime_connection_details.return_value = RealtimeConnectionDetails(
        endpoint="broker", port=8883, protocol="ssl", user_id="test-user"
    )
    mock_api.get_ac_status.return_value = mock_ac_status_response
    mock_api.set_schedule_enabled = AsyncMock()
    mock_api.set_schedule_event_enabled = AsyncMock()
    transport = MagicMock(last_heartbeat=None, start=AsyncMock(), stop=AsyncMock())

    async def load(schedule=None):
        if schedule is not None:
            mock_ac_status_response["lastKnownState"]["NV_Schedule"] = schedule
        with (
            patch(
                "custom_components.actronair_neo._create_api_client",
                return_value=mock_api,
            ),
            patch(
                "custom_components.actronair_neo.coordinator.create_push_transport",
                return_value=transport,
            ) as create_transport,
        ):
            assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
            await hass.async_block_till_done()
        receive_update = create_transport.call_args.kwargs["on_update"]

        async def push(event):
            await receive_update({"event": event}, "test")
            await hass.async_block_till_done()

        return push

    return load


def _schedule_entity_id(hass, suffix):
    return er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{MOCK_SERIAL}_switch_{suffix}"
    )


@pytest.mark.parametrize(
    ("schedule", "expected"),
    [
        (None, None),
        ([], None),
        ({"Enabled": 1}, None),
        ({"Enabled": True, "Events": {}}, None),
        ({"Enabled": False}, "off"),
        ({"Enabled": True, "Events": []}, "on"),
    ],
)
async def test_scheduler_is_created_only_for_valid_schedule(
    hass, load_schedules, schedule, expected
):
    await load_schedules(schedule)
    scheduler_id = _schedule_entity_id(hass, "scheduler")
    if expected is None:
        assert scheduler_id is None
    else:
        assert hass.states.get(scheduler_id).state == expected
    assert _schedule_entity_id(hass, "schedule_event_0") is None


async def test_schedule_push_renames_and_removes_events(
    hass, mock_config_entry, load_schedules
):
    registry = er.async_get(hass)
    offline = registry.async_get_or_create(
        "switch",
        DOMAIN,
        f"{MOCK_SERIAL}_switch_schedule_event_9",
        config_entry=mock_config_entry,
    )
    push = await load_schedules()
    assert registry.async_get(offline.entity_id) is not None

    await push({"NV_Schedule": {"Enabled": True, "Events": [_SCHEDULE_EVENT]}})
    event_id = _schedule_entity_id(hass, "schedule_event_0")
    assert registry.async_get(offline.entity_id) is None
    assert hass.states.get(event_id).attributes["start_time"] == "T06:00"
    assert hass.states.get(event_id).attributes["setpoint_cool"] == 23

    await push(
        {
            "NV_Schedule.Events[0].Name": "Evening cooling",
            "NV_Schedule.Events[0].Enabled": True,
        }
    )
    assert _schedule_entity_id(hass, "schedule_event_0") == event_id
    assert hass.states.get(event_id).state == "on"
    assert "Evening cooling" in hass.states.get(event_id).name
    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diagnostics["data"]["schedule"]["events"] == [
        {"id": 0, "position": 0, "enabled": True}
    ]

    registry.async_update_entity(event_id, name="My custom name")
    await push({"NV_Schedule.Events[0].Name": "Different controller name"})
    assert hass.states.get(event_id).name == "ActronAir Neo My custom name"
    await push({"NV_Schedule": None})
    assert hass.states.get(event_id).state == "unavailable"
    assert _schedule_entity_id(hass, "schedule_event_0") == event_id

    await push(
        {"NV_Schedule": {"Enabled": True, "Events": [{**_SCHEDULE_EVENT, "ID": 2}]}}
    )
    assert _schedule_entity_id(hass, "schedule_event_0") is None
    assert hass.states.get(event_id) is None
    replacement = _schedule_entity_id(hass, "schedule_event_2")
    assert replacement is not None
    assert replacement != event_id
    await push({"NV_Schedule.Events": [_SCHEDULE_EVENT]})
    assert _schedule_entity_id(hass, "schedule_event_0") == event_id
    assert hass.states.get(event_id).name == "ActronAir Neo My custom name"

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await push({"NV_Schedule.Events": [{**_SCHEDULE_EVENT, "ID": 3}]})
    assert _schedule_entity_id(hass, "schedule_event_3") is None


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    "target",
    [
        ("scheduler", "set_schedule_enabled", ()),
        ("schedule_event_0", "set_schedule_event_enabled", (0,)),
    ],
)
async def test_schedule_switches_write_and_refresh(
    hass, load_schedules, mock_api, enabled, target
):
    suffix, api_method, args = target
    await load_schedules(
        {
            "Enabled": not enabled,
            "Events": [{**_SCHEDULE_EVENT, "Enabled": not enabled}],
        }
    )
    service = "turn_on" if enabled else "turn_off"
    entity_id = _schedule_entity_id(hass, suffix)
    mock_api.get_ac_status.reset_mock()
    await hass.services.async_call(
        "switch", service, {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    getattr(mock_api, api_method).assert_awaited_once_with(*args, enabled=enabled)
    mock_api.get_ac_status.assert_awaited_with(MOCK_SERIAL, use_cache=False)
    assert hass.states.get(entity_id).state == ("off" if enabled else "on")


async def test_schedule_skips_bad_rows_and_omits_invalid_attributes(
    hass, load_schedules
):
    await load_schedules(
        {
            "Enabled": True,
            "Events": [
                {"ID": True, "Enabled": True},
                {"ID": 1, "Enabled": 0},
                {
                    "ID": 2,
                    "Enabled": False,
                    "Name": " ",
                    "EnabledZones": [0],
                    "TemperatureSetpoint_Cool_oC": float("inf"),
                },
            ],
        }
    )
    assert _schedule_entity_id(hass, "schedule_event_1") is None
    valid = hass.states.get(_schedule_entity_id(hass, "schedule_event_2"))
    assert valid.state == "off"
    assert valid.name == "ActronAir Neo Schedule 2"
    assert "enabled_zones" not in valid.attributes
    assert "setpoint_cool" not in valid.attributes


async def test_schedule_event_rejects_ambiguous_addresses(
    hass, load_schedules, mock_api
):
    push = await load_schedules({"Enabled": True, "Events": [_SCHEDULE_EVENT]})
    event_id = _schedule_entity_id(hass, "schedule_event_0")
    await push({"NV_Schedule.Events": [None]})
    assert _schedule_entity_id(hass, "schedule_event_0") == event_id
    assert hass.states.get(event_id).state == "unavailable"

    for rows in ([_SCHEDULE_EVENT, _SCHEDULE_EVENT], [{**_SCHEDULE_EVENT, "ID": 2}]):
        await push({"NV_Schedule.Events": rows})
        target = _schedule_entity_id(hass, f"schedule_event_{rows[0]['ID']}")
        with pytest.raises(HomeAssistantError, match="cannot be addressed safely"):
            await hass.services.async_call(
                "switch", "turn_on", {"entity_id": target}, blocking=True
            )
    mock_api.set_schedule_event_enabled.assert_not_awaited()
