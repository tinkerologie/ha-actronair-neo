"""Repairs for ActronAir Neo integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.repairs import (
    ConfirmRepairFlow,
    RepairsFlow,
    RepairsFlowResult,
)
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
    async_refresh_issues,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import ActronDataCoordinator

ISSUE_API_AUTHENTICATION_FAILED = "api_authentication_failed"
ISSUE_DEVICE_OFFLINE = "device_offline"
ISSUE_SENSOR_UNAVAILABLE = "sensor_unavailable"
ISSUE_KEYS = (
    ISSUE_API_AUTHENTICATION_FAILED,
    ISSUE_DEVICE_OFFLINE,
    ISSUE_SENSOR_UNAVAILABLE,
)


def issue_id_for(key: str, entry: ConfigEntry) -> str:
    """Return the issue ID for an issue key, unique per config entry."""
    return f"{key}_{entry.entry_id}"


async def async_create_fix_flow(
    hass: HomeAssistant,  # noqa: ARG001
    issue_id: str,
    data: dict[str, str | int | float | None] | None,  # noqa: ARG001
) -> RepairsFlow:
    """Create the repair flow for an entry-qualified (or legacy bare) issue ID."""
    if issue_id.startswith(ISSUE_API_AUTHENTICATION_FAILED):
        return ApiAuthenticationFailedRepairFlow()
    if issue_id.startswith(ISSUE_DEVICE_OFFLINE):
        return DeviceOfflineRepairFlow()
    if issue_id.startswith(ISSUE_SENSOR_UNAVAILABLE):
        return SensorUnavailableRepairFlow()
    return ConfirmRepairFlow()


class ApiAuthenticationFailedRepairFlow(RepairsFlow):
    """Handler for API authentication failures."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            # Mark as resolved - user will need to reconfigure integration
            return self.async_create_entry(data={})

        # Guidance text comes from issues.api_authentication_failed.fix_flow
        # in strings.json / translations.
        return self.async_show_form(step_id="init")


class DeviceOfflineRepairFlow(RepairsFlow):
    """Handler for device offline issues."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(data={})

        # Guidance text comes from issues.device_offline.fix_flow in
        # strings.json / translations.
        return self.async_show_form(step_id="init")


class SensorUnavailableRepairFlow(RepairsFlow):
    """Handler for sensor unavailability issues."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            return self.async_create_entry(data={})

        # Guidance text comes from issues.sensor_unavailable.fix_flow in
        # strings.json / translations.
        return self.async_show_form(step_id="init")


async def async_check_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """
    Refresh this entry's repair issues from the coordinator state.

    Issues belong to the config entry, so Home Assistant removes them with the
    entry. The refresh deletes the entry's issues that no check recreates, and
    recreating an existing issue keeps a user's "ignore".
    """
    coordinator: ActronDataCoordinator = entry.runtime_data

    # Versions before 2026.11 used domain-global issue IDs; remove them.
    for key in ISSUE_KEYS:
        async_delete_issue(hass, DOMAIN, key)

    with async_refresh_issues(hass, DOMAIN, config_entry_id=entry.entry_id):
        # Check API authentication status
        if coordinator.api_error_count > 5:  # noqa: PLR2004
            async_create_issue(
                hass,
                DOMAIN,
                issue_id_for(ISSUE_API_AUTHENTICATION_FAILED, entry),
                config_entry_id=entry.entry_id,
                is_fixable=True,
                severity=IssueSeverity.ERROR,
                translation_key=ISSUE_API_AUTHENTICATION_FAILED,
                translation_placeholders={
                    "device_name": coordinator.device_id,
                    "error_count": str(coordinator.api_error_count),
                },
            )

        # Check device connectivity
        if not coordinator.last_update_success:
            async_create_issue(
                hass,
                DOMAIN,
                issue_id_for(ISSUE_DEVICE_OFFLINE, entry),
                config_entry_id=entry.entry_id,
                is_fixable=True,
                severity=IssueSeverity.WARNING,
                translation_key=ISSUE_DEVICE_OFFLINE,
                translation_placeholders={
                    "device_name": coordinator.device_id,
                },
            )

        # Check sensor availability
        unavailable_sensors: list[str] = []
        zones = coordinator.data.get("zones", {}) if coordinator.data else {}
        for zone_id, zone_data in zones.items():
            capabilities = zone_data.get("capabilities")
            zone_exists = bool(capabilities.exists) if capabilities else False
            if zone_data.get("temp") is None and zone_exists:
                unavailable_sensors.append(zone_data.get("name", zone_id))

        if unavailable_sensors:
            async_create_issue(
                hass,
                DOMAIN,
                issue_id_for(ISSUE_SENSOR_UNAVAILABLE, entry),
                config_entry_id=entry.entry_id,
                is_fixable=True,
                severity=IssueSeverity.WARNING,
                translation_key=ISSUE_SENSOR_UNAVAILABLE,
                translation_placeholders={
                    "device_name": coordinator.device_id,
                    "sensor_count": str(len(unavailable_sensors)),
                    "sensor_names": ", ".join(unavailable_sensors[:3]),
                },
            )


async def async_health_check(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:  # noqa: ARG001
    """Perform comprehensive health check."""
    coordinator: ActronDataCoordinator = entry.runtime_data

    health_status: dict[str, Any] = {
        "overall_status": "healthy",
        "issues": [],
        "recommendations": [],
        "system_info": {
            "api_error_count": coordinator.api_error_count,
            "last_successful_update": coordinator.last_successful_api_request,
            "cache_size": coordinator.api_cache_size,
        },
    }

    # Check API health
    if coordinator.api_error_count > 3:  # noqa: PLR2004
        err_count = coordinator.api_error_count
        severity = (
            "warning" if err_count < 10 else "error"  # noqa: PLR2004
        )
        health_status["issues"].append(
            {
                "type": "api_errors",
                "severity": severity,
                "message": (f"High API error count: {err_count}"),
                "recommendation": (
                    "Check network connectivity and ActronAir service status"
                ),
            }
        )
        health_status["overall_status"] = "degraded"

    # Check zone sensor health
    zones = coordinator.data.get("zones", {}) if coordinator.data else {}
    for zone_id, zone_data in zones.items():
        battery = zone_data.get("battery_level")
        if battery is not None and battery < 20:  # noqa: PLR2004
            zone_name = zone_data.get("name", zone_id)
            health_status["issues"].append(
                {
                    "type": "low_battery",
                    "severity": "warning",
                    "message": (f"Zone {zone_name} has low battery: {battery}%"),
                    "recommendation": "Replace zone sensor battery",
                }
            )

        signal = zone_data.get("signal_strength")
        if signal is not None and signal < -70:  # noqa: PLR2004
            zone_name = zone_data.get("name", zone_id)
            health_status["issues"].append(
                {
                    "type": "poor_signal",
                    "severity": "warning",
                    "message": (f"Zone {zone_name} has poor signal: {signal} dBm"),
                    "recommendation": (
                        "Check sensor placement and remove obstructions"
                    ),
                }
            )

    # Set overall status based on issues
    if any(issue["severity"] == "error" for issue in health_status["issues"]):
        health_status["overall_status"] = "unhealthy"
    elif health_status["issues"]:
        health_status["overall_status"] = "degraded"

    return health_status
