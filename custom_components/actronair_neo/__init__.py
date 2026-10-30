"""The ActronAir Neo integration."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.exceptions import (  # type: ignore[import-untyped]
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import (
    config_validation as cv,  # type: ignore[import-untyped]
)
from homeassistant.helpers import (
    device_registry as dr,  # type: ignore[import-untyped]
)
from homeassistant.helpers import (
    entity_registry as er,  # type: ignore[import-untyped]
)
from homeassistant.helpers.storage import Store

from . import repairs
from .api import ActronAirNeoApiClient
from .api.auth import ActronAirNeoAuth
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_BASE_URL,
    CONF_ENABLE_PUSH,
    CONF_ENABLE_ZONE_CONTROL,
    CONF_REFRESH_TOKEN,
    CONF_SERIAL_NUMBER,
    CONF_TOKEN_EXPIRES_AT,
    DEFAULT_ENABLE_PUSH,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
    PLATFORMS,
    POWER_FORMAT_STORAGE_VERSION,
    SERVICE_APPLY_ZONE_PRESET,
    SERVICE_BULK_ZONE_OPERATION,
    SERVICE_CREATE_ZONE_PRESET,
    SERVICE_FORCE_UPDATE,
)
from .coordinator import ActronDataCoordinator, power_format_storage_key
from .dashboard import async_register_dashboard
from .exceptions import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    ZoneError,
)
from .frontend import async_register_frontend
from .ssl_helper import async_create_clientsession

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry  # type: ignore[import-untyped]
    from homeassistant.core import (  # type: ignore[import-untyped]
        HomeAssistant,
        ServiceCall,
    )

_LOGGER = logging.getLogger(__name__)

# This integration is configured exclusively via the UI config flow; it has no
# YAML configuration, so reject any domain-level YAML config. The HA helper is
# only partially typed, hence the targeted ignores.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    DOMAIN
)

type ActronAirNeoConfigEntry = ConfigEntry[ActronDataCoordinator]

# ── Service schemas ─────────────────────────────────────────────

SERVICE_FORCE_UPDATE_SCHEMA = probatio.Schema({})

SERVICE_CREATE_ZONE_PRESET_SCHEMA = probatio.Schema(
    {
        probatio.Required("device_id"): str,
        probatio.Required("name"): str,
        probatio.Optional("description", default=""): str,
    }
)

SERVICE_APPLY_ZONE_PRESET_SCHEMA = probatio.Schema(
    {
        probatio.Required("device_id"): str,
        probatio.Required("name"): str,
    }
)

SERVICE_BULK_ZONE_OPERATION_SCHEMA = probatio.Schema(
    {
        probatio.Required("device_id"): str,
        probatio.Required("operation"): probatio.In(
            ["enable", "disable", "set_temperature"]
        ),
        probatio.Required("zones"): list,
        probatio.Optional("temperature"): probatio.Coerce(float),
        probatio.Optional("temp_key", default="temp_setpoint_cool"): str,
    }
)

PARALLEL_UPDATES = 0


# ── Config entry migration ──────────────────────────────────────


async def async_migrate_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,  # type: ignore[type-arg]
) -> bool:
    """Migrate config entry to a new version."""
    if config_entry.version > 2:  # noqa: PLR2004
        _LOGGER.error(
            "Config entry version %s is newer than supported (2)",
            config_entry.version,
        )
        return False

    if config_entry.version == 1:
        # Keep non-credential data; tokens will be set during reauth.
        new_data = {
            CONF_SERIAL_NUMBER: config_entry.data[CONF_SERIAL_NUMBER],
            "system_id": config_entry.data.get("system_id", ""),
        }
        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            version=2,
        )

    return True


# ── Integration setup ───────────────────────────────────────────


async def async_setup(
    hass: HomeAssistant,
    config: dict[str, Any],  # noqa: ARG001
) -> bool:
    """Set up the ActronAir Neo integration (register services once)."""
    _register_services(hass)
    async_register_dashboard(hass)
    await async_register_frontend(hass)
    return True


# ── Entity migration ────────────────────────────────────────────


async def async_migrate_entities(
    hass: HomeAssistant, config_entry: ActronAirNeoConfigEntry
) -> None:
    """Migrate old entity IDs to new entity IDs."""
    entity_registry = er.async_get(hass)
    coordinator = config_entry.runtime_data

    entity_entries = er.async_entries_for_config_entry(
        entity_registry, config_entry.entry_id
    )

    migration_mappings = _build_migration_mappings(coordinator)

    for entry in entity_entries:
        old_unique_id = entry.unique_id
        if old_unique_id in migration_mappings:
            new_unique_id = migration_mappings[old_unique_id]
            if old_unique_id != new_unique_id:
                with contextlib.suppress(HomeAssistantError):
                    entity_registry.async_update_entity(
                        entry.entity_id,
                        new_unique_id=new_unique_id,
                    )


def _build_migration_mappings(
    coordinator: ActronDataCoordinator,
) -> dict[str, str]:
    """Build entity unique-ID migration mapping."""
    dev = coordinator.device_id
    mappings: dict[str, str] = {
        f"{dev}_climate": f"{dev}_climate",
        f"{dev}_main_temperature": (f"{dev}_sensor_indoor_temperature"),
        f"{dev}_filter_status": (f"{dev}_binary_sensor_filter_status"),
        f"{dev}_system_status": (f"{dev}_binary_sensor_system_status"),
        f"{dev}_system_health": (f"{dev}_binary_sensor_system_health"),
        f"{dev}_away_mode": f"{dev}_switch_away_mode",
        f"{dev}_quiet_mode": f"{dev}_switch_quiet_mode",
        f"{dev}_continuous_fan": (f"{dev}_switch_continuous_fan"),
    }

    for zone_id, zone_data in coordinator.data["zones"].items():
        zone_name = zone_data["name"].lower().replace(" ", "_")
        mappings[f"{dev}_zone_{zone_id}"] = f"{dev}_climate_zone_{zone_name}"
        mappings[f"{dev}_zone_{zone_id}_temperature"] = f"{dev}_sensor_zone_{zone_name}"

    return mappings


# ── Entry setup / unload ────────────────────────────────────────


async def async_setup_entry(
    hass: HomeAssistant, entry: ActronAirNeoConfigEntry
) -> bool:
    """Set up ActronAir Neo from a config entry."""
    # After V1→V2 migration, tokens may be missing → trigger reauth.
    _required_token_keys = (
        CONF_ACCESS_TOKEN,
        CONF_REFRESH_TOKEN,
        CONF_TOKEN_EXPIRES_AT,
    )
    if any(key not in entry.data for key in _required_token_keys):
        _msg = (
            "Authentication required — please re-authenticate "
            "using the device code flow."
        )
        raise ConfigEntryAuthFailed(_msg)

    api = await _create_api_client(hass, entry)

    try:
        await api.initialize()
        await api.set_system(
            entry.data[CONF_SERIAL_NUMBER],
            entry.data.get("system_id", ""),
            base_url=entry.data.get(CONF_BASE_URL, ""),
        )
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed from err
    except ApiError as err:
        raise ConfigEntryNotReady from err

    coordinator = ActronDataCoordinator(
        hass,
        api,
        entry.data[CONF_SERIAL_NUMBER],
        DEFAULT_REFRESH_INTERVAL,
        enable_zone_control=entry.options.get(CONF_ENABLE_ZONE_CONTROL, False),
        enable_push=entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH),
        config_entry=entry,
    )

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Migrate entities (non-fatal).
    with contextlib.suppress(HomeAssistantError, KeyError, TypeError):
        await async_migrate_entities(hass, entry)

    await coordinator.async_initialize_zone_management()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await coordinator.async_start_push()
    entry.async_on_unload(coordinator.async_stop_push)

    # Schedule repairs check.
    create_bg_task = getattr(entry, "async_create_background_task", None)
    if callable(create_bg_task):
        create_bg_task(
            hass,
            repairs.async_check_issues(hass, entry),
            f"{DOMAIN}_repairs_{entry.entry_id}",
        )
    else:
        hass.async_create_task(repairs.async_check_issues(hass, entry))
    return True


async def _create_api_client(
    hass: HomeAssistant, entry: ActronAirNeoConfigEntry
) -> ActronAirNeoApiClient:
    """
    Create and return an API client from config entry.

    Uses a private aiohttp ClientSession backed by the certifi CA bundle to
    work around the HA 2026.4 truststore change which breaks SSL verification
    against ``nimbus.actronair.com.au`` (issue #96). The session is closed in
    ``async_unload_entry``.
    """
    session = await async_create_clientsession(hass)

    def _close_session() -> None:
        hass.async_create_task(session.close())

    entry.async_on_unload(_close_session)
    auth = ActronAirNeoAuth(session=session)

    # Restore tokens from config entry data.
    auth.set_tokens(
        access_token=entry.data[CONF_ACCESS_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        expires_at=entry.data[CONF_TOKEN_EXPIRES_AT],
    )

    # Persist refreshed tokens back into the config entry.
    async def _on_token_refreshed(
        access_token: str, refresh_token: str, expires_at: float
    ) -> None:
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_ACCESS_TOKEN: access_token,
                CONF_REFRESH_TOKEN: refresh_token,
                CONF_TOKEN_EXPIRES_AT: expires_at,
            },
        )

    auth.set_token_refresh_callback(_on_token_refreshed)

    return ActronAirNeoApiClient(auth=auth, session=session)


async def async_unload_entry(
    hass: HomeAssistant, entry: ActronAirNeoConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: ActronAirNeoConfigEntry
) -> None:
    """Delete the stored compressor power format when the entry is removed."""
    serial = entry.data.get(CONF_SERIAL_NUMBER)
    if not serial:
        return
    store: Store[dict[str, Any]] = Store(
        hass, POWER_FORMAT_STORAGE_VERSION, power_format_storage_key(serial)
    )
    await store.async_remove()


async def async_remove_config_entry_device(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: ActronAirNeoConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Remove a config entry from a device if it is no longer active."""
    coordinator = config_entry.runtime_data
    active_identifier = (DOMAIN, coordinator.device_id)
    return active_identifier not in device_entry.identifiers


# ── Options update listener ────────────────────────────────────


async def update_listener(hass: HomeAssistant, entry: ActronAirNeoConfigEntry) -> None:
    """Handle configuration entry updates."""
    coordinator = entry.runtime_data
    old_zone = coordinator.enable_zone_control
    new_zone = entry.options.get(CONF_ENABLE_ZONE_CONTROL, False)
    new_push = entry.options.get(CONF_ENABLE_PUSH, DEFAULT_ENABLE_PUSH)

    # The listener fires on every entry update, including the periodic token
    # refresh persisted into entry.data. Only a real options change warrants a
    # reload — otherwise the integration would restart on every token refresh.
    if new_zone == old_zone and new_push == coordinator.enable_push:
        return

    if old_zone and not new_zone:
        entity_registry = er.async_get(hass)
        entries = er.async_entries_for_config_entry(entity_registry, entry.entry_id)
        # Check both old and new unique_id formats
        zone_prefixes = (
            f"{coordinator.device_id}_zone_",
            f"{coordinator.device_id}_climate_zone_",
        )
        for entity_entry in entries:
            if entity_entry.unique_id.startswith(zone_prefixes):
                entity_registry.async_remove(entity_entry.entity_id)

        await coordinator.set_enable_zone_control(enable=new_zone)
        await coordinator.async_request_refresh()

    await hass.config_entries.async_reload(entry.entry_id)


# ── Service handlers ────────────────────────────────────────────


def _register_services(hass: HomeAssistant) -> None:
    """Register integration services (called once from async_setup)."""
    if hass.services.has_service(DOMAIN, SERVICE_FORCE_UPDATE):
        return

    services = (
        (SERVICE_FORCE_UPDATE, _handle_force_update, SERVICE_FORCE_UPDATE_SCHEMA),
        (
            SERVICE_CREATE_ZONE_PRESET,
            _handle_create_zone_preset,
            SERVICE_CREATE_ZONE_PRESET_SCHEMA,
        ),
        (
            SERVICE_APPLY_ZONE_PRESET,
            _handle_apply_zone_preset,
            SERVICE_APPLY_ZONE_PRESET_SCHEMA,
        ),
        (
            SERVICE_BULK_ZONE_OPERATION,
            _handle_bulk_zone_operation,
            SERVICE_BULK_ZONE_OPERATION_SCHEMA,
        ),
    )
    for service, handler, schema in services:
        # HA's VolSchemaType includes the unparameterised generic probatio.All,
        # so pyright reports the method type as partially unknown.
        hass.services.async_register(  # pyright: ignore[reportUnknownMemberType]
            DOMAIN, service, handler, schema=schema
        )


def _get_coordinators(hass: HomeAssistant) -> list[ActronDataCoordinator]:
    """Get all active coordinators from config entries."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if hasattr(entry, "runtime_data")
        and isinstance(entry.runtime_data, ActronDataCoordinator)
    ]


def _find_coordinator(
    hass: HomeAssistant, device_id: str
) -> ActronDataCoordinator | None:
    """Find coordinator by device_id."""
    for coordinator in _get_coordinators(hass):
        if coordinator.device_id == device_id:
            return coordinator
    return None


async def _handle_force_update(call: ServiceCall) -> None:
    """Force update of all coordinators."""
    hass = call.hass
    coordinators = _get_coordinators(hass)
    if not coordinators:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="no_devices_configured",
        )

    for coordinator in coordinators:
        await coordinator.async_request_refresh()


def _require_coordinator(hass: HomeAssistant, device_id: str) -> ActronDataCoordinator:
    """Look up a coordinator by device_id or raise."""
    coordinator = _find_coordinator(hass, device_id)
    if not coordinator:
        msg = f"Device {device_id} not found"
        raise ServiceValidationError(
            msg,
            translation_domain=DOMAIN,
            translation_key="device_not_found",
        )
    if not coordinator.enable_zone_control:
        msg = f"Zone control not enabled for device {device_id}"
        raise ServiceValidationError(
            msg,
            translation_domain=DOMAIN,
            translation_key="zone_control_disabled",
        )
    return coordinator


async def _handle_create_zone_preset(call: ServiceCall) -> None:
    """Create a zone preset from current state."""
    hass = call.hass
    device_id = call.data["device_id"]
    preset_name = call.data["name"]
    description = call.data.get("description", "")

    coordinator = _require_coordinator(hass, device_id)

    try:
        await coordinator.async_create_zone_preset_from_current(
            preset_name, description
        )
    except (ConfigurationError, ZoneError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="create_preset_failed",
            translation_placeholders={"error": str(err)},
        ) from err


async def _handle_apply_zone_preset(call: ServiceCall) -> None:
    """Apply a zone preset."""
    hass = call.hass
    device_id = call.data["device_id"]
    preset_name = call.data["name"]

    coordinator = _require_coordinator(hass, device_id)

    try:
        await coordinator.async_apply_zone_preset(preset_name)
    except (ConfigurationError, ZoneError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="apply_preset_failed",
            translation_placeholders={"error": str(err)},
        ) from err


async def _handle_bulk_zone_operation(call: ServiceCall) -> None:
    """Perform bulk zone operations."""
    hass = call.hass
    device_id = call.data["device_id"]
    operation = call.data["operation"]
    zones = call.data["zones"]

    coordinator = _require_coordinator(hass, device_id)

    try:
        kwargs: dict[str, str | float | None] = {}
        if operation == "set_temperature":
            kwargs["temperature"] = call.data.get("temperature")
            kwargs["temp_key"] = call.data.get("temp_key", "temp_setpoint_cool")

        results = await coordinator.async_bulk_zone_operation(
            operation, zones, **kwargs
        )
        failed = [
            r.get("zone_id", r.get("zone", "unknown"))
            for r in results
            if r["status"] != "success"
        ]
        if failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="bulk_operation_failed",
                translation_placeholders={
                    "error": f"Zones failed: {', '.join(str(z) for z in failed)}"
                },
            )
    except (ConfigurationError, ZoneError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="bulk_operation_failed",
            translation_placeholders={"error": str(err)},
        ) from err
