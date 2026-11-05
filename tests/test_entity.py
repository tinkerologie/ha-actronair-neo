"""Tests for the ActronAir Neo base entity classes."""

import importlib
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.actronair_neo.const import DEVICE_MANUFACTURER, DOMAIN
from custom_components.actronair_neo.entity import (
    ActronAirNeoEntity,
)

from .conftest import MOCK_SERIAL, create_mock_coordinator


@pytest.fixture
def coordinator(mock_api, mock_status):
    """Create a coordinator for testing."""
    return create_mock_coordinator(MagicMock(), mock_api, mock_status)


class TestActronAirNeoEntity:
    """Tests for the base entity class."""

    def test_has_entity_name(self, coordinator):
        """Test entity has entity name enabled."""
        entity = ActronAirNeoEntity(coordinator, "test")
        assert entity._attr_has_entity_name is True

    def test_unique_id(self, coordinator):
        """Test unique ID generation."""
        entity = ActronAirNeoEntity(coordinator, "temperature")
        assert entity._attr_unique_id == f"{MOCK_SERIAL}_temperature"

    def test_unique_id_with_suffix(self, coordinator):
        """Test unique ID with name suffix."""
        entity = ActronAirNeoEntity(coordinator, "zone", "Living Room")
        assert entity._attr_unique_id == f"{MOCK_SERIAL}_zone_living_room"

    def test_device_info(self, coordinator, mock_status):
        """Test device info is set correctly."""
        entity = ActronAirNeoEntity(coordinator, "test")
        device_info = entity.device_info
        assert device_info is not None
        assert (DOMAIN, MOCK_SERIAL) in device_info.identifiers
        assert device_info.manufacturer == DEVICE_MANUFACTURER
        assert device_info.name == "ActronAir Neo"

    def test_device_info_model(self, coordinator, mock_status):
        """Test device info model from coordinator data."""
        entity = ActronAirNeoEntity(coordinator, "test")
        device_info = entity.device_info
        assert device_info is not None
        assert device_info.model == "NEO-12"

    def test_device_info_sw_version(self, coordinator, mock_status):
        """Test device info firmware version."""
        entity = ActronAirNeoEntity(coordinator, "test")
        device_info = entity.device_info
        assert device_info is not None
        assert device_info.sw_version == "1.2.3"

    def test_device_info_no_data(self, coordinator):
        """Test device info when coordinator data is None."""
        coordinator.data = None
        entity = ActronAirNeoEntity(coordinator, "test")
        assert entity.device_info is None

    def test_diagnostic_entity_category(self, coordinator):
        """Test diagnostic entity gets correct category."""
        entity = ActronAirNeoEntity(coordinator, "diag", is_diagnostic=True)
        assert entity._attr_entity_category is not None


# ── In-place entity_id changes (Home Assistant 2026.11, #232) ────


def _integration_entity_classes() -> list[type]:
    """Every entity class defined by the integration's platform modules."""
    from homeassistant.helpers.entity import Entity

    classes: set[type] = set()
    for name in (
        "binary_sensor",
        "climate",
        "cover",
        "entity",
        "number",
        "sensor",
        "switch",
    ):
        module = importlib.import_module(f"custom_components.actronair_neo.{name}")
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, Entity) and obj.__module__.startswith(
                "custom_components.actronair_neo"
            ):
                classes.add(obj)
    return sorted(classes, key=lambda cls: cls.__qualname__)


def test_every_entity_class_opts_in_to_in_place_entity_id_change():
    """No integration entity class falls back to remove-and-re-add on rename."""
    from homeassistant.helpers.entity import _entity_class_requires_readd

    classes = _integration_entity_classes()
    assert len(classes) > 10
    legacy = [cls.__qualname__ for cls in classes if _entity_class_requires_readd(cls)]
    assert legacy == []


async def test_entity_id_rename_updates_in_place(
    hass, mock_config_entry, mock_api, mock_ac_status_response
):
    """A registry rename keeps the entity added, registered and discoverable."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.actronair_neo.dashboard import INVENTORY

    mock_api.get_ac_status = AsyncMock(return_value=mock_ac_status_response)
    with patch(
        "custom_components.actronair_neo._create_api_client", return_value=mock_api
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    registry = er.async_get(hass)
    old_id = next(
        entry.entity_id
        for entry in er.async_entries_for_config_entry(
            registry, mock_config_entry.entry_id
        )
        if entry.domain == "climate"
    )
    inventory = hass.data[INVENTORY][mock_config_entry.entry_id]
    climate = next(e for e in inventory.values() if e.entity_id == old_id)

    with patch("custom_components.actronair_neo.entity.register_entity") as reregister:
        registry.async_update_entity(old_id, new_entity_id="climate.renamed_by_user")
        await hass.async_block_till_done()

    reregister.assert_not_called()  # not removed and re-added
    assert climate.entity_id == "climate.renamed_by_user"
    assert hass.states.get(old_id) is None
    assert hass.states.get("climate.renamed_by_user") is not None
    assert any(e is climate for e in inventory.values())

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
