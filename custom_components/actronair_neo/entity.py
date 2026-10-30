"""Base entity for ActronAir Neo integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import (
    DeviceInfo,  # type: ignore[import-untyped]
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,  # type: ignore[import-untyped]
)

from .const import DEVICE_MANUFACTURER, DOMAIN

if TYPE_CHECKING:
    from .coordinator import ActronDataCoordinator


class ActronAirNeoEntity(CoordinatorEntity["ActronDataCoordinator"]):
    """Base class for all ActronAir Neo entities."""

    _attr_has_entity_name = True
    _attr_attribution = "Data provided by ActronAir Neo"

    DEVICE_NAME = "ActronAir Neo"

    def __init__(
        self,
        coordinator: ActronDataCoordinator,
        entity_type: str,
        name_suffix: str = "",
        *,
        is_diagnostic: bool = False,
    ) -> None:
        """Initialize the base entity."""
        super().__init__(coordinator)

        if is_diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

        # Generate consistent unique_id.
        base_unique_id = f"{coordinator.device_id}_{entity_type}"
        self._attr_unique_id = (
            f"{base_unique_id}_{name_suffix.lower().replace(' ', '_')}"
            if name_suffix
            else base_unique_id
        )

        # Entities with a translation_key take their name from strings.json;
        # setting _attr_name would override it.  Others use name_suffix as
        # the name.  HA prefixes the device name (has_entity_name is True).
        if not getattr(self, "_attr_translation_key", None):
            self._attr_name = name_suffix or None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information."""
        if not self.coordinator.data:
            return None
        main_data = self.coordinator.data.get("main", {})
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.device_id)},
            name=self.DEVICE_NAME,
            manufacturer=DEVICE_MANUFACTURER,
            model=main_data.get("model"),
            serial_number=self.coordinator.device_id,
            sw_version=main_data.get("firmware_version"),
        )


class ActronZoneEntity(ActronAirNeoEntity):
    """
    Base for per-zone entities.

    Reports ``unavailable`` when the entity's zone is absent from coordinator
    data, so a transient/partial update that omits the zone renders the entity
    unavailable rather than raising ``KeyError`` from its state properties.
    Subclasses set ``self.zone_id`` in their ``__init__``.
    """

    zone_id: str

    @property
    def available(self) -> bool:
        """Return True only when the backing zone is present in data."""
        if not super().available or not self.coordinator.data:
            return False
        return self.zone_id in self.coordinator.data.get("zones", {})
