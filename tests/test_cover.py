"""Tests for the ActronAir Neo cover platform (zone dampers)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.actronair_neo.cover import (
    ActronZoneDamperCover,
    async_setup_entry,
)

from .conftest import MOCK_SERIAL, create_mock_coordinator


@pytest.fixture
def coordinator(mock_api, mock_status):
    """Create coordinator with airflow-control enabled zones."""
    mock_status["zones"]["zone_1"]["airflow_control_enabled"] = True
    return create_mock_coordinator(MagicMock(), mock_api, mock_status)


@pytest.fixture
def coordinator_locked(mock_api, mock_status):
    """Create coordinator with a locked zone."""
    mock_status["zones"]["zone_1"]["airflow_control_enabled"] = True
    mock_status["zones"]["zone_1"]["airflow_control_locked"] = True
    return create_mock_coordinator(MagicMock(), mock_api, mock_status)


@pytest.fixture
def coordinator_no_airflow(mock_api, mock_status):
    """Create coordinator without airflow-control zones."""
    return create_mock_coordinator(MagicMock(), mock_api, mock_status)


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_creates_entities_for_airflow_zones(self, coordinator, mock_status):
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        added: list = []
        await async_setup_entry(MagicMock(), mock_entry, added.extend)
        # zone_1 has airflow_control_enabled=True, zone_2 does not
        assert len(added) == 1
        assert isinstance(added[0], ActronZoneDamperCover)

    @pytest.mark.asyncio
    async def test_no_entities_without_airflow(self, coordinator_no_airflow):
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator_no_airflow
        added: list = []
        await async_setup_entry(MagicMock(), mock_entry, added.extend)
        assert len(added) == 0


class TestActronZoneDamperCover:
    def test_current_cover_position(self, coordinator):
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert cover.current_cover_position == 75

    def test_current_cover_position_none(self, coordinator, mock_status):
        mock_status["zones"]["zone_1"]["damper_position"] = None
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert cover.current_cover_position is None

    def test_is_closed_false(self, coordinator):
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert cover.is_closed is False

    def test_is_closed_true(self, coordinator, mock_status):
        mock_status["zones"]["zone_1"]["damper_position"] = 0
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert cover.is_closed is True

    def test_is_closed_none_position(self, coordinator, mock_status):
        mock_status["zones"]["zone_1"]["damper_position"] = None
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert cover.is_closed is False

    def test_available_enabled(self, coordinator):
        coordinator.last_update_success = True
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert cover.available is True

    def test_available_locked(self, coordinator_locked):
        coordinator_locked.last_update_success = True
        cover = ActronZoneDamperCover(coordinator_locked, "zone_1")
        assert cover.available is False

    def test_available_disabled(self, coordinator_no_airflow):
        coordinator_no_airflow.last_update_success = True
        cover = ActronZoneDamperCover(coordinator_no_airflow, "zone_1")
        assert cover.available is False

    @pytest.mark.asyncio
    async def test_set_cover_position(self, coordinator):
        coordinator.set_zone_airflow = AsyncMock()
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        await cover.async_set_cover_position(position=73)
        # 73 → rounds to 75
        coordinator.set_zone_airflow.assert_called_once_with(0, 75)

    @pytest.mark.asyncio
    async def test_set_cover_position_rounding(self, coordinator):
        coordinator.set_zone_airflow = AsyncMock()
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        await cover.async_set_cover_position(position=42)
        # 42 → rounds to 40
        coordinator.set_zone_airflow.assert_called_once_with(0, 40)

    @pytest.mark.asyncio
    async def test_open_cover(self, coordinator):
        coordinator.set_zone_airflow = AsyncMock()
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        await cover.async_open_cover()
        coordinator.set_zone_airflow.assert_called_once_with(0, 100)

    @pytest.mark.asyncio
    async def test_close_cover(self, coordinator):
        coordinator.set_zone_airflow = AsyncMock()
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        await cover.async_close_cover()
        coordinator.set_zone_airflow.assert_called_once_with(0, 0)

    def test_extra_state_attributes(self, coordinator):
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        attrs = cover.extra_state_attributes
        assert attrs["zone_id"] == "zone_1"
        assert attrs["zone_name"] == "Living Room"
        assert attrs["airflow_setpoint"] == 50
        assert attrs["yourzone_enabled"] is True

    def test_unique_id(self, coordinator):
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        assert MOCK_SERIAL in cover.unique_id

    def test_missing_zone_unavailable_with_minimal_attributes(
        self, coordinator, mock_status
    ):
        cover = ActronZoneDamperCover(coordinator, "zone_1")
        del mock_status["zones"]["zone_1"]
        assert cover.available is False
        assert cover.extra_state_attributes == {"zone_id": "zone_1"}
