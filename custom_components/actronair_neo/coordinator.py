"""Coordinator for the ActronAir Neo integration."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import inspect
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.climate.const import (
    HVACMode,  # type: ignore[import-untyped]
)
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,  # type: ignore[import-untyped]
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (  # type: ignore[import-untyped]
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api.const import HEARTBEAT_STALE_AFTER, MIN_FAN_MODE_INTERVAL
from .api.models import (
    FALLBACK_SUPPORTED_MODES,
    ModeSupport,
    UserSetpointLimits,
)
from .api.models import (
    MainData as MainDataModel,
)
from .api.models import (
    OutdoorUnitData as OutdoorUnitDataModel,
)
from .api.models import (
    ZoneData as ZoneDataModel,
)
from .api.push import PushTransport, create_push_transport
from .api.push.merge import apply_event_paths, deep_merge
from .api.push.models import PushState
from .const import (
    ADVANCE_FAN_MODES,
    COMP_POWER_SCALE_FACTOR,
    DEFAULT_ENABLE_PUSH,
    DOMAIN,
    FAN_MODE_SUFFIX_CONT,
    HUMIDITY_UNAVAILABLE,
    MAX_TEMP,
    MAX_ZONES,
    MIN_TEMP,
    NEO_SERIES_WC,
    OUTDOOR_TEMP_UNAVAILABLE,
    PARSE_CACHE_TTL,
    POWER_FORMAT_NATIVE_WATT,
    POWER_FORMAT_STORAGE_KEY,
    POWER_FORMAT_STORAGE_VERSION,
    POWER_FORMAT_UNRESOLVED,
    REDUCED_SCALE_MAX_RAW_COMP_POWER,
    REDUCED_SCALE_MAX_RAW_VOLTAGE,
    SUPPLY_VOLTAGE_SCALE_FACTOR,
    THREE_PHASE_FAMILY_MARKER,
    VALID_FAN_MODES,
    ZONE_OVERRIDE_TTL,
)
from .exceptions import (
    ActronAirNeoError,
    ApiError,
    AuthenticationError,
    ConfigurationError,
    DeviceOfflineError,
    RateLimitError,
    ZoneError,
)
from .ssl_helper import async_get_mqtt_ssl_context
from .zone_presets import ZonePresetManager

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry  # type: ignore[import-untyped]
    from homeassistant.core import HomeAssistant  # type: ignore[import-untyped]

    from .api import ActronAirNeoApiClient
    from .api.models import ZoneCapabilities
    from .types import (
        CloudConnectionData,
        ConnectionMetadata,
        CoordinatorData,
        LiveAirconData,
        MainData,
        OutdoorUnitData,
        PeripheralData,
        ServicingData,
        SystemStatusData,
        VFTData,
        ZoneData,
    )

_LOGGER = logging.getLogger(__name__)

_QUE_BROADCAST_METADATA_KEYS: frozenset[str] = frozenset(
    {"event", "type", "wcFirmware", "correlationId", "commandResponse"}
)


def power_format_storage_key(device_id: str) -> str:
    """Return the storage key for a device's persisted CompPower format."""
    return f"{POWER_FORMAT_STORAGE_KEY}_{device_id}"


def _as_float(value: Any) -> float | None:
    """Return a numeric telemetry value as float, or None if not numeric."""
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_matching(reference: dt.datetime | None = None) -> dt.datetime:
    """Return current datetime matching tz-awareness of reference."""
    if reference is not None and reference.tzinfo is not None:
        return dt.datetime.now(dt.UTC)
    return dt.datetime.now()  # noqa: DTZ005


