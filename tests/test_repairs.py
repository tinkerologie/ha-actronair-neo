"""Tests for the ActronAir Neo repairs flow."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant.common import MockConfigEntry

from custom_components.actronair_neo.api.models import ZoneCapabilities
from custom_components.actronair_neo.const import DOMAIN
from custom_components.actronair_neo.repairs import (
    ISSUE_API_AUTHENTICATION_FAILED,
    ISSUE_DEVICE_OFFLINE,
    ISSUE_KEYS,
    ISSUE_SENSOR_UNAVAILABLE,
    ApiAuthenticationFailedRepairFlow,
    DeviceOfflineRepairFlow,
    SensorUnavailableRepairFlow,
    async_check_issues,
    async_create_fix_flow,
    async_health_check,
)


class TestApiAuthenticationFailedRepairFlow:
    """Tests for the API authentication failure repair flow."""

    @pytest.mark.asyncio
    async def test_init_step_shows_form(self):
        """Test init step shows form."""
        flow = ApiAuthenticationFailedRepairFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_init()
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_init_step_with_input_creates_entry(self):
        """Test init step with user input creates entry."""
        flow = ApiAuthenticationFailedRepairFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_init(user_input={})
        assert result["type"] is FlowResultType.CREATE_ENTRY


class TestDeviceOfflineRepairFlow:
    """Tests for the device offline repair flow."""

    @pytest.mark.asyncio
    async def test_init_step_shows_form(self):
        """Test init step shows form."""
        flow = DeviceOfflineRepairFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_init()
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_init_step_with_input_creates_entry(self):
        """Test init step with user input creates entry."""
        flow = DeviceOfflineRepairFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_init(user_input={})
        assert result["type"] is FlowResultType.CREATE_ENTRY


class TestSensorUnavailableRepairFlow:
    """Tests for the sensor unavailable repair flow."""

    @pytest.mark.asyncio
    async def test_init_step_shows_form(self):
        """Test init step shows form."""
        flow = SensorUnavailableRepairFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_init()
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_init_step_with_input_creates_entry(self):
        """Test init step with user input creates entry."""
        flow = SensorUnavailableRepairFlow()
        flow.hass = MagicMock()
        result = await flow.async_step_init(user_input={})
        assert result["type"] is FlowResultType.CREATE_ENTRY


class TestAsyncCreateFixFlow:
    """Tests for the fix flow factory."""

    @pytest.mark.asyncio
    async def test_creates_auth_repair_flow(self):
        """Test fix flow routes authentication issues correctly."""
        hass = MagicMock()
        flow = await async_create_fix_flow(hass, "api_authentication_failed", None)
        assert isinstance(flow, ApiAuthenticationFailedRepairFlow)

    @pytest.mark.asyncio
    async def test_creates_device_offline_repair_flow(self):
        """Test fix flow routes device offline issues correctly."""
        hass = MagicMock()
        flow = await async_create_fix_flow(hass, "device_offline", None)
        assert isinstance(flow, DeviceOfflineRepairFlow)

    @pytest.mark.asyncio
    async def test_creates_sensor_unavailable_repair_flow(self):
        """Test fix flow routes sensor unavailable issues correctly."""
        hass = MagicMock()
        flow = await async_create_fix_flow(hass, "sensor_unavailable", None)
        assert isinstance(flow, SensorUnavailableRepairFlow)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("key", "flow_class"),
        [
            (ISSUE_API_AUTHENTICATION_FAILED, ApiAuthenticationFailedRepairFlow),
            (ISSUE_DEVICE_OFFLINE, DeviceOfflineRepairFlow),
            (ISSUE_SENSOR_UNAVAILABLE, SensorUnavailableRepairFlow),
        ],
    )
    async def test_routes_entry_qualified_issue_ids(self, key, flow_class):
        """Entry-qualified issue IDs open the matching repair flow."""
        flow = await async_create_fix_flow(MagicMock(), f"{key}_01ENTRYID", None)
        assert isinstance(flow, flow_class)

    @pytest.mark.asyncio
    async def test_creates_confirm_flow_for_unknown_issue(self):
        """Test fix flow returns ConfirmRepairFlow for unknown issues."""
        hass = MagicMock()
        flow = await async_create_fix_flow(hass, "unknown_issue", None)
        assert isinstance(flow, ConfirmRepairFlow)

    @pytest.mark.asyncio
    async def test_creates_repair_flow_with_data(self):
        """Test fix flow factory with data."""
        hass = MagicMock()
        data = {"key": "value"}
        flow = await async_create_fix_flow(hass, "device_offline", data)
        assert isinstance(flow, DeviceOfflineRepairFlow)


def _entry(hass, unique_id: str, *, healthy: bool) -> MockConfigEntry:
    """Add an entry whose mocked coordinator is healthy or failing every check."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, unique_id=unique_id)
    entry.add_to_hass(hass)
    _set_health(entry, healthy=healthy)
    return entry


