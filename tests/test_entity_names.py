"""Entity names come from the translation strings (entity-translations)."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

from .conftest import MOCK_SERIAL

_PATCH_CREATE_API = "custom_components.actronair_neo._create_api_client"


async def test_entity_names_use_translations(
    hass,
    mock_config_entry_with_zones,
    mock_api,
    mock_api_response,
    enable_custom_integrations,
):
    """Translated names apply, zone names fill placeholders and IDs are kept."""
    response = copy.deepcopy(mock_api_response)
    # Quiet mode off at start-up must still create the switch (#199).
    response["lastKnownState"]["UserAirconSettings"]["QuietModeEnabled"] = False
    for zone in response["lastKnownState"]["RemoteZoneInfo"]:
        # YourZone airflow control creates the damper cover; a sensor keyed by
        # this entry's serial makes the zone wireless, which adds a battery.
        zone["AirflowControlEnabled"] = True
        zone["Sensors"] = {MOCK_SERIAL: zone["Sensors"]["TEST123456"]}
    mock_api.get_ac_status = AsyncMock(return_value=response)
    with patch(_PATCH_CREATE_API, return_value=mock_api):
        await hass.config_entries.async_setup(mock_config_entry_with_zones.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry_with_zones.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = {
        entry.entity_id: entry
        for entry in er.async_entries_for_config_entry(
            registry, mock_config_entry_with_zones.entry_id
        )
    }
    names = {
        entity_id: state.name
        for entity_id in entities
        if (state := hass.states.get(entity_id)) is not None
    }

    assert names["switch.actronair_neo_quiet_mode"] == "ActronAir Neo Quiet mode"
    assert names["switch.actronair_neo_away_mode"] == "ActronAir Neo Away mode"
    assert names["switch.actronair_neo_zone_living_room"] == (
        "ActronAir Neo Zone Living Room"
    )
    assert names["sensor.actronair_neo_zone_bedroom_humidity"] == (
        "ActronAir Neo Zone Bedroom humidity"
    )
    assert names["sensor.actronair_neo_zone_living_room_battery"] == (
        "ActronAir Neo Zone Living Room battery"
    )
    assert names["cover.actronair_neo_bedroom_damper"] == (
        "ActronAir Neo Bedroom damper"
    )
    assert names["binary_sensor.actronair_neo_bedroom_yourzone_enabled"] == (
        "ActronAir Neo Bedroom YourZone enabled"
    )
    # Every translated name resolved: no raw placeholder left anywhere.
    assert not [name for name in names.values() if "{" in name]
    # Unique IDs still come from the English suffix, so existing IDs are kept.
    assert entities["switch.actronair_neo_quiet_mode"].unique_id.endswith(
        "_switch_quiet_mode"
    )
