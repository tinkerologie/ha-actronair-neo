"""Exercise authenticated discovery, ownership and lifecycle boundaries."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.actronair_neo.climate import ActronClimate
from custom_components.actronair_neo.const import DOMAIN
from custom_components.actronair_neo.dashboard import (
    async_register_dashboard,
    register_entity,
)
from custom_components.actronair_neo.switch import ActronZoneSwitch

from .conftest import create_mock_coordinator


@pytest.fixture
async def dashboard_system(hass, mock_api, mock_status):
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id="SERIAL_PRIVATE")
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    coordinator = create_mock_coordinator(hass, mock_api, mock_status)
    coordinator.device_id = "SERIAL_PRIVATE"
    coordinator.config_entry = entry
    entry.runtime_data = coordinator
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "SERIAL_PRIVATE")},
        name="Home climate",
    )
    entities = []
    for entity, domain, unique_id in [
        (ActronClimate(coordinator), "climate", "unchanged-main"),
        (ActronZoneSwitch(coordinator, "zone_1"), "switch", "unchanged-zone"),
    ]:
        registered = er.async_get(hass).async_get_or_create(
            domain, DOMAIN, unique_id, config_entry=entry, device_id=device.id
        )
        entity.hass = hass
        entity.entity_id = registered.entity_id
        register_entity(entity)
        entities.append(entity)
    async_register_dashboard(hass)
    return entry, device, entities


async def test_discovery_maps_roles_without_serial(
    hass, hass_ws_client, dashboard_system
):
    entry, device, entities = dashboard_system
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    response = await client.receive_json()
    assert response["success"]
    assert response["result"]["system"]["system_climate"] == entities[0].entity_id
    assert (
        response["result"]["zones"][0]["roles"]["zone_enable"] == entities[1].entity_id
    )
    assert "SERIAL_PRIVATE" not in str(response)
    assert response["result"]["entry_id"] == entry.entry_id


async def test_renamed_entity_is_discovered(hass, hass_ws_client, dashboard_system):
    _, device, entities = dashboard_system
    registry = er.async_get(hass)
    original = registry.async_get(entities[0].entity_id)
    registry.async_update_entity(
        entities[0].entity_id, new_entity_id="climate.renamed_by_user"
    )
    entities[0].entity_id = "climate.renamed_by_user"
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    response = await client.receive_json()
    assert response["result"]["system"]["system_climate"] == "climate.renamed_by_user"
    assert registry.async_get("climate.renamed_by_user").unique_id == original.unique_id


async def test_foreign_and_unloaded_entries_are_rejected(
    hass, hass_ws_client, dashboard_system
):
    entry, device, _ = dashboard_system
    client = await hass_ws_client(hass)
    for number, device_id in enumerate(["foreign-device", device.id], 1):
        entry.mock_state(hass, ConfigEntryState.NOT_LOADED)
        await client.send_json(
            {
                "id": number,
                "type": "actronair_neo/dashboard/discover",
                "device_id": device_id,
            }
        )
        response = await client.receive_json()
        assert not response["success"]
        assert response["error"]["code"] == "not_found"


async def test_permission_and_disabled_entities_are_omitted(
    hass,
    hass_ws_client,
    hass_read_only_user,
    hass_read_only_access_token,
    dashboard_system,
):
    _, device, entities = dashboard_system
    client = await hass_ws_client(hass, access_token=hass_read_only_access_token)
    with patch.object(
        type(hass_read_only_user.permissions),
        "check_entity",
        autospec=True,
        side_effect=lambda _permissions, entity_id, _: (
            entity_id != entities[1].entity_id
        ),
    ):
        await client.send_json(
            {
                "id": 1,
                "type": "actronair_neo/dashboard/discover",
                "device_id": device.id,
            }
        )
        response = await client.receive_json()
    assert response["result"]["zones"] == []
    er.async_get(hass).async_update_entity(
        entities[1].entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    await client.send_json(
        {"id": 2, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    assert (await client.receive_json())["result"]["zones"] == []


async def test_cross_entry_entity_is_never_exposed(
    hass, hass_ws_client, dashboard_system
):
    _, device, entities = dashboard_system
    other = MockConfigEntry(domain=DOMAIN, data={})
    other.add_to_hass(hass)
    er.async_get(hass).async_update_entity(
        entities[1].entity_id, config_entry_id=other.entry_id
    )
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    assert (await client.receive_json())["result"]["zones"] == []


async def test_replacement_registration_survives_stale_removal(
    hass, hass_ws_client, dashboard_system
):
    entry, device, entities = dashboard_system
    original = entities[0]
    replacement = ActronClimate(entry.runtime_data)
    replacement.hass = hass
    replacement.entity_id = original.entity_id
    callbacks = []
    with patch.object(original, "async_on_remove", side_effect=callbacks.append):
        register_entity(original)
    with patch.object(replacement, "async_on_remove", side_effect=callbacks.append):
        register_entity(replacement)
    callbacks[0]()
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    assert (await client.receive_json())["result"]["system"][
        "system_climate"
    ] == original.entity_id
    callbacks[1]()
    await client.send_json(
        {"id": 2, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    assert "system_climate" not in (await client.receive_json())["result"]["system"]
    assert er.async_get(hass).async_get(original.entity_id) is not None


async def test_other_system_with_same_name_is_isolated(
    hass, hass_ws_client, dashboard_system
):
    entry, device, _ = dashboard_system
    other = MockConfigEntry(domain=DOMAIN, data={}, unique_id="OTHER_PRIVATE")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.LOADED)
    coordinator = create_mock_coordinator(
        hass, entry.runtime_data.api, entry.runtime_data.data
    )
    coordinator.device_id = "OTHER_PRIVATE"
    coordinator.config_entry = other
    other.runtime_data = coordinator
    other_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id,
        identifiers={(DOMAIN, "OTHER_PRIVATE")},
        name="Home climate",
    )
    registered = er.async_get(hass).async_get_or_create(
        "climate", DOMAIN, "other-main", config_entry=other, device_id=other_device.id
    )
    entity = ActronClimate(coordinator)
    entity.hass = hass
    entity.entity_id = registered.entity_id
    register_entity(entity)
    client = await hass_ws_client(hass)
    await client.send_json(
        {"id": 1, "type": "actronair_neo/dashboard/discover", "device_id": device.id}
    )
    response = await client.receive_json()
    assert registered.entity_id not in str(response)
    assert "OTHER_PRIVATE" not in str(response)
