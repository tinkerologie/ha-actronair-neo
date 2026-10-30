"""Discover loaded dashboard entities without exposing identifiers or API data."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, cast

import probatio
from homeassistant.auth.permissions.const import POLICY_READ
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ActronDataCoordinator
    from .entity import ActronAirNeoEntity
    from .types import DashboardData, DashboardZoneData


class DashboardRole(StrEnum):
    """Closed semantic roles assigned explicitly by each entity class."""

    SYSTEM_CLIMATE = "system_climate"
    AWAY_MODE = "away_mode"
    QUIET_MODE = "quiet_mode"
    CONTINUOUS_FAN = "continuous_fan"
    TURBO_MODE = "turbo_mode"
    AFTER_HOURS = "after_hours"
    AFTER_HOURS_DURATION = "after_hours_duration"
    INDOOR_TEMPERATURE = "indoor_temperature"
    OUTDOOR_TEMPERATURE = "outdoor_temperature"
    COMPRESSOR_POWER = "compressor_power"
    COMPRESSOR_ENERGY = "compressor_energy"
    SYSTEM_STATE = "system_state"
    SYSTEM_HEALTH = "system_health"
    ACTIVE_WARNINGS = "active_warnings"
    CONNECTIVITY_STATUS = "connectivity_status"
    SERVICE_REMINDER = "service_reminder"
    ZONE_CLIMATE = "zone_climate"
    ZONE_ENABLE = "zone_enable"
    ZONE_DAMPER = "zone_damper"
    ZONE_DAMPER_POSITION = "zone_damper_position"
    ZONE_TEMPERATURE = "zone_temperature"
    ZONE_HUMIDITY = "zone_humidity"
    ZONE_BATTERY = "zone_battery"
    ZONE_AIRFLOW_CONTROL = "zone_airflow_control"


type Inventory = dict[str, dict[tuple[DashboardRole, str | None], ActronAirNeoEntity]]
INVENTORY: HassKey[Inventory] = HassKey("actronair_neo_dashboard_inventory")
REGISTERED: HassKey[bool] = HassKey("actronair_neo_dashboard_registered")
COMMAND = "actronair_neo/dashboard/discover"


@callback
def register_entity(entity: ActronAirNeoEntity) -> None:
    """Keep a live reference, removing only the same registration on unload."""
    role = entity.dashboard_role
    entry = entity.coordinator.config_entry
    if role is None or entry is None:
        return
    inventory = entity.hass.data.setdefault(INVENTORY, {})
    objects = inventory.setdefault(entry.entry_id, {})
    key = (role, getattr(entity, "zone_id", None))
    objects[key] = entity

    @callback
    def remove() -> None:
        if objects.get(key) is entity:
            objects.pop(key)
        if not objects and inventory.get(entry.entry_id) is objects:
            inventory.pop(entry.entry_id)

    entity.async_on_remove(remove)


@callback
def async_register_dashboard(hass: HomeAssistant) -> None:
    """Register the authenticated command once across entries and reloads."""
    if not hass.data.get(REGISTERED):
        websocket_api.async_register_command(hass, websocket_discover)  # pyright: ignore[reportUnknownMemberType] - HA schema generic is partially typed.
        hass.data[REGISTERED] = True


def _discover(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, device_id: str
) -> DashboardData | None:
    """Validate the owning entry and filter every live object by user access."""
    device = dr.async_get(hass).async_get(device_id)
    if not isinstance(device, dr.DeviceEntry):
        return None
    identifiers = {
        identifier for domain, identifier in device.identifiers if domain == DOMAIN
    }
    entry = hass.config_entries.async_get_entry(device.config_entry_id)
    if (
        len(identifiers) != 1
        or entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        return None
    coordinator = cast("ActronDataCoordinator", entry.runtime_data)
    if coordinator.device_id not in identifiers:
        return None
    registry = er.async_get(hass)
    system: dict[str, str] = {}
    zones: dict[str, DashboardZoneData] = {}
    inventory = hass.data.get(INVENTORY)
    if inventory is None:
        return None
    objects = inventory.get(entry.entry_id, {})
    for (role, zone_id), entity in list(objects.items()):
        entity_id = entity.entity_id
        registered = registry.async_get(entity_id)
        if (
            registered is None
            or registered.platform != DOMAIN
            or registered.config_entry_id != entry.entry_id
            or registered.device_id != device_id
            or registered.disabled_by is not None
            or not connection.user.permissions.check_entity(entity_id, POLICY_READ)
        ):
            continue
        if zone_id is None:
            system[role] = entity_id
        else:
            zone_data = coordinator.data.get("zones", {}).get(zone_id)
            if zone_data is None:
                continue
            zone = zones.setdefault(
                zone_id, {"zone_id": zone_id, "name": zone_data["name"], "roles": {}}
            )
            zone["roles"][role] = entity_id
    if not system and not zones:
        return None
    return {
        "entry_id": entry.entry_id,
        "device_id": device_id,
        "name": device.name_by_user or device.name or "ActronAir Neo",
        "model": device.model,
        "system": system,
        "zones": sorted(
            zones.values(), key=lambda zone: int(zone["zone_id"].split("_")[1])
        ),
    }


@websocket_api.websocket_command(  # pyright: ignore[reportUnknownMemberType] - HA schema generic is partially typed.
    {probatio.Required("type"): COMMAND, probatio.Required("device_id"): str}
)
@callback
def websocket_discover(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    message: dict[str, Any],
) -> None:
    """Return only loaded, owned and readable entities for a selected device."""
    result = _discover(hass, connection, message["device_id"])
    if result is None:
        connection.send_error(
            message["id"], "not_found", "ActronAir Neo system not found or not readable"
        )
    else:
        connection.send_result(message["id"], result)