class ActronDataCoordinator(DataUpdateCoordinator["CoordinatorData"]):
    """Class to manage fetching ActronAir Neo data."""

    def __init__(  # noqa: PLR0913
        self,
        hass: HomeAssistant,
        api: ActronAirNeoApiClient,
        device_id: str,
        update_interval: int,
        *,
        enable_zone_control: bool,
        enable_push: bool = DEFAULT_ENABLE_PUSH,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        """
        Initialize the data coordinator.

        Args:
            hass: HomeAssistant instance
            api: ActronAirNeoApiClient instance for API communication
            device_id: Unique identifier for the device
            update_interval: Update interval in seconds
            enable_zone_control: Whether zone control is enabled
            enable_push: Whether realtime MQTT push transport is enabled
            config_entry: Optional ConfigEntry associated with this coordinator

        """
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api
        self.device_id = device_id
        self.enable_zone_control = enable_zone_control
        self.enable_push = enable_push
        self._push_transport: PushTransport | None = None
        self._push_task: asyncio.Task[None] | None = None
        self.last_data: CoordinatorData | None = None

        # Fan mode control attributes
        self._continuous_fan = False
        self._fan_mode_change_lock = asyncio.Lock()
        self._last_fan_mode_change: dt.datetime | None = None
        self._min_fan_mode_interval = MIN_FAN_MODE_INTERVAL

        # Zone state writes update the full EnabledZones array, so they must be
        # serialized across all zones rather than locked per-zone.
        self._zone_state_change_lock = asyncio.Lock()
        # Maps zone index -> (desired_enabled_state, created_at). Each override
        # expires after ZONE_OVERRIDE_TTL so a state the API never confirms does
        # not stick permanently.
        self._pending_zone_state_overrides: dict[int, tuple[bool, dt.datetime]] = {}

        # After a state-changing command, force the next refresh to bypass the
        # API response cache so we re-fetch fresh state rather than a cached
        # pre-command snapshot. See issue #112.
        self._force_fresh_on_next_update = False

        # Cache management
        self._last_cache_cleanup: dt.datetime | None = None

        # Enhanced zone management
        self.zone_preset_manager = ZonePresetManager(hass, device_id)

        # CompPower format latch for single-phase Inverter units (#200).
        # One-directional: once native-watt, never reverts automatically.
        self._power_format = POWER_FORMAT_UNRESOLVED
        self._power_format_store: Store[dict[str, Any]] = Store(
            hass,
            POWER_FORMAT_STORAGE_VERSION,
            power_format_storage_key(device_id),
        )

        # Raw API response (private, for diagnostics only)
        self._last_raw_response: dict[str, Any] = {}

        # Performance optimization: data processing cache
        self._parsed_data_cache: CoordinatorData | None = None
        self._raw_data_hash: int | None = None
        self._parsed_data_cache_timestamp: dt.datetime | None = None

        # Memory optimization: track cache sizes and cleanup
        self._cache_hit_count = 0
        self._cache_miss_count = 0
        self._last_memory_cleanup: dt.datetime | None = None

    async def _async_setup(self) -> None:
        """Load persisted state before the first refresh."""
        try:
            stored = await self._power_format_store.async_load()
        except Exception:
            _LOGGER.exception("Failed to load the stored compressor power format")
            return
        if stored and stored.get("format") == POWER_FORMAT_NATIVE_WATT:
            self._power_format = POWER_FORMAT_NATIVE_WATT

    @property
    def power_format(self) -> str:
        """Return the resolved CompPower format (unresolved or native_watt)."""
        return self._power_format

    def _latch_native_watt_power(self, raw_comp_power: float) -> None:
        """Record that this system reports CompPower in W and persist it."""
        self._power_format = POWER_FORMAT_NATIVE_WATT
        self._power_format_store.async_delay_save(
            lambda: {"format": POWER_FORMAT_NATIVE_WATT}
        )
        _LOGGER.info(
            "Raw compressor power %s W is above the reduced-scale ceiling of %s; "
            "this system reports compressor power in watts, so it will no "
            "longer be scaled",
            raw_comp_power,
            REDUCED_SCALE_MAX_RAW_COMP_POWER,
        )

    def validate_fan_mode(self, mode: str, *, continuous: bool = False) -> str:
        """
        Validate and format fan mode.

        Args:
            mode: The fan mode to validate (LOW, MED, HIGH, AUTO)
            continuous: Whether to add continuous suffix

        Returns:
            Validated and formatted fan mode string

        Raises:
            ValueError: If fan mode is invalid

        """
        try:
            # Get supported modes from coordinator data
            supported_modes = self.data["main"].get(
                "supported_fan_modes", ["LOW", "MED", "HIGH"]
            )

            # First strip any existing continuous suffix
            base_mode = mode.split("+", maxsplit=1)[0] if "+" in mode else mode
            base_mode = base_mode.split("-")[0] if "-" in base_mode else base_mode
            base_mode = base_mode.upper()

            # Validate against supported modes
            if base_mode not in supported_modes:
                base_mode = "LOW"

            # Validate against known valid modes as a safety check
            if base_mode not in VALID_FAN_MODES:
                base_mode = "LOW"

        except (KeyError, AttributeError, ValueError):
            return "LOW+CONT" if continuous else "LOW"
        else:
            return f"{base_mode}{FAN_MODE_SUFFIX_CONT}" if continuous else base_mode

    def _validate_fan_mode_response(
        self, requested_mode: str, actual_mode: str, *, continuous: bool
    ) -> bool:
        """
        Validate that the fan mode was set correctly.

        Args:
            requested_mode: The requested fan mode
            continuous: The requested continuous state
            actual_mode: The actual mode returned by the API

        Returns:
            bool: True if the mode was set correctly

        """
        base_requested = (
            requested_mode.split("+", maxsplit=1)[0].split("-", maxsplit=1)[0].upper()
        )
        base_actual = (
            actual_mode.split("+", maxsplit=1)[0].split("-", maxsplit=1)[0].upper()
        )

        is_continuous = "+CONT" in actual_mode

        mode_correct = base_requested == base_actual
        continuous_correct = continuous == is_continuous

        return mode_correct and continuous_correct

    @property
    def continuous_fan(self) -> bool:
        """Get continuous fan state."""
        return self._continuous_fan

    @continuous_fan.setter
    def continuous_fan(self, value: bool) -> None:
        """Set continuous fan state."""
        self._continuous_fan = value

    async def set_enable_zone_control(self, *, enable: bool) -> None:
        """Update the enable_zone_control status."""
        self.enable_zone_control = enable
        await self.async_request_refresh()

    async def _async_update_data(self) -> CoordinatorData:
        """Fetch data from API endpoint with enhanced caching and error handling."""
        try:
            # Check API health first
            if not self.api.is_api_healthy() and self.last_data:
                _LOGGER.warning(
                    "ActronAir API unhealthy (errors=%s); serving last known "
                    "data while attempting recovery",
                    self.api.error_count,
                )
                return self.last_data

            # After a command we bypass the response cache to guarantee a
            # fresh fetch rather than a cached pre-command snapshot.
            use_cache = not self._force_fresh_on_next_update
            self._force_fresh_on_next_update = False

            # Use the enhanced API client with caching and deduplication
            status = await self.api.get_ac_status(self.device_id, use_cache=use_cache)

            # Parse data using optimized approach with caching
            parsed_data = await self._parse_data_optimized(status)  # type: ignore[arg-type]

            # Update last known good data
            self.last_data = parsed_data

            # Periodic cache cleanup (every 5 minutes)
            await self._maybe_cleanup_cache()

        except AuthenticationError:
            await self.api.clear_all_caches()
            raise ConfigEntryAuthFailed from None

        except RateLimitError as err:
            if self.last_data:
                return self.last_data
            msg = f"Rate limit exceeded: {err}"
            raise UpdateFailed(msg) from err

        except DeviceOfflineError as err:
            if self.last_data:
                return self.last_data
            msg = f"Device offline: {err}"
            raise UpdateFailed(msg) from err

        except ApiError as err:
            return self._handle_api_error(err)

        except Exception as err:
            if self.last_data:
                return self.last_data
            msg = f"Unexpected error: {err}"
            raise UpdateFailed(msg) from err

        else:
            return parsed_data

    def _handle_api_error(self, err: ApiError) -> CoordinatorData:
        """
        Handle API errors during data update.

        Args:
            err: The ApiError that occurred

        Returns:
            Cached coordinator data if available

        Raises:
            UpdateFailed: If no cached data is available

        """
        if err.is_temporary and self.last_data:
            return self.last_data
        if err.is_client_error:
            if self.last_data:
                return self.last_data
            msg = f"Configuration error: {err}"
            raise UpdateFailed(msg) from err
        if self.last_data:
            return self.last_data
        msg = f"API communication error: {err}"
        raise UpdateFailed(msg) from err

    async def _parse_data(self, data: dict[str, Any]) -> CoordinatorData:
        """
        Parse the data from the API into structured data for entities.

        Args:
            data: Raw API response data

        Returns:
            Dict containing fully parsed data (no raw_data passthrough)

        Raises:
            UpdateFailed: If parsing fails

        """
        try:
            # Store raw response for diagnostics access only
            self._last_raw_response = data

            # Extract main data sections for easier access
            last_known_state = data.get("lastKnownState", {})
            data_sections = self._extract_data_sections(last_known_state)

            # Parse main system data
            main_data = await self._parse_main_data(data_sections)

            # Parse zone data efficiently
            zones = await self._parse_zones_data(data_sections)

            # Parse new structured sub-sections
            live_aircon_data = self._parse_live_aircon_data(data_sections)
            outdoor_unit_data = self._parse_outdoor_unit_data(data_sections)
            system_status_data = self._parse_system_status_data(
                data_sections["device_section"]
            )
            cloud_data = self._parse_cloud_data(data_sections["device_section"])
            servicing_data = self._parse_servicing_data(data_sections["device_section"])
            connection_meta = self._parse_connection_metadata(data)
            vft_data = self._parse_vft_data(data_sections)

            # Update internal state
            self._continuous_fan = main_data["fan_continuous"]

            # Construct the final result — no raw_data passthrough
            result: CoordinatorData = {  # type: ignore[assignment]
                "main": main_data,
                "zones": zones,
                "live_aircon": live_aircon_data,
                "outdoor_unit": outdoor_unit_data,
                "system_status": system_status_data,
                "cloud": cloud_data,
                "servicing": servicing_data,
                "connection_meta": connection_meta,
                "vft": vft_data,
            }

            self._apply_pending_zone_state_overrides(result)

        except Exception as e:
            msg = f"Failed to parse API response: {e}"
            raise UpdateFailed(msg) from e
        else:
            return result

    @staticmethod
    def _sync_zone_enabled_state(
        coordinator_data: CoordinatorData,
        enabled_zones: list[bool],
    ) -> None:
        """Keep main and per-zone enabled state in sync."""
        coordinator_data["main"]["EnabledZones"] = enabled_zones.copy()

        for zone_index, is_enabled in enumerate(enabled_zones, start=1):
            zone_key = f"zone_{zone_index}"
            zone_data = coordinator_data["zones"].get(zone_key)
            if zone_data is not None:
                zone_data["is_enabled"] = is_enabled

    def _apply_pending_zone_state_overrides(
        self,
        coordinator_data: CoordinatorData,
    ) -> None:
        """Apply optimistic zone state overrides until the API catches up."""
        if not self._pending_zone_state_overrides:
            return

        enabled_zones = coordinator_data["main"].get("EnabledZones")
        # Defensive: the parsed shape guarantees a list, but a malformed/partial
        # push could omit it. Guard kept; the type model can't see the runtime risk.
        if not isinstance(enabled_zones, list):  # pyright: ignore[reportUnnecessaryIsInstance]
            return  # type: ignore[unreachable]

        now = dt.datetime.now()  # noqa: DTZ005
        resolved_zone_indexes: list[int] = []

        for zone_index, (
            desired_state,
            created_at,
        ) in self._pending_zone_state_overrides.items():
            if zone_index >= len(enabled_zones):
                continue

            # Confirmed by the API — drop the override.
            if enabled_zones[zone_index] == desired_state:
                resolved_zone_indexes.append(zone_index)
                continue

            # Expired without confirmation — stop forcing it and let the API
            # value show through.
            if (now - created_at).total_seconds() >= ZONE_OVERRIDE_TTL:
                _LOGGER.debug(
                    "Zone %s state override expired without confirmation",
                    zone_index + 1,
                )
                resolved_zone_indexes.append(zone_index)
                continue

            enabled_zones[zone_index] = desired_state
            zone_key = f"zone_{zone_index + 1}"
            zone_data = coordinator_data["zones"].get(zone_key)
            if zone_data is not None:
                zone_data["is_enabled"] = desired_state

        for zone_index in resolved_zone_indexes:
            self._pending_zone_state_overrides.pop(zone_index, None)

    def _optimistically_update_zone_state(
        self,
        enabled_zones: list[bool],
    ) -> None:
        """Push an optimistic EnabledZones update to subscribed entities."""
        if not self.last_data:
            return

        main_data = self.last_data.get("main")
        zones_data = self.last_data.get("zones")
        # Defensive guard against malformed/partial state; types say redundant.
        if not isinstance(main_data, dict) or not isinstance(zones_data, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            return  # type: ignore[unreachable]

        self._sync_zone_enabled_state(self.last_data, enabled_zones)

        # Force the next refresh to re-parse raw API data rather than returning
        # a cached parsed structure that predates this optimistic change.
        self._clear_parse_cache()
        self.async_set_updated_data(self.last_data)

    def _clear_parse_cache(self) -> None:
        """Reset the parsed-data cache so the next poll re-parses raw data."""
        self._parsed_data_cache = None
        self._raw_data_hash = None
        self._parsed_data_cache_timestamp = None

    async def _async_refresh_after_command(self) -> None:
        """
        Refresh coordinator data after a state-changing command.

        Clears the parse cache and forces the next fetch to bypass the API
        response cache, so entities reflect the new state as quickly as the
        cloud makes it available rather than a stale cached snapshot.
        """
        self._clear_parse_cache()
        self._force_fresh_on_next_update = True
        await self.async_request_refresh()

    async def _parse_data_optimized(self, data: dict[str, Any]) -> CoordinatorData:
        """
        Parse data with performance optimizations and caching.

        Args:
            data: Raw API response data

        Returns:
            Parsed coordinator data

        """
        # Calculate hash of raw data for change detection
        raw_data_str = (
            str(sorted(data.items()))
            if isinstance(data, dict)  # pyright: ignore[reportUnnecessaryIsInstance]
            else str(data)
        )
        raw_data_hash = hash(raw_data_str)

        # Return cached parsed data if raw data hasn't changed AND the cache is
        # still fresh. The TTL guards against the ActronAir cloud serving an
        # unchanged (possibly stale) lastKnownState indefinitely. See issue #112.
        if (
            self._raw_data_hash == raw_data_hash
            and self._parsed_data_cache is not None
            and not self._is_parse_cache_expired()
        ):
            self._cache_hit_count += 1
            # Pending zone overrides are normally applied during a full parse;
            # apply them here too so a cache hit doesn't drop or strand them.
            self._apply_pending_zone_state_overrides(self._parsed_data_cache)
            return self._parsed_data_cache

        # Parse data using existing method
        self._cache_miss_count += 1
        parsed_data = await self._parse_data(data)

        # Cache the parsed result
        self._raw_data_hash = raw_data_hash
        self._parsed_data_cache = parsed_data
        self._parsed_data_cache_timestamp = dt.datetime.now()  # noqa: DTZ005

        # Periodic memory cleanup
        await self._maybe_cleanup_memory()

        return parsed_data

    def _is_parse_cache_expired(self) -> bool:
        """Return True when the parsed-data cache has exceeded its TTL."""
        if self._parsed_data_cache_timestamp is None:
            return True
        age = (
            dt.datetime.now()  # noqa: DTZ005
            - self._parsed_data_cache_timestamp
        ).total_seconds()
        return age >= PARSE_CACHE_TTL

    def _extract_data_sections(
        self, last_known_state: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Extract and organize data sections from API response.

        Args:
            last_known_state: The lastKnownState section from API response

        Returns:
            Dictionary with organized data sections

        """
        # Find the serial-keyed device section (e.g. "<22H09780>")
        device_section: dict[str, Any] = {}
        for key, value in last_known_state.items():
            if key.startswith("<") and key.endswith(">") and isinstance(value, dict):
                device_section = cast("dict[str, Any]", value)
                break

        return {
            "user_aircon_settings": last_known_state.get("UserAirconSettings", {}),
            "master_info": last_known_state.get("MasterInfo", {}),
            "live_aircon": last_known_state.get("LiveAircon", {}),
            "aircon_system": last_known_state.get("AirconSystem", {}),
            "indoor_unit": last_known_state.get("AirconSystem", {}).get(
                "IndoorUnit", {}
            ),
            "alerts": last_known_state.get("Alerts", {}),
            "remote_zone_info": last_known_state.get("RemoteZoneInfo", []),
            "peripherals": last_known_state.get("AirconSystem", {}).get(
                "Peripherals", []
            ),
            "nv_limits": last_known_state.get("NV_Limits", {}),
            "device_section": device_section,
        }

    async def _parse_main_data(self, data_sections: dict[str, Any]) -> MainData:
        """
        Parse main system data from API response sections.

        Args:
            data_sections: Organized data sections from API response

        Returns:
            MainData structure with parsed main system information

        """
        user_aircon_settings = data_sections["user_aircon_settings"]
        master_info = data_sections["master_info"]
        live_aircon = data_sections["live_aircon"]
        aircon_system = data_sections["aircon_system"]
        indoor_unit = data_sections["indoor_unit"]
        alerts = data_sections["alerts"]

        # Get supported modes
        supported_fan_modes: list[str]
        auto_fan_enabled = indoor_unit.get("NV_AutoFanEnabled", False)
        if auto_fan_enabled:
            supported_fan_modes = list(ADVANCE_FAN_MODES)
        else:
            fan_mode = user_aircon_settings.get("FanMode", "")
            supported_fan_modes = self._validate_fan_modes(
                indoor_unit.get("NV_SupportedFanModes", 0),
                current_fan_mode=fan_mode,
                auto_fan_enabled=auto_fan_enabled,
            )

        # Get fan mode and check for continuous state using '+CONT'
        fan_mode = user_aircon_settings.get("FanMode", "")
        is_continuous = fan_mode.endswith("+CONT")

        # Strip the continuous suffix for clean fan_mode storage
        base_fan_mode = fan_mode.split("+")[0] if "+" in fan_mode else fan_mode
        base_fan_mode = (
            base_fan_mode.split("-")[0] if "-" in base_fan_mode else base_fan_mode
        )

        # Get model number for specific handling of NEO Series WC
        model = aircon_system.get("MasterWCModel", "")
        if model in NEO_SERIES_WC:
            model = indoor_unit.get("NV_ModelNumber", "")

        # Parse hardware ModeSupport
        raw_mode_support = user_aircon_settings.get("ModeSupport")
        if isinstance(raw_mode_support, dict):
            mode_support = ModeSupport.model_validate(raw_mode_support)
            supported_hvac_modes = mode_support.supported_modes
        else:
            supported_hvac_modes = list(FALLBACK_SUPPORTED_MODES)
            if self._detect_dry_mode_support(user_aircon_settings):
                supported_hvac_modes.append("DRY")

        # Parse NV_Limits.UserSetpoint_oC
        nv_limits_raw = data_sections.get("nv_limits", {})
        user_setpoint_limits_raw: Any = (
            cast("dict[str, Any]", nv_limits_raw).get("UserSetpoint_oC", {})
            if isinstance(nv_limits_raw, dict)
            else {}
        )
        setpoint_limits = UserSetpointLimits.model_validate(
            user_setpoint_limits_raw
            if isinstance(user_setpoint_limits_raw, dict)
            else {}
        )
        zone_variance_raw = user_aircon_settings.get(
            "ZoneTemperatureSetpointVariance_oC", 0.0
        )
        try:
            zone_temp_variance = float(zone_variance_raw or 0.0)
        except (TypeError, ValueError):
            zone_temp_variance = 0.0

        # Create and validate main data structure via Pydantic v2
        raw_main_data = {
            "is_on": user_aircon_settings.get("isOn", False),
            "mode": user_aircon_settings.get("Mode", "OFF"),
            "fan_mode": fan_mode,
            "fan_continuous": is_continuous,
            "base_fan_mode": base_fan_mode,
            "supported_fan_modes": supported_fan_modes,
            "temp_setpoint_cool": user_aircon_settings.get(
                "TemperatureSetpoint_Cool_oC"
            ),
            "temp_setpoint_heat": user_aircon_settings.get(
                "TemperatureSetpoint_Heat_oC"
            ),
            "indoor_temp": master_info.get("LiveTemp_oC"),
            "indoor_humidity": self._parse_humidity(master_info.get("LiveHumidity_pc")),
            "compressor_state": live_aircon.get("CompressorMode", "OFF"),
            "EnabledZones": user_aircon_settings.get("EnabledZones", []),
            "away_mode": user_aircon_settings.get("AwayMode", False),
            "quiet_mode": user_aircon_settings.get(
                "QuietMode", user_aircon_settings.get("QuietModeEnabled", False)
            ),
            "model": model,
            "indoor_model": indoor_unit.get("NV_ModelNumber"),
            "serial_number": aircon_system.get("MasterSerial"),
            "firmware_version": aircon_system.get("MasterWCFirmwareVersion") or "",
            "filter_clean_required": alerts.get("CleanFilter", False),
            "defrosting": alerts.get("Defrosting", False),
            # Extended API coverage fields
            "turbo_mode_supported": user_aircon_settings.get("TurboMode", {}).get(
                "Supported", False
            ),
            "turbo_mode_enabled": user_aircon_settings.get("TurboMode", {}).get(
                "Enabled", False
            ),
            "after_hours_enabled": user_aircon_settings.get("AfterHours", {}).get(
                "Enabled", False
            ),
            "after_hours_duration": user_aircon_settings.get("AfterHours", {}).get(
                "Duration", 120
            ),
            "outdoor_temp": self._parse_outdoor_temp(
                master_info.get("LiveOutdoorTemp_oC"),
                live_aircon.get("OutdoorUnit", {}),
            ),
            "fast_heating": user_aircon_settings.get("isFastHeating", False),
            # Some units report the on/off state in QuietModeEnabled (#199), so
            # the key's presence, not its value, signals quiet mode support.
            "quiet_mode_supported": "QuietModeEnabled" in user_aircon_settings,
            "quiet_mode_active": user_aircon_settings.get("QuietModeActive", False),
            "service_reminder_enabled": user_aircon_settings.get(
                "ServiceReminder", {}
            ).get("Enabled", False),
            "service_reminder_time": user_aircon_settings.get(
                "ServiceReminder", {}
            ).get("Time", "NA"),
            "warnings": self._parse_warnings(live_aircon),
            "dry_mode_supported": self._detect_dry_mode_support(user_aircon_settings),
            "supported_hvac_modes": supported_hvac_modes,
            "min_temp_cool": setpoint_limits.set_cool_min,
            "max_temp_cool": setpoint_limits.set_cool_max,
            "min_temp_heat": setpoint_limits.set_heat_min,
            "max_temp_heat": setpoint_limits.set_heat_max,
            "zone_temp_variance": zone_temp_variance,
            "variance_above_cool": setpoint_limits.variance_above_cool,
            "variance_below_cool": setpoint_limits.variance_below_cool,
            "variance_above_heat": setpoint_limits.variance_above_heat,
            "variance_below_heat": setpoint_limits.variance_below_heat,
        }
        validated_main = MainDataModel.model_validate(raw_main_data).model_dump(
            by_alias=True
        )
        # Preserve original serial_number None vs string semantics
        if aircon_system.get("MasterSerial") is None:
            validated_main["serial_number"] = None
        if aircon_system.get("MasterWCFirmwareVersion") is None:
            validated_main["firmware_version"] = None  # type: ignore[typeddict-item]
        return cast("MainData", validated_main)

    async def _parse_zones_data(
        self, data_sections: dict[str, Any]
    ) -> dict[str, ZoneData]:
        """
        Parse zone data from API response sections.

        Args:
            data_sections: Organized data sections from API response

        Returns:
            Dictionary of zone data indexed by zone_id

        """
        zones: dict[str, ZoneData] = {}
        remote_zone_info = data_sections["remote_zone_info"]
        peripherals = data_sections["peripherals"]
        user_aircon_settings = data_sections["user_aircon_settings"]

        if not isinstance(remote_zone_info, list):
            return zones

        zone_list = cast("list[Any]", remote_zone_info)  # type: ignore[redundant-cast]  # needed by pyright strict
        for i, zone_raw in enumerate(zone_list):
            if i < MAX_ZONES and isinstance(zone_raw, dict):
                zone = cast("dict[str, Any]", zone_raw)
                zone_id = f"zone_{i + 1}"

                # Get zone capabilities including existence check
                capabilities = self.api.get_zone_capabilities(zone)

                if capabilities.exists:
                    # Create base zone data
                    zone_data: dict[str, Any] = {
                        "name": zone.get("NV_Title", f"Zone {i + 1}"),
                        "temp": zone.get("LiveTemp_oC"),
                        "setpoint": zone.get("TemperatureSetpoint_oC"),
                        "is_on": zone.get("CanOperate", False),
                        "capabilities": capabilities,
                        "humidity": self._parse_humidity(zone.get("LiveHumidity_pc")),
                        "is_enabled": self._get_zone_enabled(user_aircon_settings, i),
                        "temp_setpoint_cool": capabilities.target_temp_cool,
                        "temp_setpoint_heat": capabilities.target_temp_heat,
                        # Zone damper position
                        # (convert from 0-20 API scale to 0-100 percentage)
                        "damper_position": self._convert_damper_position(
                            zone.get("ZonePosition")
                        ),
                        # YourZone airflow control fields
                        "airflow_setpoint": zone.get("AirflowSetpoint"),
                        "airflow_control_enabled": zone.get(
                            "AirflowControlEnabled", False
                        ),
                        "airflow_control_locked": zone.get(
                            "AirflowControlLocked", False
                        ),
                        "zone_max_position": zone.get("ZoneMaxPosition"),
                        "zone_min_position": zone.get("ZoneMinPosition"),
                        # Controller-published zone setpoint limits
                        "min_cool_setpoint": zone.get("MinCoolSetpoint"),
                        "max_cool_setpoint": zone.get("MaxCoolSetpoint"),
                        "min_heat_setpoint": zone.get("MinHeatSetpoint"),
                        "max_heat_setpoint": zone.get("MaxHeatSetpoint"),
                        # Initialize peripheral data
                        "battery_level": None,
                        "signal_strength": None,
                        "peripheral_type": None,
                        "last_connection": None,
                        "connection_state": None,
                    }

                    # Match peripheral data by sensor serial
                    self._enrich_zone_with_peripheral(
                        zone, zone_data, capabilities, peripherals
                    )

                    validated_zone = ZoneDataModel.model_validate(zone_data)
                    dumped_zone = validated_zone.model_dump()
                    dumped_zone["capabilities"] = validated_zone.capabilities
                    zones[zone_id] = cast("ZoneData", dumped_zone)

        return zones

    @staticmethod
    def _get_zone_enabled(
        user_aircon_settings: dict[str, Any], zone_index: int
    ) -> bool:
        """Check if a zone is enabled by index."""
        enabled_zones = user_aircon_settings.get("EnabledZones", [])
        if zone_index < len(enabled_zones):
            return enabled_zones[zone_index]
        return False

    def _enrich_zone_with_peripheral(
        self,
        zone: dict[str, Any],
        zone_data: dict[str, Any],
        capabilities: ZoneCapabilities,
        peripherals: list[dict[str, Any]],
    ) -> None:
        """Enrich zone data with matching peripheral information."""
        zone_sensors = zone.get("Sensors", {})
        zone_sensor_kind = ""

        # Find device ID with case-insensitive matching
        for device_key, sensor_data in zone_sensors.items():
            if device_key.lower() == self.device_id.lower():
                zone_sensor_kind = sensor_data.get("NV_Kind", "")
                break

        # Extract serial from NV_Kind (format: "ZS: 23E01206")
        if not zone_sensor_kind.startswith("ZS: "):
            return

        zone_serial = zone_sensor_kind.replace("ZS: ", "")

        # Find matching peripheral by serial number
        for peripheral in peripherals:
            if peripheral.get("SerialNumber", "") != zone_serial:
                continue

            zone_data.update(
                {
                    "battery_level": peripheral.get("RemainingBatteryCapacity_pc"),
                    "signal_strength": peripheral.get("RSSI", {}).get("Local"),
                    "peripheral_type": peripheral.get("DeviceType"),
                    "last_connection": peripheral.get("LastConnectionTime"),
                    "connection_state": peripheral.get("ConnectionState"),
                }
            )

            # Add peripheral capabilities if present
            if peripheral.get("ControlCapabilities"):
                zone_data["capabilities"] = capabilities.model_copy(
                    update={
                        "peripheral_capabilities": peripheral.get("ControlCapabilities")
                    }
                )
            break

    def _parse_live_aircon_data(self, data_sections: dict[str, Any]) -> LiveAirconData:
        """Parse live aircon operational data."""
        live = data_sections.get("live_aircon", {})
        return cast(
            "LiveAirconData",
            {
                "system_on": live.get("SystemOn", False),
                "compressor_capacity": live.get("CompressorCapacity", 0),
                "compressor_mode": live.get("CompressorMode", "OFF"),
                "am_running_fan": live.get("AmRunningFan", False),
                "fan_rpm": live.get("FanRPM", 0),
                "fan_pwm": live.get("FanPWM", 0),
                "coil_inlet": live.get("CoilInlet"),
                "err_code": live.get("ErrCode", 0),
                "compressor_chasing_temp": live.get("CompressorChasingTemperature"),
                "compressor_live_temp": live.get("CompressorLiveTemperature"),
            },
        )

    def _parse_outdoor_unit_data(
        self, data_sections: dict[str, Any]
    ) -> OutdoorUnitData:
        """Parse outdoor unit live and system info data."""
        live = data_sections.get("live_aircon", {})
        ou_live = live.get("OutdoorUnit", {})
        aircon_system = data_sections.get("aircon_system", {})
        ou_system = aircon_system.get("OutdoorUnit", {})

        # Single-phase Inverter units can report SupplyVoltage_Vac and
        # CompPower at reduced scale (#133); other series (Classic, Aires)
        # report engineering-unit values already.  Only Inverter families are
        # candidates, to prevent over-scaling on non-NTW devices (e.g. 230 VAC
        # -> 2300 VAC on a Classic unit).  The controller model can't tell the
        # cases apart (three-phase Advance units also report NTW-1000), so
        # the Family string decides: three-phase Inverter families already
        # report CompPower in W and pass through unscaled (#189).  Some
        # single-phase units also report W (#200), so a candidate's values
        # are only scaled when their magnitude fits the reduced scale.
        family = ou_system.get("Family", "")
        reduced_scale_candidate = (
            "Inverter" in family and THREE_PHASE_FAMILY_MARKER not in family.lower()
        )

        # Handle API typos in field names
        supply_current = ou_live.get(
            "SupplyCurrentRMS_A", ou_live.get("SuppyCurrentRMS_A", 0)
        )
        supply_power = ou_live.get(
            "SupplyPowerRMS_W", ou_live.get("SuppyPowerRMS_W", 0)
        )

        # Use explicit None checks so that a genuine zero reading (e.g.
        # compressor off) is preserved as 0 and not mistaken for a missing
        # value.
        raw_voltage = ou_live.get("SupplyVoltage_Vac")
        voltage_value = _as_float(raw_voltage)
        if raw_voltage is None:
            supply_voltage: float = 0
        elif (
            reduced_scale_candidate
            and voltage_value is not None
            and 0 < voltage_value <= REDUCED_SCALE_MAX_RAW_VOLTAGE
        ):
            supply_voltage = voltage_value * SUPPLY_VOLTAGE_SCALE_FACTOR
        else:
            supply_voltage = raw_voltage

        raw_comp_power = ou_live.get("CompPower")
        comp_power_value = _as_float(raw_comp_power)
        if raw_comp_power is None:
            comp_power: float = 0
        elif (
            not reduced_scale_candidate
            or comp_power_value is None
            or self._power_format == POWER_FORMAT_NATIVE_WATT
        ):
            comp_power = raw_comp_power
        elif comp_power_value > REDUCED_SCALE_MAX_RAW_COMP_POWER:
            self._latch_native_watt_power(comp_power_value)
            comp_power = raw_comp_power
        else:
            comp_power = comp_power_value * COMP_POWER_SCALE_FACTOR

        raw_outdoor = {
            "comp_power": comp_power,
            "compressor_on": ou_live.get("CompressorOn", False),
            "comp_speed": ou_live.get("CompSpeed", 0),
            "coil_temp": ou_live.get("CoilTemp"),
            "amb_temp": ou_live.get("AmbTemp"),
            "supply_voltage": supply_voltage,
            "supply_current": supply_current,
            "supply_power": supply_power,
            "reverse_valve_position": ou_live.get("ReverseValvePosition", "Unknown"),
            "defrost_mode": ou_live.get("DefrostMode", 0),
            "drm": ou_live.get("DRM", False),
            "err_codes": [
                ou_live.get("ErrCode_1", 0),
                ou_live.get("ErrCode_2", 0),
                ou_live.get("ErrCode_3", 0),
                ou_live.get("ErrCode_4", 0),
                ou_live.get("ErrCode_5", 0),
            ],
            "family": ou_system.get("Family", ""),
            "ctrl_board_type": ou_system.get("CtrlBoardType", ""),
            "capacity_kw": ou_system.get("Capacity_kW", 0),
            "model_number": ou_system.get("ModelNumber", ""),
            "software_version": ou_system.get("SoftwareVersion", ""),
            "serial_number": ou_system.get("SerialNumber", ""),
        }
        return cast(
            "OutdoorUnitData",
            OutdoorUnitDataModel.model_validate(raw_outdoor).model_dump(),
        )

    @staticmethod
    def _parse_system_status_data(device_section: dict[str, Any]) -> SystemStatusData:
        """Parse device system status data from serial-keyed section."""
        sys_status = device_section.get("SystemStatus_Local", {})
        wifi = sys_status.get("WiFi", {})
        sensor_inputs = sys_status.get("SensorInputs", {})
        shtc1 = sensor_inputs.get("SHTC1", {})

        return cast(
            "SystemStatusData",
            {
                "uptime_seconds": sys_status.get("Uptime_s", 0),
                "board_temp": shtc1.get("Temperature_oC"),
                "wifi_strength": sys_status.get("WifiStrength_of3"),
                "wifi_ssid": wifi.get("ApSSID", "Unknown"),
                "wifi_channel": str(wifi.get("RFChannel", "Unknown")),
                "wifi_firmware": wifi.get("FirmwareVersion", "Unknown"),
                "wifi_hw_errors": wifi.get("HardwareErrorCount", 0),
            },
        )

    @staticmethod
    def _parse_cloud_data(device_section: dict[str, Any]) -> CloudConnectionData:
        """Parse cloud connection data from serial-keyed section."""
        cloud = device_section.get("Cloud", {})
        connection = cloud.get("Connection", {})
        error_counts = connection.get("ErrorCount", {})

        return cast(
            "CloudConnectionData",
            {
                "connection_state": cloud.get("ConnectionState", "Unknown"),
                "session_uptime": connection.get("UpTime", {}).get(
                    "CurrentSession_s", 0
                ),
                "sent_packets": cloud.get("SentPackets", 0),
                "received_packets": cloud.get("ReceivedPackets", 0),
                "failed_sent_packets": cloud.get("FailedSentPackets", 0),
                "session_count_since_reset": connection.get("SessionCount", {}).get(
                    "SinceLastMCUReset", 0
                ),
                "dns_failures": error_counts.get("DNSFailures", 0),
                "aborted_sockets": error_counts.get("AbortedSockets", 0),
            },
        )

    @staticmethod
    def _parse_servicing_data(device_section: dict[str, Any]) -> ServicingData:
        """Parse servicing and error history data."""
        servicing = device_section.get("Servicing", {})
        return cast(
            "ServicingData",
            {
                "error_history": servicing.get("NV_ErrorHistory", []),
                "event_history": servicing.get("NV_AC_EventHistory", []),
            },
        )

    @staticmethod
    def _parse_connection_metadata(data: dict[str, Any]) -> ConnectionMetadata:
        """Parse top-level connection metadata from raw API response."""
        return cast(
            "ConnectionMetadata",
            {
                "is_online": data.get("isOnline", False),
                "last_status_update": data.get("lastStatusUpdate", "Unknown"),
                "time_since_last_contact": data.get("timeSinceLastContact", "Unknown"),
            },
        )

    @staticmethod
    def _parse_vft_data(data_sections: dict[str, Any]) -> VFTData:
        """Parse variable fan technology data."""
        user_settings = data_sections.get("user_aircon_settings", {})
        vft = user_settings.get("VFT", {})
        return cast(
            "VFTData",
            {
                "supported": vft.get("Supported", False),
                "airflow": vft.get("Airflow", 0.0),
            },
        )

    def get_diagnostics_snapshot(self) -> dict[str, Any]:
        """Return raw API response for diagnostics only."""
        return self._last_raw_response

    async def _handle_push_update(self, payload: dict[str, Any], kind: str) -> None:
        """Apply a realtime push payload and publish to entities."""
        prior_raw = self._last_raw_response
        try:
            # Push payloads come in two shapes, both incremental:
            #   * full-status carries a (possibly partial) "lastKnownState".
            #   * status-change carries an "event" of flattened path→value
            #     pairs (e.g. "UserAirconSettings.Mode": "COOL"). See #112.
            # Apply either onto the last known full state so a partial push
            # never drops sections (notably RemoteZoneInfo) and so the parser
            # actually sees the changed values.
            prior_state: dict[str, Any] = cast(
                "dict[str, Any]", prior_raw.get("lastKnownState") or {}
            )
            event = payload.get("event")
            incoming_state = payload.get("lastKnownState")
            if isinstance(incoming_state, dict):
                incoming = cast("dict[str, Any]", incoming_state)
                merged_state: dict[str, Any] = (
                    deep_merge(prior_state, incoming) if prior_state else incoming
                )
            elif isinstance(event, dict):
                event_dict = cast("dict[str, Any]", event)
                event_type = event_dict.get("type")
                if event_type == "full-status-broadcast":
                    # Neo /mwc/full-status wraps the nested state dict inside
                    # payload["event"] with type="full-status-broadcast".
                    # Merge it recursively rather than treating keys as
                    # flat dotted paths.
                    full_event_state = {
                        k: v for k, v in event_dict.items() if k != "type"
                    }
                    merged_state = (
                        deep_merge(prior_state, full_event_state)
                        if prior_state
                        else full_event_state
                    )
                else:
                    merged_state = apply_event_paths(prior_state, event_dict)
            elif payload.get("type") == "full-status-broadcast":
                # Que sends full-status-broadcast with state keys flat at top level
                full_event_state = {
                    k: v
                    for k, v in payload.items()
                    if k not in _QUE_BROADCAST_METADATA_KEYS
                }
                merged_state = (
                    deep_merge(prior_state, full_event_state)
                    if prior_state
                    else full_event_state
                )
            elif payload.get("type") == "status-change-broadcast":
                # Que sends status-change-broadcast with delta flat at top level
                delta = {
                    k: v
                    for k, v in payload.items()
                    if k not in _QUE_BROADCAST_METADATA_KEYS
                }
                merged_state = apply_event_paths(prior_state, delta)
            else:
                # Tolerate a bare-state payload without a recognised wrapper.
                bare = {k: v for k, v in payload.items() if k != "lastKnownState"}
                merged_state = deep_merge(prior_state, bare) if prior_state else bare
            merged_raw: dict[str, Any] = {
                **prior_raw,
                "lastKnownState": merged_state,
            }
            _LOGGER.debug(
                "Push update (kind=%s): payload keys=%s",
                kind,
                sorted(payload.keys()),
            )

            # Push data is authoritative; persist the merged raw and bypass the
            # stale-hash parse shortcut.
            self._last_raw_response = merged_raw
            self._clear_parse_cache()
            parsed = await self._parse_data_optimized(merged_raw)  # type: ignore[arg-type]

            # Safeguard: never let a partial push blank a previously-populated
            # system. If the merged parse drops all zones we used to have, treat
            # the push as suspect, roll back, and keep the last good state.
            if (
                not parsed.get("zones")
                and isinstance(self.last_data, dict)
                and self.last_data.get("zones")
            ):
                _LOGGER.warning(
                    "Ignoring push update that would clear all zones "
                    "(kind=%s, state keys=%s)",
                    kind,
                    sorted(merged_state.keys()),
                )
                self._last_raw_response = prior_raw
                self._clear_parse_cache()
                return

            self.last_data = parsed
            self.async_set_updated_data(parsed)
        except Exception:
            _LOGGER.exception("Failed to apply realtime push update; ignoring")
            self._last_raw_response = prior_raw
            self._clear_parse_cache()

    async def async_start_push(self) -> None:
        """Discover the broker and start the push transport (non-fatal)."""
        if not self.enable_push or self._push_transport is not None:
            return
        try:
            details = await self.api.get_realtime_connection_details(self.device_id)
        except ActronAirNeoError as err:
            _LOGGER.warning("Realtime push discovery failed (%s); polling only", err)
            return
        if details is None:
            _LOGGER.warning("No realtime connection details returned; polling only")
            return
        # The user id is baked into every MQTT topic. If discovery didn't
        # provide one the topics become "actron-cloud/unknown/..." and we
        # silently receive nothing — surface that rather than failing quietly.
        if not details.user_id or details.user_id == "unknown":
            _LOGGER.warning(
                "Realtime discovery returned no user id; push topics would be "
                "invalid and receive no messages — falling back to polling only"
            )
            return
        # Build the MQTT SSL context off the event loop (cached in hass.data).
        # The broker sends a leaf-only cert and is reached by IP, so this
        # context bundles the missing Sectigo intermediate and disables
        # hostname checking while keeping chain verification on. See #112.
        ssl_context = await async_get_mqtt_ssl_context(self.hass)
        username = ""
        with contextlib.suppress(Exception):
            maybe_email: Any = self.api.get_account_email()
            if inspect.isawaitable(maybe_email):
                resolved_email = await maybe_email
                if isinstance(resolved_email, str):
                    username = resolved_email
            elif isinstance(maybe_email, str):
                username = maybe_email
        client_id = f"ha-{self.device_id.lower()}-{details.user_id}"
        transport = create_push_transport(
            platform=self.api.platform,
            details=details,
            serial=self.device_id,
            token_provider=self.api.get_realtime_access_token,
            on_update=self._handle_push_update,
            ssl_context=ssl_context,
            username=username,
            client_id=client_id,
        )
        if transport is None:
            return
        self._push_transport = transport
        self._push_task = self.hass.async_create_background_task(
            transport.start(), name=f"{DOMAIN}_push_{self.device_id}"
        )
        _LOGGER.debug("Realtime push started for %s", self.device_id)

    async def async_stop_push(self) -> None:
        """Stop the push transport and cancel its background task."""
        if self._push_transport is not None:
            await self._push_transport.stop()
            self._push_transport = None
        if self._push_task is not None:
            self._push_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._push_task
            self._push_task = None

    @property
    def push_transport(self) -> PushTransport | None:
        """Return the active push transport instance, if any."""
        return self._push_transport

    @property
    def push_state(self) -> PushState:
        """Return the current push health state for diagnostics."""
        if not self.enable_push or self._push_transport is None:
            return PushState.DISABLED
        last = self._push_transport.last_heartbeat
        if (
            self._push_transport.state is PushState.CONNECTED
            and last is not None
            and (_now_matching(last) - last).total_seconds() > HEARTBEAT_STALE_AFTER
        ):
            return PushState.STALE
        return self._push_transport.state

    @property
    def api_error_count(self) -> int:
        """Return the API error count."""
        return self.api.error_count

    @property
    def last_successful_api_request(self) -> dt.datetime | None:
        """Return the timestamp of the last successful API request."""
        return self.api.last_successful_request

    @property
    def api_cache_size(self) -> int:
        """Return the number of entries in the API response cache."""
        return len(self.api.response_cache)

    def supports_power_monitoring(self) -> bool:
        """Check if the outdoor unit supports power monitoring."""
        if not self.data:
            return False
        ou = self.data["outdoor_unit"]
        family = ou.get("family", "")
        ctrl_board_type = ou.get("ctrl_board_type", "")

        # Fixed Speed Classic units with Type 100 controllers don't support
        # power monitoring
        if "Fixed Speed" in family and "Type 100" in ctrl_board_type:
            return False

        # Check if power fields have meaningful values
        comp_power = ou.get("comp_power", 0)
        supply_voltage = ou.get("supply_voltage", 0)
        supply_current = ou.get("supply_current", 0)
        compressor_on = ou.get("compressor_on", False)

        if (
            (comp_power and comp_power > 0)
            or (supply_voltage and supply_voltage > 0)
            or (supply_current and supply_current > 0)
        ):
            return True

        # Family-based heuristic for units that may not report live data
        # at first poll but are known to support power monitoring
        if family and "Fixed Speed" not in family:
            return compressor_on

        return False

    async def _maybe_cleanup_cache(self) -> None:
        """Perform periodic cache cleanup if needed."""
        now = dt.datetime.now()  # noqa: DTZ005

        # Cleanup every 5 minutes
        if (
            self._last_cache_cleanup is None
            or (now - self._last_cache_cleanup).total_seconds() > 300  # noqa: PLR2004
        ):
            await self.api.cleanup_expired_cache()
            self._last_cache_cleanup = now

    async def _maybe_cleanup_memory(self) -> None:
        """Perform periodic memory optimization cleanup."""
        now = dt.datetime.now()  # noqa: DTZ005

        # Memory cleanup every 10 minutes
        if (
            self._last_memory_cleanup is None
            or (now - self._last_memory_cleanup).total_seconds() > 600  # noqa: PLR2004
        ):
            # Clear parsed data cache if we have too many cache misses
            cache_hit_rate = self._cache_hit_count / max(
                1, self._cache_hit_count + self._cache_miss_count
            )

            if cache_hit_rate < 0.3:  # noqa: PLR2004
                self._clear_parse_cache()

            # Reset counters periodically
            if self._cache_hit_count + self._cache_miss_count > 1000:  # noqa: PLR2004
                self._cache_hit_count = 0
                self._cache_miss_count = 0

            self._last_memory_cleanup = now

    def _validate_fan_modes(
        self,
        modes: Any,
        *,
        current_fan_mode: str | None = None,
        auto_fan_enabled: bool = False,
    ) -> list[str]:
        """
        Validate and normalize supported fan modes.

        Note on Actron Quirks:
        - NV_SupportedFanModes is a bitmap where:
            1=LOW, 2=MED, 4=HIGH, 8=AUTO
        - Some devices omit HIGH from NV_SupportedFanModes even though
            they support it. If we detect HIGH mode in current settings,
            we add it to supported modes regardless of bitmap.
        - When in doubt, we fall back to [LOW, MED, HIGH] as defaults.
        """
        default_modes = ["LOW", "MED", "HIGH"]

        try:
            if isinstance(modes, int):
                return self._decode_fan_mode_bitmap(
                    modes,
                    default_modes,
                    current_fan_mode=current_fan_mode,
                    auto_fan_enabled=auto_fan_enabled,
                )

            return self._parse_fan_mode_list(modes, default_modes)

        except (KeyError, TypeError, ValueError):
            return default_modes

    @staticmethod
    def _decode_fan_mode_bitmap(
        modes: int,
        default_modes: list[str],
        *,
        current_fan_mode: str | None = None,
        auto_fan_enabled: bool = False,
    ) -> list[str]:
        """
        Decode fan mode bitmap value from the API.

        Args:
            modes: Bitmap integer (1=LOW, 2=MED, 4=HIGH, 8=AUTO)
            default_modes: Fallback modes if decoding fails
            current_fan_mode: The current fan mode string from the API
            auto_fan_enabled: Whether AUTO fan mode is enabled

        Returns:
            List of supported fan mode strings

        """
        # Extract base mode (strip +CONT suffix)
        current_mode = current_fan_mode.split("+")[0] if current_fan_mode else None

        # Process bitmap
        supported: list[str] = []
        if modes & 1:
            supported.append("LOW")
        if modes & 2:
            supported.append("MED")
        if modes & 4:
            supported.append("HIGH")
        if modes & 8 and auto_fan_enabled:
            supported.append("AUTO")

        # Use defaults if HIGH mode active or basic modes set without AUTO
        if current_mode == "HIGH" or (modes & 0x03 and not (modes & 0x08)):
            return default_modes

        return supported or default_modes

    @staticmethod
    def _parse_fan_mode_list(modes: Any, default_modes: list[str]) -> list[str]:
        """
        Parse fan modes from string, list, or other formats.

        Args:
            modes: Fan mode input (string, list, or other)
            default_modes: Fallback modes

        Returns:
            List of valid fan mode strings

        """
        valid_modes = {"LOW", "MED", "HIGH", "AUTO"}

        if not modes:
            return default_modes

        if isinstance(modes, str):
            modes = [m.strip().upper() for m in modes.split(",")]
        elif isinstance(modes, (list, tuple)):
            items = cast("list[Any] | tuple[Any, ...]", modes)  # type: ignore[redundant-cast]  # needed by pyright strict
            modes = [str(m).strip().upper() for m in items]

        supported = [m for m in modes if m in valid_modes]
        return supported or default_modes

    def get_zone_peripheral(self, zone_id: str) -> PeripheralData | None:
        """Get peripheral data for a specific zone by matching serial numbers."""
        try:
            zone_index = int(zone_id.split("_")[1]) - 1

            # Read from stored raw response (not from coordinator.data)
            last_known_state = self._last_raw_response.get("lastKnownState", {})

            # Get zone sensor info from RemoteZoneInfo
            remote_zone_info = last_known_state.get("RemoteZoneInfo", [])
            if zone_index >= len(remote_zone_info):
                return None

            zone_info = remote_zone_info[zone_index]
            zone_sensors = zone_info.get("Sensors", {})
            zone_sensor_kind = ""

            # Find device ID with case-insensitive matching
            for device_key, sensor_data in zone_sensors.items():
                if device_key.lower() == self.device_id.lower():
                    zone_sensor_kind = sensor_data.get("NV_Kind", "")
                    break

            # Extract serial from NV_Kind (format: "ZS: 23E01206")
            if not zone_sensor_kind.startswith("ZS: "):
                return None  # Not a wireless sensor

            zone_serial = zone_sensor_kind.replace("ZS: ", "")

            # Find matching peripheral by serial number
            peripherals = last_known_state.get("AirconSystem", {}).get(
                "Peripherals", []
            )

            for peripheral in peripherals:
                peripheral_serial = peripheral.get("SerialNumber", "")
                if peripheral_serial == zone_serial:
                    return cast("PeripheralData", peripheral)

        except (KeyError, ValueError, IndexError):
            pass
        return None

    def get_zone_last_updated(self, zone_id: str) -> str | None:
        """Get last update time for a specific zone."""
        try:
            peripheral_data = self.get_zone_peripheral(zone_id)
        except (KeyError, ValueError, IndexError):
            return None
        else:
            return (
                peripheral_data.get("LastConnectionTime") if peripheral_data else None
            )

    async def set_hvac_mode(self, hvac_mode: str) -> None:
        """Set HVAC mode."""
        if hvac_mode == HVACMode.OFF:
            command = self.api.create_command("OFF")
        else:
            command = self.api.create_command("CLIMATE_MODE", mode=hvac_mode)
        await self.api.send_command(self.device_id, command)
        await self._async_refresh_after_command()

    async def turn_on(self) -> None:
        """Turn the AC system on."""
        command = self.api.create_command("ON")
        await self.api.send_command(self.device_id, command)
        await self._async_refresh_after_command()

    async def turn_off(self) -> None:
        """Turn the AC system off."""
        command = self.api.create_command("OFF")
        await self.api.send_command(self.device_id, command)
        await self._async_refresh_after_command()

    async def set_temperature(self, temperature: float, *, is_cooling: bool) -> None:
        """Set temperature."""
        command = self.api.create_command(
            "SET_TEMP", temp=temperature, is_cool=is_cooling
        )
        await self.api.send_command(self.device_id, command)
        await self._async_refresh_after_command()

    async def set_fan_mode(self, mode: str, *, continuous: bool | None = None) -> None:
        """
        Set fan mode with state tracking, validation and retry.

        Args:
            mode: The fan mode to set (LOW, MED, HIGH, AUTO)
            continuous: Whether to enable continuous fan mode.
                If None, maintains current state.

        Raises:
            ApiError: If communication with the API fails
            ValueError: If the fan mode is invalid
            RateLimitError: If too many requests are made

        """
        # If continuous is not specified, maintain current state
        if continuous is None:
            current_mode = self.data["main"].get("fan_mode", "")
            continuous = current_mode.endswith("+CONT")

        # Rate limiting check
        async with self._fan_mode_change_lock:
            await self._throttle_fan_mode_change()

            validated_mode = self.validate_fan_mode(mode, continuous=continuous)

            await self._send_fan_mode_with_retry(validated_mode, continuous=continuous)

    async def _throttle_fan_mode_change(self) -> None:
        """Apply rate limiting for fan mode changes."""
        if self._last_fan_mode_change:
            elapsed = (
                dt.datetime.now()  # noqa: DTZ005
                - self._last_fan_mode_change
            ).total_seconds()
            if elapsed < self._min_fan_mode_interval:
                wait_time = self._min_fan_mode_interval - elapsed
                await asyncio.sleep(wait_time)

    async def _send_fan_mode_with_retry(
        self, validated_mode: str, *, continuous: bool
    ) -> None:
        """
        Send fan mode command with verification retry.

        Sends the command via the API (which handles its own transport-level
        retries) then verifies continuous mode was applied correctly.

        Args:
            validated_mode: The validated fan mode string
            continuous: Whether continuous fan mode is enabled

        """
        max_verify_attempts = 3
        for attempt in range(max_verify_attempts):
            command = self.api.create_command("FAN_MODE", mode=validated_mode)
            await self.api.send_command(self.device_id, command)

            # Update state tracking
            self._last_fan_mode_change = (
                dt.datetime.now()  # noqa: DTZ005
            )
            self._continuous_fan = continuous

            # Force immediate refresh (blocking to ensure fresh data
            # before verification). Bypass both caches so verification reads
            # genuinely fresh state rather than a cached pre-command snapshot.
            self._clear_parse_cache()
            self._force_fresh_on_next_update = True
            await self.async_refresh()

            # Verify the change
            new_mode = self.data["main"].get("fan_mode", "")

            # Validate continuous mode was set correctly
            if continuous and "+CONT" not in new_mode:
                if attempt < max_verify_attempts - 1:
                    await asyncio.sleep(2**attempt)
                    continue
                _LOGGER.warning(
                    "Failed to set continuous mode after %d attempts",
                    max_verify_attempts,
                )

            break

    async def set_zone_temperature(
        self,
        zone_id: str,
        temperature: float | None = None,
        *,
        target_cool: float | None = None,
        target_heat: float | None = None,
    ) -> None:
        """
        Set temperature for a specific zone with comprehensive validation.

        Supports two calling conventions:
        - Single target: ``set_zone_temperature(zone_id, temperature=22.0)``
        - Separate targets: ``set_zone_temperature(zone_id, target_cool=24.0,
          target_heat=20.0)``

        Args:
            zone_id: Identifier for the zone (e.g. ``"zone_1"``)
            temperature: Single target temperature (mutually exclusive with
                target_cool/target_heat)
            target_cool: Cooling setpoint (use with target_heat)
            target_heat: Heating setpoint (use with target_cool)

        Raises:
            ZoneError: If zone-specific validation fails
            ConfigurationError: If zone control is disabled
            ApiError: If API communication fails

        """
        if not self.enable_zone_control:
            msg = "Zone control is not enabled"
            raise ConfigurationError(msg, config_key="enable_zone_control")

        if not self.last_data:
            msg = "No system data available"
            raise ZoneError(msg, zone_id=zone_id)

        zones_data = self.last_data.get("zones", {})
        zone_data = zones_data.get(zone_id)

        if not zone_data:
            msg = f"Zone {zone_id} not found"
            raise ZoneError(msg, zone_id=zone_id)

        # Note: We allow setting temperature for disabled zones as the
        # ActronAir API supports this. It's useful for pre-setting
        # temperatures before enabling zones.

        # Validate temperature range for all provided values
        for temp_val in [
            t for t in [temperature, target_cool, target_heat] if t is not None
        ]:
            if not (MIN_TEMP <= temp_val <= MAX_TEMP):
                msg = (
                    f"Temperature {temp_val} outside "
                    f"valid range [{MIN_TEMP}, {MAX_TEMP}]"
                )
                raise ZoneError(msg, zone_id=zone_id)

        # Check zone capabilities
        capabilities = zone_data.get("capabilities")
        if not capabilities or not capabilities.has_temp_control:
            msg = f"Zone {zone_id} does not support temperature control"
            raise ZoneError(msg, zone_id=zone_id)

        zone_index = int(zone_id.split("_")[1]) - 1

        # Delegate to the API client which handles locking and
        # command construction for both single and separate targets.
        await self.api.set_zone_temperature(
            zone_index=zone_index,
            temperature=temperature,
            target_cool=target_cool,
            target_heat=target_heat,
        )
        await self._async_refresh_after_command()

    async def set_zone_state(self, zone_id: str | int, *, enable: bool) -> None:
        """
        Set zone state.

        Args:
            zone_id: Zone ID string ('zone_1') or direct index (0-7)
            enable: True to enable zone, False to disable

        """
        # Handle both string zone_id and direct integer index
        if isinstance(zone_id, str):
            zone_index = int(zone_id.split("_")[1]) - 1
        else:
            zone_index = int(zone_id)

        async with self._zone_state_change_lock:
            # Use current data if available, otherwise fetch fresh.
            if self.last_data and "main" in self.last_data:
                current_zone_status = self.last_data["main"]["EnabledZones"]
            else:
                current_zone_status = await self.api.get_zone_statuses()

            modified_statuses = current_zone_status.copy()

            # Preserve earlier optimistic writes so rapid successive updates send
            # the full cumulative zone array rather than a stale snapshot.
            for (
                pending_zone_index,
                (pending_state, _created_at),
            ) in self._pending_zone_state_overrides.items():
                if pending_zone_index < len(modified_statuses):
                    modified_statuses[pending_zone_index] = pending_state

            # Ensure zone_index is within bounds.
            self._validate_zone_index(zone_index, len(modified_statuses))
            modified_statuses[zone_index] = enable

            command = self.api.create_command("SET_ZONE_STATE", zones=modified_statuses)
            await self.api.send_command(self.device_id, command)

            self._pending_zone_state_overrides[zone_index] = (
                enable,
                dt.datetime.now(),  # noqa: DTZ005
            )
            self._optimistically_update_zone_state(modified_statuses)

        await self._async_refresh_after_command()

    @staticmethod
    def _validate_zone_index(zone_index: int, max_zones: int) -> None:
        """
        Validate zone index is within bounds.

        Args:
            zone_index: The zone index to validate
            max_zones: Maximum number of zones

        Raises:
            ValueError: If zone index is out of range

        """
        if not (0 <= zone_index < max_zones):
            msg = f"Zone index {zone_index} out of range"
            raise ValueError(msg)

    async def set_zone_airflow(self, zone_index: int, airflow_percentage: int) -> None:
        """Set zone airflow percentage (YourZone control)."""
        await self.api.set_zone_airflow(zone_index, airflow_percentage)
        await self._async_refresh_after_command()

    async def set_climate_mode(self, mode: str) -> None:
        """Set climate mode for all zones."""
        command = self.api.create_command("CLIMATE_MODE", mode=mode)
        await self.api.send_command(self.device_id, command)
        await self._async_refresh_after_command()

    async def set_away_mode(self, *, state: bool) -> None:
        """Set away mode."""
        await self.api.set_away_mode(state=state)
        await self._async_refresh_after_command()

    async def set_quiet_mode(self, *, state: bool) -> None:
        """Set quiet mode."""
        await self.api.set_quiet_mode(state=state)
        await self._async_refresh_after_command()

    async def set_turbo_mode(self, *, state: bool) -> None:
        """Set turbo mode."""
        await self.api.set_turbo_mode(state=state)
        await self._async_refresh_after_command()

    async def set_after_hours(self, *, enabled: bool) -> None:
        """Set after hours mode."""
        await self.api.set_after_hours(enabled=enabled)
        await self._async_refresh_after_command()

    async def set_after_hours_duration(self, duration: int) -> None:
        """Set after hours duration in minutes."""
        await self.api.set_after_hours_duration(duration)
        await self._async_refresh_after_command()

    async def force_update(self) -> None:
        """Force an immediate update of the device data."""
        await self.api.clear_all_caches()
        self._clear_parse_cache()
        self._force_fresh_on_next_update = True
        await self.async_refresh()

    async def invalidate_cache(self) -> None:
        """Invalidate cached data to force fresh API calls."""
        await self.api.invalidate_status_cache(self.device_id)

    async def cleanup_expired_cache(self) -> None:
        """Clean up expired cache entries."""
        await self.api.cleanup_expired_cache()

    def get_cache_stats(self) -> dict[str, Any]:
        """
        Get cache statistics for monitoring.

        Returns:
            Dictionary with cache statistics

        """
        return {
            "api_health": self.api.is_api_healthy(),
            "last_successful_request": self.api.last_successful_request,
            "error_count": self.api.error_count,
            "has_cached_status": self.api.cached_status is not None,
            "coordinator_has_data": self.last_data is not None,
        }

    def get_performance_stats(self) -> dict[str, Any]:
        """
        Get performance statistics for monitoring.

        Returns:
            Dictionary with performance statistics

        """
        total_requests = self._cache_hit_count + self._cache_miss_count
        cache_hit_rate = (self._cache_hit_count / max(1, total_requests)) * 100

        return {
            "cache_hit_count": self._cache_hit_count,
            "cache_miss_count": self._cache_miss_count,
            "cache_hit_rate_percent": round(cache_hit_rate, 1),
            "total_parse_requests": total_requests,
            "has_parsed_cache": self._parsed_data_cache is not None,
            "last_cache_cleanup": self._last_cache_cleanup,
            "last_memory_cleanup": self._last_memory_cleanup,
            "zone_preset_count": len(self.zone_preset_manager.get_all_presets())
            if self.zone_preset_manager
            else 0,
        }

    # Enhanced Zone Management Methods

    async def async_initialize_zone_management(self) -> None:
        """Initialize zone management components."""
        try:
            await self.zone_preset_manager.async_load()
        except Exception:
            _LOGGER.exception("Failed to initialize zone management")

    async def async_create_zone_preset_from_current(
        self, name: str, description: str = ""
    ) -> None:
        """
        Create a zone preset from current zone states.

        Args:
            name: Preset name
            description: Optional description

        Raises:
            ConfigurationError: If preset creation fails

        """
        if not self.last_data:
            msg = "No zone data available"
            raise ConfigurationError(msg)

        zones_config: dict[str, dict[str, Any]] = {}
        for zone_id, zone_data in self.last_data["zones"].items():
            zones_config[zone_id] = {
                "enabled": zone_data["is_enabled"],
                "temp_cool": zone_data.get("temp_setpoint_cool"),
                "temp_heat": zone_data.get("temp_setpoint_heat"),
            }

        await self.zone_preset_manager.async_create_preset(
            name, zones_config, description
        )

    async def async_apply_zone_preset(self, preset_name: str) -> None:
        """
        Apply a zone preset.

        Args:
            preset_name: Name of preset to apply

        Raises:
            ConfigurationError: If preset not found or fails

        """
        preset = self.zone_preset_manager.get_preset(preset_name)
        if not preset:
            msg = f"Preset '{preset_name}' not found"
            raise ConfigurationError(msg)

        if not self.enable_zone_control:
            msg = "Zone control is not enabled"
            raise ConfigurationError(msg)

        # Apply zone states
        for zone_id, zone_config in preset.zones.items():
            try:
                if "enabled" in zone_config:
                    await self.set_zone_state(zone_id, enable=zone_config["enabled"])

                # Set temperatures if zone supports it
                if self.last_data and zone_id in self.last_data["zones"]:
                    await self._apply_zone_preset_temps(zone_id, zone_config)

            except Exception:
                _LOGGER.exception("Failed to apply preset to zone %s", zone_id)

        await self.async_request_refresh()

    async def _apply_zone_preset_temps(
        self, zone_id: str, zone_config: dict[str, Any]
    ) -> None:
        """
        Apply temperature settings from a zone preset.

        Args:
            zone_id: The zone to apply temperatures to
            zone_config: Zone configuration from preset

        """
        if not self.last_data:
            return

        zone_data = self.last_data["zones"].get(zone_id)
        if not zone_data:
            return

        capabilities = zone_data.get("capabilities")
        if not capabilities or not capabilities.has_temp_control:
            return

        if zone_config.get("temp_cool") is not None:
            await self.set_zone_temperature(
                zone_id,
                target_cool=zone_config["temp_cool"],
            )
        if zone_config.get("temp_heat") is not None:
            await self.set_zone_temperature(
                zone_id,
                target_heat=zone_config["temp_heat"],
            )

    async def async_bulk_zone_operation(
        self,
        operation: str,
        zones: list[str],
        **kwargs: Any,
    ) -> list[dict[str, str]]:
        """
        Perform bulk operations on multiple zones.

        Args:
            operation: Operation type ('enable', 'disable', 'set_temperature')
            zones: List of zone IDs
            **kwargs: Additional operation parameters

        Raises:
            ConfigurationError: If zone control disabled or invalid op
            ZoneError: If zone operation fails

        Returns:
            List of result dicts with zone_id and status

        """
        if not self.enable_zone_control:
            msg = "Zone control is not enabled"
            raise ConfigurationError(msg)

        valid_operations = {"enable", "disable", "set_temperature"}
        if operation not in valid_operations:
            msg = f"Invalid operation: {operation}"
            raise ConfigurationError(msg)

        results: list[dict[str, str]] = []
        for zone_id in zones:
            try:
                result = await self._execute_bulk_zone_op(operation, zone_id, **kwargs)
                results.append(result)
            except Exception:  # noqa: BLE001
                results.append(
                    {
                        "zone_id": zone_id,
                        "status": "error",
                        "error": "operation failed",
                    }
                )

        await self.async_request_refresh()
        return results

    async def _execute_bulk_zone_op(
        self,
        operation: str,
        zone_id: str,
        **kwargs: Any,
    ) -> dict[str, str]:
        """
        Execute a single bulk zone operation.

        Args:
            operation: The operation to perform
            zone_id: Target zone ID
            **kwargs: Additional parameters

        Returns:
            Result dict with zone_id and status

        """
        if operation == "enable":
            await self.set_zone_state(zone_id, enable=True)
        elif operation == "disable":
            await self.set_zone_state(zone_id, enable=False)
        elif operation == "set_temperature":
            temperature = kwargs.get("temperature")
            target_cool = kwargs.get("target_cool")
            target_heat = kwargs.get("target_heat")
            if temperature is None and target_cool is None and target_heat is None:
                return {
                    "zone_id": zone_id,
                    "status": "error",
                    "error": "No temperature provided",
                }
            await self.set_zone_temperature(
                zone_id,
                temperature=temperature,
                target_cool=target_cool,
                target_heat=target_heat,
            )
        return {"zone_id": zone_id, "status": "success"}

    def _convert_damper_position(self, api_position: int | None) -> int:
        """
        Convert damper position from API scale (0-20) to percentage.

        The ActronAir Neo API returns damper positions in a 0-20
        scale. This converts to 0-100 percentage for Home Assistant.

        Args:
            api_position: Raw damper position from API (0-20), or None

        Returns:
            Damper position as percentage (0-100), or 0 if invalid

        """
        if api_position is None:
            return 0

        try:
            # Clamp to valid range to handle unexpected values
            api_position = max(0, min(20, int(api_position)))
            percentage = (api_position * 100) // 20
            return min(100, percentage)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _parse_outdoor_temp(
        raw_value: float | None,
        outdoor_unit: dict[str, Any] | None = None,
    ) -> float | None:
        """
        Parse outdoor temperature, filtering sentinel values.

        The API returns 3000.0 for LiveOutdoorTemp_oC when the outdoor
        temperature sensor is unavailable (common on Classic series units).
        In that case, fall back to OutdoorUnit.AmbTemp from LiveAircon,
        but only when the outdoor unit's ambient sensor is healthy
        (AmbientSensErr is False).

        Args:
            raw_value: Raw temperature from MasterInfo.LiveOutdoorTemp_oC
            outdoor_unit: LiveAircon.OutdoorUnit dict (contains AmbTemp
                and AmbientSensErr)

        Returns:
            Temperature in Celsius, or None if unavailable

        """
        if raw_value is not None and raw_value < OUTDOOR_TEMP_UNAVAILABLE:
            return raw_value
        # Fall back to outdoor unit ambient sensor only if no sensor error
        if outdoor_unit and not outdoor_unit.get("AmbientSensErr", True):
            amb_temp = outdoor_unit.get("AmbTemp")
            if amb_temp is not None:
                return amb_temp
        return None

    @staticmethod
    def _parse_humidity(raw_value: float | None) -> float | None:
        """
        Parse humidity, filtering sentinel values.

        The API returns 3000.0 for LiveHumidity_pc when the humidity
        sensor is unavailable (common on zones without a humidity-capable
        sensor or wired sensors that only report temperature).

        Args:
            raw_value: Raw humidity from LiveHumidity_pc

        Returns:
            Humidity percentage, or None if unavailable

        """
        if raw_value is not None and raw_value < HUMIDITY_UNAVAILABLE:
            return raw_value
        return None

    @staticmethod
    def _detect_dry_mode_support(user_aircon_settings: dict[str, Any]) -> bool:
        """
        Detect whether this unit supports DRY (dehumidify) mode.

        DRY mode is only available on select Neo models — classic units do not
        expose it on the physical controller or in the API.  Detection is done
        in priority order:
        1. The unit is currently in DRY mode (definitive proof of support).
        2. The API advertises a DryMode.Supported flag.
        3. The API lists "DRY" in a Modes or SupportedModes capability array.
        """
        current_mode = user_aircon_settings.get("Mode", "")
        if current_mode == "DRY":
            return True

        dry_mode_obj = user_aircon_settings.get("DryMode")
        if isinstance(dry_mode_obj, dict):
            dry_mode = cast("dict[str, Any]", dry_mode_obj)
            if dry_mode.get("Supported", False):
                return True

        for field in ("Modes", "SupportedModes", "EnabledModes"):
            modes = user_aircon_settings.get(field)
            if isinstance(modes, (list, tuple)) and "DRY" in modes:
                return True

        return False

    @staticmethod
    def _parse_warnings(live_aircon: dict[str, Any]) -> list[str]:
        """
        Parse active warnings from LiveAircon data.

        Only includes currently active error indicators:
        - LiveAircon.ErrCode: main system error code (0 = no error)
        - OutdoorUnit.LPErr: active low pressure error
        - OutdoorUnit.HPErr: active high pressure error

        Note: OutdoorUnit.ErrCode_1 through ErrCode_5 are historical error
        logs that persist after resolution. These are NOT included as active
        warnings — they are exposed separately via extra_state_attributes
        on the Active Warnings binary sensor.

        Args:
            live_aircon: LiveAircon section from API response

        Returns:
            List of active warning descriptions

        """
        warnings: list[str] = []
        outdoor_unit = live_aircon.get("OutdoorUnit", {})

        # Active error indicators only
        if outdoor_unit.get("LPErr", False):
            warnings.append("Low Pressure Error")
        if outdoor_unit.get("HPErr", False):
            warnings.append("High Pressure Error")

        # Main system error code (0 = no error)
        err_code = live_aircon.get("ErrCode", 0)
        if err_code and err_code != 0:
            warnings.append(f"System Error: {err_code}")

        return warnings
