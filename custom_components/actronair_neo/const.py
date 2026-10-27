"""Constants for the ActronAir Neo integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform  # type: ignore[import-untyped]

# ── Integration identifiers ─────────────────────────────────────

DOMAIN: Final = "actronair_neo"
DEVICE_MANUFACTURER: Final = "ActronAir"

# ── Configuration constants ─────────────────────────────────────
# Note: CONF_USERNAME / CONF_PASSWORD are no longer used (device code flow).

CONF_SERIAL_NUMBER: Final = "serial_number"
CONF_ENABLE_ZONE_CONTROL: Final = "enable_zone_control"
CONF_ENABLE_PUSH: Final = "enable_push"
CONF_BASE_URL: Final = "base_url"

# OAuth token storage keys (config entry data)
CONF_ACCESS_TOKEN: Final = "access_token"  # noqa: S105
CONF_REFRESH_TOKEN: Final = "refresh_token"  # noqa: S105
CONF_TOKEN_EXPIRES_AT: Final = "token_expires_at"  # noqa: S105

DEFAULT_REFRESH_INTERVAL: Final = 30  # seconds
DEFAULT_ENABLE_PUSH: Final = True

# ── Cache freshness ──────────────────────────────────────────────
# Maximum age of the coordinator's parsed-data cache before a full
# re-parse is forced, even when the raw API bytes are unchanged. This
# guards against the ActronAir cloud serving an unchanged (and possibly
# stale) lastKnownState indefinitely. See issue #112.
PARSE_CACHE_TTL: Final = 60  # seconds

# Maximum lifetime of an optimistic zone-enable override before it is
# discarded if the API never confirms the requested state.
ZONE_OVERRIDE_TTL: Final = 120  # seconds

# ── Platforms ────────────────────────────────────────────────────

PLATFORMS: Final[list[Platform]] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

# ── Temperature limits ───────────────────────────────────────────

MIN_TEMP: Final = 10
MAX_TEMP: Final = 30

# ── Fan modes (Actron API values) ───────────────────────────────

FAN_MODE_SUFFIX_CONT: Final = "+CONT"
VALID_FAN_MODES: Final[frozenset[str]] = frozenset({"LOW", "MED", "HIGH", "AUTO"})

# ── Zone constants ───────────────────────────────────────────────

MAX_ZONES: Final = 8

# ── Service names ────────────────────────────────────────────────

SERVICE_FORCE_UPDATE: Final = "force_update"
SERVICE_CREATE_ZONE_PRESET: Final = "create_zone_preset"
SERVICE_APPLY_ZONE_PRESET: Final = "apply_zone_preset"
SERVICE_BULK_ZONE_OPERATION: Final = "bulk_zone_operation"

# ── Entity attribute keys (used by sensor.py) ───────────────────

ATTR_BATTERY_LEVEL: Final = "battery_level"
ATTR_LAST_UPDATED: Final = "last_updated"
ATTR_ZONE_NAME: Final = "zone_name"
ATTR_ZONE_TYPE: Final = "zone_type"

# ── Icons ────────────────────────────────────────────────────────
# Note: Most icons are now defined in icons.json.
# Only kept here for programmatic use in entity constructors.

ICON_ZONE: Final = "mdi:air-conditioner"

# ── Model series definitions ────────────────────────────────────

ADVANCE_SERIES_MODELS: Final[frozenset[str]] = frozenset(
    {
        "CRV13AS",
        "CRV15AS",
        "CRV15AT",
        "CRV17AS",
        "CRV17AT",
        "CRV210T",
        "CRV240T",
        "EVV13AS-V",
        "EVV15AS",
        "EVV15AS-V",
        "EVV17AS",
        "EVV17AS-V",
        "EVV210S",
        "EVV240S",
    }
)

NEO_SERIES_WC: Final[frozenset[str]] = frozenset({"NTB-10", "NTW-10"})

# ── Fan mode capabilities ───────────────────────────────────────

BASE_FAN_MODES: Final[frozenset[str]] = frozenset({"LOW", "MED", "HIGH"})
ADVANCE_FAN_MODES: Final[frozenset[str]] = frozenset({"LOW", "MED", "HIGH", "AUTO"})

ADVANCED_FAN_MODE_ORDER: Final = ["AUTO", "LOW", "MED", "HIGH"]
BASE_FAN_MODE_ORDER: Final = ["LOW", "MED", "HIGH"]

# ── Sensor sentinel values ────────────────────────────────────────
# The ActronAir API returns 3000.0 when a sensor reading is unavailable
# (common on Classic series or zones without the respective sensor).

OUTDOOR_TEMP_UNAVAILABLE: Final = 3000.0
HUMIDITY_UNAVAILABLE: Final = 3000.0

# ── Outdoor-unit telemetry scaling factors ────────────────────────
# NTW-series (Advance/Inverter) units report telemetry at reduced scale
# in the raw API payload. These factors correct the values to real-world
# engineering units.
#
# SupplyVoltage_Vac: NTW-1000 evidence shows raw 23.0 -> actual 230 VAC
# (factor of 10). Confirmed via GitHub issue #133: supply_voltage x 10
# matches meter readings when cross-checked with supply_current.
#
# CompPower: Raw 45 -> actual ~4500 W (factor of 100). P ~= V x I gives
# 230 V x 19 A ~= 4370 W, consistent with 45 x 100 = 4500 W.
#
# Three-phase Advance units (Family "Inverter: Advance Series I Three
# Phase", also controller model NTW-1000) are NOT scaled: they report
# CompPower in W already (raw 122-5142 on a 24 kW system).  Their raw
# SupplyVoltage_Vac (~665-715) is not confirmed as line voltage and passes
# through unchanged; x 10 gave ~7000 VAC.  See GitHub issue #189.
#
# Native-watt single-phase units (#200).  Some single-phase Inverter units
# on the same controller model and firmware (NTW-1000, 2.6.2.5) report
# CompPower in W already (raw 2975 -> 2975 W, not 297,500 W).  Nothing in
# the payload labels the format, so a magnitude ceiling decides: a
# reduced-scale reading above 100 would be over 10 kW after x 100, which a
# single-phase compressor cannot draw.  The first reading above the ceiling
# latches the system as native-watt, and the latch is persisted so readings
# stay unscaled after a restart.  Residual risk: low native-watt readings
# taken before the first reading above the ceiling are still scaled x 100.
# SupplyVoltage_Vac is checked independently: raw 23 (reduced) and raw 230
# (native) cannot overlap, so only 0 < raw <= 100 is scaled x 10.
#
# SupplyPowerRMS_W / OutputPowerRMS_W: scaling not yet confirmed from a
# live payload with non-zero values; left unscaled pending further data.
# See utils/actron_api_structure.md (NTW-series Telemetry Scaling section)
# for details on sharing live payload data to confirm these factors.

SUPPLY_VOLTAGE_SCALE_FACTOR: Final = 10  # raw VAC x 10 = actual VAC (NTW-series)
COMP_POWER_SCALE_FACTOR: Final = 100  # raw W x 100 = actual W (NTW-series)
# Lower-case Family marker for three-phase units, which are never scaled
THREE_PHASE_FAMILY_MARKER: Final = "three phase"
# Largest raw reduced-scale values: CompPower 100 (= 10 kW), voltage 100 (= 1000 V)
REDUCED_SCALE_MAX_RAW_COMP_POWER: Final = 100
REDUCED_SCALE_MAX_RAW_VOLTAGE: Final = 100
# CompPower format of a single-phase Inverter system (persisted per device)
POWER_FORMAT_UNRESOLVED: Final = "unresolved"
POWER_FORMAT_NATIVE_WATT: Final = "native_watt"
POWER_FORMAT_STORAGE_KEY: Final = f"{DOMAIN}.power_format"
POWER_FORMAT_STORAGE_VERSION: Final = 1

WATTS_PER_KILOWATT: Final = 1000  # W -> kW conversion for power display formatting