def _set_health(entry: MockConfigEntry, *, healthy: bool) -> None:
    coordinator = MagicMock()
    coordinator.device_id = entry.unique_id
    coordinator.api_error_count = 0 if healthy else 6
    coordinator.last_update_success = healthy
    coordinator.data = {
        "zones": {
            "zone_1": {
                "name": "Living",
                "temp": 22 if healthy else None,
                "capabilities": ZoneCapabilities(exists=True),
            }
        }
    }
    entry.runtime_data = coordinator


def _entry_issues(hass, entry: MockConfigEntry) -> dict[str, ir.IssueEntry]:
    return {
        issue.translation_key: issue
        for (domain, _), issue in ir.async_get(hass).issues.items()
        if domain == DOMAIN and issue.config_entry_id == entry.entry_id
    }


async def test_async_check_issues_creates_entry_owned_issues(hass):
    """Failing checks create entry-qualified issues owned by the entry."""
    entry = _entry(hass, "SERIAL_A", healthy=False)

    await async_check_issues(hass, entry)

    issues = _entry_issues(hass, entry)
    assert set(issues) == set(ISSUE_KEYS)
    for key, issue in issues.items():
        assert issue.issue_id == f"{key}_{entry.entry_id}"
        assert issue.is_fixable
    assert issues[ISSUE_API_AUTHENTICATION_FAILED].severity is ir.IssueSeverity.ERROR
    assert issues[ISSUE_DEVICE_OFFLINE].severity is ir.IssueSeverity.WARNING
    assert issues[ISSUE_SENSOR_UNAVAILABLE].severity is ir.IssueSeverity.WARNING
    assert issues[ISSUE_SENSOR_UNAVAILABLE].translation_placeholders == {
        "device_name": "SERIAL_A",
        "sensor_count": "1",
        "sensor_names": "Living",
    }


async def test_async_check_issues_refresh_removes_resolved_issues(hass):
    """A healthy recheck removes the entry's issues."""
    entry = _entry(hass, "SERIAL_A", healthy=False)
    await async_check_issues(hass, entry)

    _set_health(entry, healthy=True)
    await async_check_issues(hass, entry)

    assert _entry_issues(hass, entry) == {}


async def test_async_check_issues_isolated_per_entry(hass):
    """A healthy check for one entry leaves another entry's issues alone."""
    entry_a = _entry(hass, "SERIAL_A", healthy=False)
    entry_b = _entry(hass, "SERIAL_B", healthy=False)
    await async_check_issues(hass, entry_a)
    await async_check_issues(hass, entry_b)

    _set_health(entry_b, healthy=True)
    await async_check_issues(hass, entry_b)

    assert set(_entry_issues(hass, entry_a)) == set(ISSUE_KEYS)
    assert _entry_issues(hass, entry_b) == {}


async def test_async_check_issues_keeps_ignored_issue_ignored(hass):
    """Recreating an ignored issue keeps it ignored."""
    entry = _entry(hass, "SERIAL_A", healthy=False)
    await async_check_issues(hass, entry)
    issue_id = f"{ISSUE_DEVICE_OFFLINE}_{entry.entry_id}"
    ir.async_ignore_issue(hass, DOMAIN, issue_id, True)

    await async_check_issues(hass, entry)

    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.dismissed_version is not None


async def test_async_check_issues_removes_legacy_global_issues(hass):
    """Domain-global issue IDs from earlier versions are deleted."""
    entry = _entry(hass, "SERIAL_A", healthy=True)
    for key in ISSUE_KEYS:
        ir.async_create_issue(
            hass,
            DOMAIN,
            key,
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=key,
        )

    await async_check_issues(hass, entry)

    registry = ir.async_get(hass)
    assert all(registry.async_get_issue(DOMAIN, key) is None for key in ISSUE_KEYS)


async def test_entry_issues_removed_with_entry(hass):
    """Home Assistant deletes entry-owned issues when the entry is removed."""
    entry = _entry(hass, "SERIAL_A", healthy=False)
    await async_check_issues(hass, entry)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    assert all(
        registry.async_get_issue(DOMAIN, f"{key}_{entry.entry_id}") is None
        for key in ISSUE_KEYS
    )


@pytest.mark.asyncio
async def test_async_health_check_degraded_and_unhealthy():
    """Test health check includes issues and status transitions."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.api_error_count = 12
    coordinator.last_successful_api_request = "2025-01-01T00:00:00Z"
    coordinator.api_cache_size = 1
    coordinator.data = {
        "zones": {
            "zone_1": {"name": "Living", "battery_level": 10, "signal_strength": -80}
        }
    }
    entry = MagicMock()
    entry.runtime_data = coordinator

    result = await async_health_check(hass, entry)
    assert result["overall_status"] == "unhealthy"
    assert len(result["issues"]) >= 2


@pytest.mark.asyncio
async def test_async_health_check_degraded_warning_only():
    """Test health check returns degraded when only warning issues exist."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.api_error_count = 4
    coordinator.last_successful_api_request = "2025-01-01T00:00:00Z"
    coordinator.api_cache_size = 0
    coordinator.data = {
        "zones": {
            "zone_1": {"name": "Living", "battery_level": 50, "signal_strength": -60}
        }
    }
    entry = MagicMock()
    entry.runtime_data = coordinator

    result = await async_health_check(hass, entry)
    assert result["overall_status"] == "degraded"
