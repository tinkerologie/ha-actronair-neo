"""Tests for the ActronAir Neo coordinator."""

import asyncio
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate.const import HVACMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.actronair_neo.api.models import ZoneCapabilities
from custom_components.actronair_neo.api.push.models import PushState
from custom_components.actronair_neo.const import (
    POWER_FORMAT_NATIVE_WATT,
    POWER_FORMAT_UNRESOLVED,
)
from custom_components.actronair_neo.coordinator import (
    ActronDataCoordinator,
    _as_float,
)
from custom_components.actronair_neo.exceptions import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    DeviceOfflineError,
    RateLimitError,
    ZoneError,
)


@pytest.fixture
def coordinator_instance(
    hass: HomeAssistant, mock_api: MagicMock
) -> ActronDataCoordinator:
    """Return a coordinator instance for helper-method tests."""
    coordinator = ActronDataCoordinator(
        hass=hass,
        api=mock_api,
        device_id="TEST123456",
        update_interval=60,
        enable_zone_control=True,
    )
    coordinator.data = {
        "main": {
            "fan_mode": "LOW",
            "supported_fan_modes": ["LOW", "MED", "HIGH"],
            "EnabledZones": [True, False, False, False, False, False, False, False],
        },
        "zones": {
            "zone_1": {
                "name": "Living",
                "is_enabled": True,
                "capabilities": ZoneCapabilities(
                    exists=True,
                    can_operate=True,
                    has_temp_control=True,
                    has_separate_targets=False,
                    target_temp_cool=24.0,
                    target_temp_heat=22.0,
                    peripheral_capabilities=None,
                ),
            }
        },
    }
    coordinator._last_raw_response = {
        "lastKnownState": {
            "RemoteZoneInfo": [
                {
                    "Sensors": {"test123456": {"NV_Kind": "ZS: 23E01206"}},
                }
            ],
            "AirconSystem": {
                "Peripherals": [
                    {
                        "SerialNumber": "23E01206",
                        "LastConnectionTime": "2025-01-01T00:00:00Z",
                    }
                ]
            },
            "UserAirconSettings": {"FanMode": "HIGH"},
        },
    }
    coordinator.last_data = coordinator.data
    return coordinator


class TestActronDataCoordinator:
    """Test the ActronDataCoordinator class."""

    @pytest.mark.asyncio
    async def test_coordinator_initialization(
        self, hass: HomeAssistant, mock_api: MagicMock
    ) -> None:
        """Test coordinator initialization."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        assert coordinator.api == mock_api
        assert coordinator.device_id == "TEST123456"
        assert coordinator.enable_zone_control is True
        assert coordinator.last_data is None
        assert coordinator._continuous_fan is False

    @pytest.mark.asyncio
    async def test_successful_data_update(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
        mock_api_response: dict[str, Any],
    ) -> None:
        """Test successful data update."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock API response
        mock_api.get_ac_status = AsyncMock(return_value=mock_api_response)
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.cleanup_expired_cache = AsyncMock()

        # Mock zone capabilities
        mock_api.get_zone_capabilities = MagicMock(
            return_value=ZoneCapabilities(
                exists=True,
                can_operate=True,
                has_temp_control=True,
                has_separate_targets=False,
                target_temp_cool=22.0,
                target_temp_heat=20.0,
                peripheral_capabilities=None,
            )
        )

        # Perform update
        result = await coordinator._async_update_data()

        # Verify result structure
        assert "main" in result
        assert "zones" in result
        assert "live_aircon" in result

        # Verify main data
        main_data = result["main"]
        assert main_data["is_on"] is True
        assert main_data["mode"] == "COOL"
        assert main_data["fan_mode"] == "AUTO"
        assert main_data["indoor_temp"] == 23.5
        assert main_data["indoor_humidity"] == 45

        # Verify zones data
        zones_data = result["zones"]
        assert "zone_1" in zones_data
        assert "zone_2" in zones_data

        zone_1 = zones_data["zone_1"]
        assert zone_1["name"] == "Living Room"
        assert zone_1["temp"] == 22.0
        assert zone_1["humidity"] == 40

        # Verify coordinator state
        assert coordinator.last_data == result

        # Verify API calls
        mock_api.get_ac_status.assert_called_once_with("TEST123456", use_cache=True)
        mock_api.cleanup_expired_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_unhealthy_fallback(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
        mock_api_response: dict[str, Any],
    ) -> None:
        """Test fallback to cached data when API is unhealthy."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Set up cached data
        coordinator.last_data = {"cached": "data"}

        # Mock unhealthy API
        mock_api.is_api_healthy = MagicMock(return_value=False)

        # Perform update
        result = await coordinator._async_update_data()

        # Should return cached data
        assert result == {"cached": "data"}

        # Should not have called API
        mock_api.get_ac_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_authentication_error_handling(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test authentication error handling."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock authentication error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(
            side_effect=AuthenticationError("Auth failed")
        )
        mock_api.clear_all_caches = AsyncMock()

        # Should raise ConfigEntryAuthFailed
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()

        # Should clear caches on auth failure
        mock_api.clear_all_caches.assert_called_once()

    @pytest.mark.asyncio
    async def test_api_error_with_cached_data(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test API error handling with cached data fallback."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Set up cached data
        coordinator.last_data = {"cached": "data"}

        # Mock API error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(side_effect=ApiError("API failed"))

        # Should return cached data
        result = await coordinator._async_update_data()
        assert result == {"cached": "data"}

    @pytest.mark.asyncio
    async def test_api_error_without_cached_data(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test API error handling without cached data."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # No cached data
        coordinator.last_data = None

        # Mock API error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(side_effect=ApiError("API failed"))

        # Should raise UpdateFailed
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()

    @pytest.mark.asyncio
    async def test_data_parsing_methods(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
        mock_api_response: dict[str, Any],
    ) -> None:
        """Test data parsing methods."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock zone capabilities
        mock_api.get_zone_capabilities = MagicMock(
            return_value=ZoneCapabilities(
                exists=True,
                can_operate=True,
                has_temp_control=True,
                has_separate_targets=False,
                target_temp_cool=22.0,
                target_temp_heat=20.0,
                peripheral_capabilities=None,
            )
        )

        # Test data extraction
        last_known_state = mock_api_response["lastKnownState"]
        data_sections = coordinator._extract_data_sections(last_known_state)

        assert "user_aircon_settings" in data_sections
        assert "master_info" in data_sections
        assert "live_aircon" in data_sections
        assert "aircon_system" in data_sections
        assert "indoor_unit" in data_sections
        assert "alerts" in data_sections
        assert "remote_zone_info" in data_sections
        assert "peripherals" in data_sections

        # Test main data parsing
        main_data = await coordinator._parse_main_data(data_sections)

        assert main_data["is_on"] is True
        assert main_data["mode"] == "COOL"
        assert main_data["fan_mode"] == "AUTO"
        assert main_data["fan_continuous"] is False
        assert main_data["base_fan_mode"] == "AUTO"
        assert main_data["indoor_temp"] == 23.5
        assert main_data["indoor_humidity"] == 45
        assert main_data["compressor_state"] == "COOLING"
        assert main_data["away_mode"] is False
        assert main_data["quiet_mode"] is False
        assert main_data["filter_clean_required"] is False
        assert main_data["defrosting"] is False

        # Test zones data parsing
        zones_data = await coordinator._parse_zones_data(data_sections)

        assert "zone_1" in zones_data
        assert "zone_2" in zones_data

        zone_1 = zones_data["zone_1"]
        assert zone_1["name"] == "Living Room"
        assert zone_1["temp"] == 22.0
        assert zone_1["humidity"] == 40
        assert zone_1["is_enabled"] is True
        assert zone_1["battery_level"] == 85
        assert zone_1["signal_strength"] == 2

    @pytest.mark.asyncio
    async def test_cache_management_methods(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test cache management methods."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock API methods
        mock_api.clear_all_caches = AsyncMock()
        mock_api.invalidate_status_cache = AsyncMock()
        mock_api.cleanup_expired_cache = AsyncMock()

        # Test force update
        with patch.object(
            coordinator, "async_refresh", new_callable=AsyncMock
        ) as mock_refresh:
            await coordinator.force_update()
            mock_api.clear_all_caches.assert_called_once()
            mock_refresh.assert_called_once()

        # Test cache invalidation
        await coordinator.invalidate_cache()
        mock_api.invalidate_status_cache.assert_called_once_with("TEST123456")

        # Test cache cleanup
        await coordinator.cleanup_expired_cache()
        mock_api.cleanup_expired_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_statistics(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test cache statistics."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock API properties
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.last_successful_request = datetime.now()
        mock_api.error_count = 0
        mock_api.cached_status = {"some": "data"}

        # Set coordinator data
        coordinator.last_data = {"coordinator": "data"}

        # Get cache stats
        stats = coordinator.get_cache_stats()

        assert stats["api_health"] is True
        assert stats["last_successful_request"] is not None
        assert stats["error_count"] == 0
        assert stats["has_cached_status"] is True
        assert stats["coordinator_has_data"] is True

    @pytest.mark.asyncio
    async def test_periodic_cache_cleanup(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test periodic cache cleanup."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock API method
        mock_api.cleanup_expired_cache = AsyncMock()

        # First call should trigger cleanup
        await coordinator._maybe_cleanup_cache()
        mock_api.cleanup_expired_cache.assert_called_once()
        assert coordinator._last_cache_cleanup is not None

        # Reset mock
        mock_api.cleanup_expired_cache.reset_mock()

        # Second call immediately should not trigger cleanup
        await coordinator._maybe_cleanup_cache()
        mock_api.cleanup_expired_cache.assert_not_called()

        # Simulate time passage
        coordinator._last_cache_cleanup = datetime.now() - timedelta(seconds=301)

        # Should trigger cleanup again
        await coordinator._maybe_cleanup_cache()
        mock_api.cleanup_expired_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_zone_control_toggle(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test zone control enable/disable."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Mock refresh method
        with patch.object(
            coordinator, "async_request_refresh", new_callable=AsyncMock
        ) as mock_refresh:
            # Test disabling zone control
            await coordinator.set_enable_zone_control(enable=False)
            assert coordinator.enable_zone_control is False
            mock_refresh.assert_called_once()

            # Reset mock
            mock_refresh.reset_mock()

            # Test enabling zone control
            await coordinator.set_enable_zone_control(enable=True)
            assert coordinator.enable_zone_control is True
            mock_refresh.assert_called_once()


class TestEnhancedCoordinatorErrorHandling:
    """Test enhanced error handling in coordinator."""

    @pytest.mark.asyncio
    async def test_rate_limit_error_handling(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test rate limit error handling with cached data fallback."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Set up cached data
        coordinator.last_data = {"cached": "data"}

        # Mock rate limit error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(
            side_effect=RateLimitError("Rate limited", retry_after=60)
        )

        # Should return cached data
        result = await coordinator._async_update_data()
        assert result == {"cached": "data"}

    @pytest.mark.asyncio
    async def test_device_offline_error_handling(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test device offline error handling."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Set up cached data
        coordinator.last_data = {"cached": "data"}

        # Mock device offline error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(
            side_effect=DeviceOfflineError("Device offline", "TEST123456")
        )

        # Should return cached data
        result = await coordinator._async_update_data()
        assert result == {"cached": "data"}

    @pytest.mark.asyncio
    async def test_temporary_api_error_handling(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test temporary API error handling."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Set up cached data
        coordinator.last_data = {"cached": "data"}

        # Mock temporary API error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        temp_error = ApiError("Server error", status_code=503)
        mock_api.get_ac_status = AsyncMock(side_effect=temp_error)

        # Should return cached data for temporary errors
        result = await coordinator._async_update_data()
        assert result == {"cached": "data"}

    @pytest.mark.asyncio
    async def test_client_error_handling(
        self,
        hass: HomeAssistant,
        mock_api: MagicMock,
    ) -> None:
        """Test client error handling."""
        coordinator = ActronDataCoordinator(
            hass=hass,
            api=mock_api,
            device_id="TEST123456",
            update_interval=60,
            enable_zone_control=True,
        )

        # Set up cached data
        coordinator.last_data = {"cached": "data"}

        # Mock client error
        mock_api.is_api_healthy = MagicMock(return_value=True)
        client_error = ApiError("Bad request", status_code=400)
        mock_api.get_ac_status = AsyncMock(side_effect=client_error)

        # Should return cached data for client errors too
        result = await coordinator._async_update_data()
        assert result == {"cached": "data"}


class TestCoordinatorAdditionalCoverage:
    """Additional coordinator tests for low-coverage branches."""

    def test_validate_fan_mode_and_response(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        assert coordinator_instance.validate_fan_mode("med") == "MED"
        assert coordinator_instance.validate_fan_mode("invalid") == "LOW"
        assert (
            coordinator_instance.validate_fan_mode("high", continuous=True)
            == "HIGH+CONT"
        )
        assert coordinator_instance._validate_fan_mode_response(
            "HIGH", "HIGH+CONT", continuous=True
        )

    def test_handle_api_error_variants(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        coordinator_instance.last_data = {"cached": "yes"}
        assert coordinator_instance._handle_api_error(
            ApiError("tmp", status_code=503)
        ) == {"cached": "yes"}

        coordinator_instance.last_data = None
        with pytest.raises(UpdateFailed):
            coordinator_instance._handle_api_error(ApiError("client", status_code=400))

        with pytest.raises(UpdateFailed):
            coordinator_instance._handle_api_error(ApiError("server", status_code=500))

    @pytest.mark.asyncio
    async def test_parse_data_optimized_cache_hit(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        payload = {"lastKnownState": {"RemoteZoneInfo": []}}
        coordinator_instance._last_memory_cleanup = datetime.now()
        with patch.object(
            coordinator_instance,
            "_parse_data",
            new_callable=AsyncMock,
            return_value={"main": {}, "zones": {}, "live_aircon": {}},
        ) as parse_data:
            first = await coordinator_instance._parse_data_optimized(payload)
            second = await coordinator_instance._parse_data_optimized(payload)
        assert first == second
        assert parse_data.call_count >= 1

    def test_fan_mode_decoding_and_parsing(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        modes = coordinator_instance._validate_fan_modes(0x0F)
        assert "LOW" in modes
        assert "MED" in modes
        assert "HIGH" in modes

        parsed = coordinator_instance._parse_fan_mode_list("low,med", ["LOW", "MED"])
        assert parsed == ["LOW", "MED"]
        parsed_list = coordinator_instance._parse_fan_mode_list(
            ["auto", "bad"], ["LOW"]
        )
        assert parsed_list == ["AUTO"]

    def test_zone_peripheral_helpers(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        peripheral = coordinator_instance.get_zone_peripheral("zone_1")
        assert peripheral is not None
        assert (
            coordinator_instance.get_zone_last_updated("zone_1")
            == "2025-01-01T00:00:00Z"
        )
        assert coordinator_instance.get_zone_peripheral("zone_99") is None

    @pytest.mark.asyncio
    async def test_set_methods_call_api(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        mock_api.create_command = MagicMock(return_value={"cmd": "x"})
        mock_api.send_command = AsyncMock()
        mock_api.set_zone_airflow = AsyncMock()
        mock_api.set_away_mode = AsyncMock()
        mock_api.set_quiet_mode = AsyncMock()
        mock_api.set_turbo_mode = AsyncMock()
        mock_api.set_after_hours = AsyncMock()
        mock_api.set_after_hours_duration = AsyncMock()

        await coordinator_instance.set_hvac_mode("COOL")
        await coordinator_instance.set_temperature(23.0, is_cooling=True)
        await coordinator_instance.set_climate_mode("HEAT")
        await coordinator_instance.set_zone_airflow(0, 50)
        await coordinator_instance.set_away_mode(state=True)
        await coordinator_instance.set_quiet_mode(state=True)
        await coordinator_instance.set_turbo_mode(state=True)
        await coordinator_instance.set_after_hours(enabled=True)
        await coordinator_instance.set_after_hours_duration(90)
        assert mock_api.send_command.call_count >= 3

    @pytest.mark.asyncio
    async def test_set_fan_mode_path(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        coordinator_instance._throttle_fan_mode_change = AsyncMock()
        coordinator_instance._send_fan_mode_with_retry = AsyncMock()
        await coordinator_instance.set_fan_mode("LOW")
        coordinator_instance._send_fan_mode_with_retry.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_fan_mode_with_retry_error_and_success(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
    ) -> None:
        coordinator_instance.data["main"]["fan_mode"] = "LOW+CONT"
        coordinator_instance.async_request_refresh = AsyncMock()
        coordinator_instance.async_refresh = AsyncMock()
        mock_api.create_command = MagicMock(return_value={"cmd": "fan"})
        mock_api.send_command = AsyncMock()
        await coordinator_instance._send_fan_mode_with_retry(
            "LOW+CONT", continuous=True
        )

        err = ApiError("retry", status_code=429)
        mock_api.send_command = AsyncMock(side_effect=err)
        with pytest.raises(ApiError):
            await coordinator_instance._send_fan_mode_with_retry(
                "LOW", continuous=False
            )

    @pytest.mark.asyncio
    async def test_set_zone_temperature_validations(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        mock_api.set_zone_temperature = AsyncMock()

        coordinator_instance.enable_zone_control = False
        with pytest.raises(ConfigurationError):
            await coordinator_instance.set_zone_temperature("zone_1", 22.0)

        coordinator_instance.enable_zone_control = True
        with pytest.raises(ZoneError):
            await coordinator_instance.set_zone_temperature("zone_2", 22.0)

        with pytest.raises(ZoneError):
            await coordinator_instance.set_zone_temperature("zone_1", 99.0)

        await coordinator_instance.set_zone_temperature("zone_1", 23.0)
        mock_api.set_zone_temperature.assert_called()

    @pytest.mark.asyncio
    async def test_zone_state_and_index_validation(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        mock_api.create_command = MagicMock(return_value={"cmd": "zone"})
        mock_api.send_command = AsyncMock()
        await coordinator_instance.set_zone_state("zone_1", enable=False)
        await coordinator_instance.set_zone_state(0, enable=True)
        with pytest.raises(ValueError, match="out of range"):
            coordinator_instance._validate_zone_index(99, 2)

    @pytest.mark.asyncio
    async def test_zone_state_concurrent_updates_use_cumulative_state(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
    ) -> None:
        """Test concurrent zone toggles preserve earlier optimistic changes."""
        coordinator_instance.async_request_refresh = AsyncMock()
        coordinator_instance.last_data["main"]["EnabledZones"] = [
            True,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
        ]
        coordinator_instance.last_data["zones"]["zone_1"]["is_enabled"] = True
        coordinator_instance.last_data["zones"]["zone_2"] = {
            "name": "Bedroom",
            "is_enabled": True,
            "capabilities": ZoneCapabilities(
                exists=True,
                can_operate=True,
                has_temp_control=True,
                has_separate_targets=False,
                target_temp_cool=24.0,
                target_temp_heat=22.0,
                peripheral_capabilities=None,
            ),
        }

        commands_sent: list[dict[str, Any]] = []
        first_command_started = asyncio.Event()
        release_first_command = asyncio.Event()

        mock_api.create_command = MagicMock(
            side_effect=lambda command_type, **kwargs: {
                "cmd": command_type,
                "zones": kwargs["zones"].copy(),
            }
        )

        async def send_command(_device_id: str, command: dict[str, Any]) -> None:
            commands_sent.append(command)
            if len(commands_sent) == 1:
                first_command_started.set()
                await release_first_command.wait()

        mock_api.send_command = AsyncMock(side_effect=send_command)

        first_toggle = asyncio.create_task(
            coordinator_instance.set_zone_state("zone_1", enable=False)
        )
        await first_command_started.wait()

        second_toggle = asyncio.create_task(
            coordinator_instance.set_zone_state("zone_2", enable=False)
        )
        await asyncio.sleep(0)

        assert len(commands_sent) == 1
        assert commands_sent[0]["zones"][:2] == [False, True]

        release_first_command.set()
        await asyncio.gather(first_toggle, second_toggle)

        assert len(commands_sent) == 2
        assert commands_sent[1]["zones"][:2] == [False, False]
        assert coordinator_instance.last_data["main"]["EnabledZones"][:2] == [
            False,
            False,
        ]
        assert coordinator_instance.last_data["zones"]["zone_1"]["is_enabled"] is False
        assert coordinator_instance.last_data["zones"]["zone_2"]["is_enabled"] is False

    @pytest.mark.asyncio
    async def test_bulk_zone_operations_and_execute(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        coordinator_instance.set_zone_state = AsyncMock()
        coordinator_instance.set_zone_temperature = AsyncMock()

        result_enable = await coordinator_instance._execute_bulk_zone_op(
            "enable", "zone_1"
        )
        assert result_enable["status"] == "success"

        result_no_temp = await coordinator_instance._execute_bulk_zone_op(
            "set_temperature", "zone_1"
        )
        assert result_no_temp["status"] == "error"

        results = await coordinator_instance.async_bulk_zone_operation(
            "set_temperature", ["zone_1"], temperature=23.0
        )
        assert results[0]["status"] in {"success", "error"}

        coordinator_instance.enable_zone_control = False
        with pytest.raises(ConfigurationError):
            await coordinator_instance.async_bulk_zone_operation("enable", ["zone_1"])

        coordinator_instance.enable_zone_control = True
        with pytest.raises(ConfigurationError):
            await coordinator_instance.async_bulk_zone_operation("invalid", ["zone_1"])

    def test_parse_and_convert_helpers(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        assert coordinator_instance._convert_damper_position(None) == 0
        assert coordinator_instance._convert_damper_position(10) == 50
        assert coordinator_instance._convert_damper_position("bad") == 0

        assert coordinator_instance._parse_outdoor_temp(22.0, {}) == 22.0
        assert (
            coordinator_instance._parse_outdoor_temp(
                3000.0,
                {"AmbientSensErr": False, "AmbTemp": 18.0},
            )
            == 18.0
        )
        assert coordinator_instance._parse_outdoor_temp(3000.0, {}) is None

        warnings = coordinator_instance._parse_warnings(
            {
                "ErrCode": 2,
                "OutdoorUnit": {"ErrCode_1": 1, "LPErr": 3, "HPErr": 4},
            }
        )
        assert len(warnings) >= 3

    @pytest.mark.asyncio
    async def test_zone_preset_management_methods(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        coordinator_instance.set_zone_state = AsyncMock()
        coordinator_instance.set_zone_temperature = AsyncMock()
        coordinator_instance.zone_preset_manager.async_load = AsyncMock()
        coordinator_instance.zone_preset_manager.async_create_preset = AsyncMock()

        await coordinator_instance.async_initialize_zone_management()
        await coordinator_instance.async_create_zone_preset_from_current(
            "Sleep", "desc"
        )
        coordinator_instance.zone_preset_manager.async_create_preset.assert_called_once()

        preset = MagicMock()
        preset.zones = {
            "zone_1": {"enabled": True, "temp_cool": 23.0, "temp_heat": 21.0}
        }
        coordinator_instance.zone_preset_manager.get_preset = MagicMock(
            return_value=preset
        )
        await coordinator_instance.async_apply_zone_preset("Sleep")

        coordinator_instance.zone_preset_manager.get_preset = MagicMock(
            return_value=None
        )
        with pytest.raises(ConfigurationError):
            await coordinator_instance.async_apply_zone_preset("Missing")


class TestCoordinatorRemainingBranches:
    """Targeted tests for remaining uncovered coordinator branches."""

    @pytest.mark.asyncio
    async def test_update_data_error_variants(
        self, coordinator_instance: ActronDataCoordinator, mock_api: MagicMock
    ) -> None:
        mock_api.is_api_healthy = MagicMock(return_value=True)
        coordinator_instance.last_data = None

        mock_api.get_ac_status = AsyncMock(side_effect=RateLimitError("rate"))
        with pytest.raises(UpdateFailed):
            await coordinator_instance._async_update_data()

        mock_api.get_ac_status = AsyncMock(side_effect=DeviceOfflineError("offline"))
        with pytest.raises(UpdateFailed):
            await coordinator_instance._async_update_data()

        mock_api.get_ac_status = AsyncMock(side_effect=RuntimeError("boom"))
        with pytest.raises(UpdateFailed):
            await coordinator_instance._async_update_data()

        coordinator_instance.last_data = {"cached": True}
        result = await coordinator_instance._async_update_data()
        assert result == {"cached": True}

    @pytest.mark.asyncio
    async def test_parse_data_raises_update_failed(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        with (
            patch.object(
                coordinator_instance,
                "_extract_data_sections",
                side_effect=TypeError("bad"),
            ),
            pytest.raises(UpdateFailed),
        ):
            await coordinator_instance._parse_data({"lastKnownState": {}})

    @pytest.mark.asyncio
    async def test_parse_main_data_model_and_auto_modes(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        sections = {
            "user_aircon_settings": {"FanMode": "LOW", "Mode": "COOL"},
            "master_info": {},
            "live_aircon": {},
            "aircon_system": {"MasterWCModel": "NTB-10"},
            "indoor_unit": {"NV_AutoFanEnabled": True, "NV_ModelNumber": "CRV17AS"},
            "alerts": {},
            "remote_zone_info": [],
            "peripherals": [],
        }
        main = await coordinator_instance._parse_main_data(sections)
        assert "AUTO" in main["supported_fan_modes"]
        assert main["model"] == "CRV17AS"

    def test_misc_helpers_remaining_branches(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        assert coordinator_instance.continuous_fan is False
        coordinator_instance.continuous_fan = True
        assert coordinator_instance.continuous_fan is True

        assert coordinator_instance._get_zone_enabled({}, 0) is False

        zone_data: dict[str, Any] = {}
        capabilities = ZoneCapabilities(
            exists=True,
            can_operate=True,
            has_temp_control=True,
            has_separate_targets=False,
            target_temp_cool=24.0,
            target_temp_heat=22.0,
            peripheral_capabilities=None,
        )
        coordinator_instance._enrich_zone_with_peripheral(
            {"Sensors": {"test123456": {"NV_Kind": "invalid"}}},
            zone_data,
            capabilities,
            [],
        )
        assert zone_data == {}

        zone_data = {}
        coordinator_instance._enrich_zone_with_peripheral(
            {"Sensors": {"test123456": {"NV_Kind": "ZS: 23E01206"}}},
            zone_data,
            capabilities,
            [{"SerialNumber": "23E01206", "ControlCapabilities": {"a": 1}}],
        )
        assert zone_data["capabilities"].peripheral_capabilities == {"a": 1}

        assert coordinator_instance._validate_fan_modes(object()) == [
            "LOW",
            "MED",
            "HIGH",
        ]
        assert ActronDataCoordinator._decode_fan_mode_bitmap(
            0, ["LOW", "MED", "HIGH"]
        ) == ["LOW", "MED", "HIGH"]
        assert coordinator_instance._parse_fan_mode_list(None, ["LOW"]) == ["LOW"]

        coordinator_instance._last_raw_response = {
            "lastKnownState": {"RemoteZoneInfo": []}
        }
        assert coordinator_instance.get_zone_peripheral("zone_1") is None
        assert coordinator_instance.get_zone_last_updated("bad") is None

    def test_validate_fan_mode_remaining_branches(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        coordinator_instance.data["main"]["supported_fan_modes"] = ["TURBO"]
        assert coordinator_instance.validate_fan_mode("turbo") == "LOW"

        coordinator_instance.data = {}
        assert (
            coordinator_instance.validate_fan_mode("LOW", continuous=True) == "LOW+CONT"
        )

    def test_get_zone_peripheral_non_wireless_and_last_updated_exception(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        coordinator_instance._last_raw_response = {
            "lastKnownState": {
                "RemoteZoneInfo": [{"Sensors": {"test123456": {"NV_Kind": "WIRED"}}}],
                "AirconSystem": {"Peripherals": []},
            }
        }
        assert coordinator_instance.get_zone_peripheral("zone_1") is None

        with patch.object(
            coordinator_instance, "get_zone_peripheral", side_effect=ValueError
        ):
            assert coordinator_instance.get_zone_last_updated("zone_1") is None

    @pytest.mark.asyncio
    async def test_fan_mode_throttle_and_retry_branches(
        self, coordinator_instance: ActronDataCoordinator, mock_api: MagicMock
    ) -> None:
        coordinator_instance._last_fan_mode_change = datetime.now()
        coordinator_instance._min_fan_mode_interval = 10
        with patch(
            "custom_components.actronair_neo.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep_mock:
            await coordinator_instance._throttle_fan_mode_change()
        sleep_mock.assert_called_once()

        coordinator_instance.async_request_refresh = AsyncMock()
        coordinator_instance.async_refresh = AsyncMock()
        coordinator_instance.data = {"main": {"fan_mode": "LOW"}}
        mock_api.create_command = MagicMock(return_value={"cmd": "fan"})
        mock_api.send_command = AsyncMock(return_value={})
        await coordinator_instance._send_fan_mode_with_retry(
            "LOW+CONT", continuous=True
        )

        # Test that ApiError from send_command propagates directly
        # (no duplicate retry — API layer handles retries)
        retry_error = ApiError("retry", status_code=500)
        mock_api.send_command = AsyncMock(side_effect=retry_error)
        with pytest.raises(ApiError):
            await coordinator_instance._send_fan_mode_with_retry(
                "LOW", continuous=False
            )

        # Test continuous mode verification retry
        coordinator_instance.data = {"main": {"fan_mode": "LOW"}}
        mock_api.send_command = AsyncMock(return_value={})
        with patch(
            "custom_components.actronair_neo.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep_mock:
            await coordinator_instance._send_fan_mode_with_retry(
                "LOW+CONT", continuous=True
            )
        assert sleep_mock.await_count >= 1

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off_branch(
        self, coordinator_instance: ActronDataCoordinator, mock_api: MagicMock
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        mock_api.create_command = MagicMock(return_value={"cmd": "off"})
        mock_api.send_command = AsyncMock()
        await coordinator_instance.set_hvac_mode(HVACMode.OFF)
        mock_api.create_command.assert_called_with("OFF")

    @pytest.mark.asyncio
    async def test_zone_methods_and_presets_remaining(
        self, coordinator_instance: ActronDataCoordinator, mock_api: MagicMock
    ) -> None:
        coordinator_instance.async_request_refresh = AsyncMock()
        coordinator_instance.last_data = None
        with pytest.raises(ZoneError):
            await coordinator_instance.set_zone_temperature("zone_1", 22.0)

        coordinator_instance.last_data = {
            "zones": {
                "zone_1": {
                    "capabilities": ZoneCapabilities(
                        exists=True,
                        can_operate=True,
                        has_temp_control=False,
                        has_separate_targets=False,
                        target_temp_cool=24.0,
                        target_temp_heat=22.0,
                        peripheral_capabilities=None,
                    )
                }
            }
        }
        with pytest.raises(ZoneError):
            await coordinator_instance.set_zone_temperature("zone_1", 22.0)

        coordinator_instance.last_data = None
        mock_api.get_zone_statuses = AsyncMock(return_value=[True, False])
        mock_api.create_command = MagicMock(return_value={"cmd": "zone"})
        mock_api.send_command = AsyncMock()
        await coordinator_instance.set_zone_state("zone_1", enable=False)

        coordinator_instance.zone_preset_manager.async_load = AsyncMock(
            side_effect=RuntimeError("load")
        )
        await coordinator_instance.async_initialize_zone_management()

        coordinator_instance.last_data = None
        with pytest.raises(ConfigurationError):
            await coordinator_instance.async_create_zone_preset_from_current("A")

        preset = MagicMock()
        preset.zones = {"zone_1": {"enabled": True}}
        coordinator_instance.zone_preset_manager.get_preset = MagicMock(
            return_value=preset
        )
        coordinator_instance.enable_zone_control = False
        with pytest.raises(ConfigurationError):
            await coordinator_instance.async_apply_zone_preset("A")

        coordinator_instance.enable_zone_control = True
        coordinator_instance.set_zone_state = AsyncMock(
            side_effect=RuntimeError("zone")
        )
        coordinator_instance.last_data = {"zones": {"zone_1": {"capabilities": None}}}
        await coordinator_instance.async_apply_zone_preset("A")

        coordinator_instance.last_data = None
        await coordinator_instance._apply_zone_preset_temps("zone_1", {"temp_cool": 22})
        coordinator_instance.last_data = {"zones": {}}
        await coordinator_instance._apply_zone_preset_temps("zone_1", {"temp_cool": 22})
        coordinator_instance.last_data = {
            "zones": {
                "zone_1": {
                    "capabilities": ZoneCapabilities(
                        exists=True,
                        can_operate=True,
                        has_temp_control=False,
                        has_separate_targets=False,
                        target_temp_cool=24.0,
                        target_temp_heat=22.0,
                        peripheral_capabilities=None,
                    )
                }
            }
        }
        await coordinator_instance._apply_zone_preset_temps("zone_1", {"temp_cool": 22})

        coordinator_instance.enable_zone_control = True
        original_execute = coordinator_instance._execute_bulk_zone_op
        coordinator_instance._execute_bulk_zone_op = AsyncMock(
            side_effect=RuntimeError("bulk")
        )
        results = await coordinator_instance.async_bulk_zone_operation(
            "enable", ["zone_1"]
        )
        assert results[0]["status"] == "error"

        coordinator_instance._execute_bulk_zone_op = original_execute
        coordinator_instance.set_zone_state = AsyncMock()
        await coordinator_instance._execute_bulk_zone_op("disable", "zone_1")


class TestStaleStateHandling:
    """Tests for the stale-state resilience fixes (issue #112)."""

    @pytest.mark.asyncio
    async def test_command_forces_fresh_fetch(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
        mock_api_response: dict[str, Any],
    ) -> None:
        """After a command the next fetch bypasses the response cache."""
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(return_value=mock_api_response)
        mock_api.create_command = MagicMock(return_value={"cmd": "on"})
        mock_api.send_command = AsyncMock()
        # Stub the scheduled refresh so we can inspect the flag before the
        # follow-up update consumes it.
        coordinator_instance.async_request_refresh = AsyncMock()

        # Issuing a command sets the force-fresh flag.
        await coordinator_instance.turn_on()
        assert coordinator_instance._force_fresh_on_next_update is True

        # The subsequent update fetches with use_cache=False then clears it.
        await coordinator_instance._async_update_data()
        mock_api.get_ac_status.assert_called_with("TEST123456", use_cache=False)
        assert coordinator_instance._force_fresh_on_next_update is False

    @pytest.mark.asyncio
    async def test_normal_update_uses_cache(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
        mock_api_response: dict[str, Any],
    ) -> None:
        """A routine poll (no preceding command) still uses the cache."""
        mock_api.is_api_healthy = MagicMock(return_value=True)
        mock_api.get_ac_status = AsyncMock(return_value=mock_api_response)

        await coordinator_instance._async_update_data()

        mock_api.get_ac_status.assert_called_with("TEST123456", use_cache=True)

    @pytest.mark.asyncio
    async def test_zone_override_expires_after_ttl(
        self,
        coordinator_instance: ActronDataCoordinator,
    ) -> None:
        """An unconfirmed zone override is dropped once its TTL elapses."""
        coordinator_data = {
            "main": {"EnabledZones": [False, False]},
            "zones": {"zone_1": {"is_enabled": False}},
        }

        # A fresh override is enforced even though the API disagrees.
        coordinator_instance._pending_zone_state_overrides[0] = (
            True,
            datetime.now(),
        )
        coordinator_instance._apply_pending_zone_state_overrides(coordinator_data)
        assert coordinator_data["main"]["EnabledZones"][0] is True
        assert 0 in coordinator_instance._pending_zone_state_overrides

        # An expired override is discarded and the API value shows through.
        coordinator_data["main"]["EnabledZones"][0] = False
        coordinator_instance._pending_zone_state_overrides[0] = (
            True,
            datetime.now() - timedelta(seconds=300),
        )
        coordinator_instance._apply_pending_zone_state_overrides(coordinator_data)
        assert coordinator_data["main"]["EnabledZones"][0] is False
        assert 0 not in coordinator_instance._pending_zone_state_overrides

    @pytest.mark.asyncio
    async def test_unhealthy_api_logs_warning(
        self,
        coordinator_instance: ActronDataCoordinator,
        mock_api: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Serving stale data while degraded emits a warning for visibility."""
        coordinator_instance.last_data = {"cached": "data"}
        mock_api.is_api_healthy = MagicMock(return_value=False)
        mock_api.error_count = 7

        with caplog.at_level("WARNING"):
            result = await coordinator_instance._async_update_data()

        assert result == {"cached": "data"}
        assert "serving last known data" in caplog.text


class TestCoordinatorPushIntegration:
    """Tests for the realtime push integration on the coordinator."""

    @pytest.mark.asyncio
    async def test_handle_push_full_replaces_and_publishes(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        c._last_raw_response = {"lastKnownState": {"RemoteZoneInfo": [{"z": 1}]}}
        c._parse_data_optimized = AsyncMock(
            return_value={"zones": {"zone_1": {}}, "main": {"is_on": True}}
        )
        c.async_set_updated_data = MagicMock()
        await c._handle_push_update(
            {"lastKnownState": {"UserAirconSettings": {"isOn": True}}}, "full"
        )
        state = c._last_raw_response["lastKnownState"]
        # New section merged in; prior RemoteZoneInfo preserved.
        assert state["UserAirconSettings"] == {"isOn": True}
        assert state["RemoteZoneInfo"] == [{"z": 1}]
        c.async_set_updated_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_push_delta_merges(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        c._last_raw_response = {
            "lastKnownState": {
                "UserAirconSettings": {"isOn": True, "Mode": "COOL"},
                "RemoteZoneInfo": [{"z": 1}],
            }
        }
        c._parse_data_optimized = AsyncMock(return_value={"zones": {"zone_1": {}}})
        c.async_set_updated_data = MagicMock()
        await c._handle_push_update(
            {"lastKnownState": {"UserAirconSettings": {"isOn": False}}}, "delta"
        )
        state = c._last_raw_response["lastKnownState"]
        # Scalar overwritten, sibling key kept, untouched section preserved.
        assert state["UserAirconSettings"] == {"isOn": False, "Mode": "COOL"}
        assert state["RemoteZoneInfo"] == [{"z": 1}]

    @pytest.mark.asyncio
    async def test_handle_push_full_status_without_zone_info_preserves_zones(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """A push lacking RemoteZoneInfo must not blank zones (issue regression)."""
        c = coordinator_instance
        c._last_raw_response = {
            "lastKnownState": {"RemoteZoneInfo": [{"z": 1}], "LiveAircon": {"a": 1}}
        }
        captured: dict = {}

        async def _capture(data):
            captured["state"] = data["lastKnownState"]
            return {"zones": {"zone_1": {}}}

        c._parse_data_optimized = _capture
        c.async_set_updated_data = MagicMock()
        # full-status carrying only LiveAircon — no RemoteZoneInfo.
        await c._handle_push_update(
            {"lastKnownState": {"LiveAircon": {"a": 2}}}, "full"
        )
        # The data handed to the parser still has the prior RemoteZoneInfo.
        assert captured["state"]["RemoteZoneInfo"] == [{"z": 1}]
        c.async_set_updated_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_push_rolls_back_when_zones_would_blank(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """A push parsing to zero zones is ignored when we had zones."""
        c = coordinator_instance
        prior_raw = {"lastKnownState": {"RemoteZoneInfo": [{"z": 1}]}}
        c._last_raw_response = prior_raw
        c.last_data = {"zones": {"zone_1": {"is_enabled": True}}}
        c._parse_data_optimized = AsyncMock(return_value={"zones": {}})
        c.async_set_updated_data = MagicMock()
        await c._handle_push_update({"lastKnownState": {"RemoteZoneInfo": []}}, "full")
        # Update suppressed; last good state retained.
        c.async_set_updated_data.assert_not_called()
        assert c.last_data == {"zones": {"zone_1": {"is_enabled": True}}}
        assert c._last_raw_response is prior_raw

    @pytest.mark.asyncio
    async def test_handle_push_event_applies_flattened_paths(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """A status-change event applies flattened paths onto the state."""
        c = coordinator_instance
        c._last_raw_response = {
            "lastKnownState": {
                "UserAirconSettings": {"Mode": "HEAT"},
                "RemoteZoneInfo": [{"LiveTemp_oC": 20.0}],
            }
        }
        captured: dict = {}

        async def _capture(data):
            captured["state"] = data["lastKnownState"]
            return {"zones": {"zone_1": {}}}

        c._parse_data_optimized = _capture
        c.async_set_updated_data = MagicMock()
        await c._handle_push_update(
            {
                "event": {
                    "type": "status-change-broadcast",
                    "UserAirconSettings.Mode": "COOL",
                    "RemoteZoneInfo[0].LiveTemp_oC": 24.2,
                },
                "wcFirmware": "2.6.2.3",
            },
            "delta",
        )
        # The flattened paths were un-flattened into the parsed state.
        assert captured["state"]["UserAirconSettings"]["Mode"] == "COOL"
        assert captured["state"]["RemoteZoneInfo"][0]["LiveTemp_oC"] == 24.2
        c.async_set_updated_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_push_swallows_parse_error(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        c._parse_data_optimized = AsyncMock(side_effect=RuntimeError("bad"))
        c.async_set_updated_data = MagicMock()
        await c._handle_push_update({}, "full")  # must not raise
        c.async_set_updated_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_push_noop_when_disabled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        c.enable_push = False
        await c.async_start_push()
        assert c._push_transport is None

    @pytest.mark.asyncio
    async def test_start_push_nonfatal_on_discovery_error(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        c.enable_push = True
        c.api.get_realtime_connection_details = AsyncMock(side_effect=ApiError("nope"))
        await c.async_start_push()  # must not raise
        assert c._push_transport is None

    @pytest.mark.asyncio
    async def test_start_push_nonfatal_on_auth_error(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        from custom_components.actronair_neo.exceptions import AuthenticationError

        c = coordinator_instance
        c.enable_push = True
        c.api.get_realtime_connection_details = AsyncMock(
            side_effect=AuthenticationError("401")
        )
        await c.async_start_push()  # must not raise
        assert c._push_transport is None

    def test_push_state_disabled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        coordinator_instance.enable_push = False
        assert coordinator_instance.push_state is PushState.DISABLED

    @pytest.mark.asyncio
    async def test_handle_push_clears_parse_cache_before_parsing(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Cache cleared before parse; identical-hash pushes still propagate (#112)."""
        c = coordinator_instance
        calls: list[str] = []
        real_clear = c._clear_parse_cache

        def _spy_clear() -> None:
            calls.append("clear")
            real_clear()

        async def _fake_parse(_data):
            calls.append("parse")
            return {"zones": {"zone_1": {}}, "main": {}}

        c._clear_parse_cache = _spy_clear
        c._parse_data_optimized = _fake_parse
        c.async_set_updated_data = MagicMock()
        await c._handle_push_update({"x": 1}, "full")
        assert calls == ["clear", "parse"]
        c.async_set_updated_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_push_noop_when_no_details(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        c.enable_push = True
        c.api.get_realtime_connection_details = AsyncMock(return_value=None)
        await c.async_start_push()
        assert c._push_transport is None

    @pytest.mark.asyncio
    async def test_start_push_noop_when_factory_returns_none(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        from custom_components.actronair_neo.api.push.models import (
            RealtimeConnectionDetails,
        )

        c = coordinator_instance
        c.enable_push = True
        c.api.get_realtime_connection_details = AsyncMock(
            return_value=RealtimeConnectionDetails(
                endpoint="h", port=8883, protocol="ssl", user_id="u"
            )
        )
        # api is a MagicMock so platform is a settable attribute; "que" is an
        # unsupported platform that causes create_push_transport to return None.
        c.api.platform = "que"
        await c.async_start_push()
        assert c._push_transport is None

    @pytest.mark.asyncio
    async def test_stop_push_cancels_task_and_resets(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        c = coordinator_instance
        transport = AsyncMock()
        c._push_transport = transport

        async def _run() -> None:
            await asyncio.Event().wait()

        c._push_task = asyncio.create_task(_run())
        await c.async_stop_push()
        transport.stop.assert_awaited_once()
        assert c._push_transport is None
        assert c._push_task is None

    def test_push_state_stale_when_heartbeat_old(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        import datetime as dt

        c = coordinator_instance
        c.enable_push = True
        transport = MagicMock()
        transport.state = PushState.CONNECTED
        transport.last_heartbeat = dt.datetime.now() - dt.timedelta(seconds=10000)
        c._push_transport = transport
        assert c.push_state is PushState.STALE

    def test_push_state_passthrough_when_fresh(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        import datetime as dt

        c = coordinator_instance
        c.enable_push = True
        transport = MagicMock()
        transport.state = PushState.CONNECTED
        transport.last_heartbeat = dt.datetime.now()
        c._push_transport = transport
        assert c.push_state is PushState.CONNECTED


class TestOutdoorUnitScaling:
    """Regression tests for outdoor-unit telemetry scaling (GitHub issue #133).

    NTW-series (Advance/Inverter) units report SupplyVoltage_Vac at 1/10th
    of the true value and CompPower at 1/100th of the true value.  The
    coordinator must apply the correction factors from const.py so that
    downstream sensors receive engineering-unit values.
    """

    def _make_sections(
        self,
        comp_power: float = 45,
        voltage: float = 23.0,
        current: float = 19.0,
        capacity_kw: float = 13.0,
        family: str = "Tru-Inverter",
    ) -> dict:
        """Build a minimal data_sections dict for _parse_outdoor_unit_data."""
        return {
            "live_aircon": {
                "OutdoorUnit": {
                    "CompPower": comp_power,
                    "SupplyVoltage_Vac": voltage,
                    "SupplyCurrentRMS_A": current,
                    "CompressorOn": True,
                    "CompSpeed": 3000,
                }
            },
            "aircon_system": {
                "OutdoorUnit": {
                    "Family": family,
                    "CtrlBoardType": "Type 300",
                    "Capacity_kW": capacity_kw,
                }
            },
        }

    def test_ntw_scaling_applied(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Raw NTW-1000 values are scaled to correct engineering units."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(comp_power=45, voltage=23.0, current=19.0)
        )

        # CompPower: raw 45 x 100 = 4500 W
        assert result["comp_power"] == pytest.approx(4500.0)
        # SupplyVoltage_Vac: raw 23.0 x 10 = 230.0 V
        assert result["supply_voltage"] == pytest.approx(230.0)
        # supply_current and capacity_kw must NOT be scaled
        assert result["supply_current"] == pytest.approx(19.0)
        assert result["capacity_kw"] == pytest.approx(13.0)

    def test_zero_fields_are_not_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Raw 0 values must remain 0 (no false-scaling artefact)."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(comp_power=0, voltage=0.0)
        )

        assert result["comp_power"] == 0
        assert result["supply_voltage"] == 0

    def test_absent_fields_default_to_zero(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Completely absent CompPower / SupplyVoltage_Vac default to 0."""
        sections = {
            "live_aircon": {"OutdoorUnit": {}},
            "aircon_system": {"OutdoorUnit": {}},
        }
        result = coordinator_instance._parse_outdoor_unit_data(sections)

        assert result["comp_power"] == 0
        assert result["supply_voltage"] == 0

    def test_supply_current_typo_fallback(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """API typo variant 'SuppyCurrentRMS_A' is accepted for supply_current."""
        sections = {
            "live_aircon": {
                "OutdoorUnit": {
                    "CompPower": 45,
                    "SupplyVoltage_Vac": 23.0,
                    "SuppyCurrentRMS_A": 19.0,  # intentional typo (API bug)
                }
            },
            "aircon_system": {
                "OutdoorUnit": {
                    "Family": "Tru-Inverter",  # NTW-series: scaling must apply
                }
            },
        }
        result = coordinator_instance._parse_outdoor_unit_data(sections)

        assert result["supply_current"] == pytest.approx(19.0)
        assert result["comp_power"] == pytest.approx(4500.0)
        assert result["supply_voltage"] == pytest.approx(230.0)

    def test_classic_unit_not_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Classic (Fixed Speed) units must NOT have scaling applied to telemetry."""
        sections = {
            "live_aircon": {
                "OutdoorUnit": {
                    "CompPower": 4500,  # already in Watts — must NOT be multiplied
                    "SupplyVoltage_Vac": 230.0,  # already in VAC — must NOT scale
                    "SupplyCurrentRMS_A": 19.0,
                    "CompressorOn": True,
                    "CompSpeed": 0,
                }
            },
            "aircon_system": {
                "OutdoorUnit": {
                    "Family": "Fixed Speed: Classic",
                    "CtrlBoardType": "Type 100",
                    "Capacity_kW": 5.0,
                }
            },
        }
        result = coordinator_instance._parse_outdoor_unit_data(sections)

        # Values must pass through unscaled for Classic units
        assert result["comp_power"] == pytest.approx(4500.0)
        assert result["supply_voltage"] == pytest.approx(230.0)
        assert result["supply_current"] == pytest.approx(19.0)

    THREE_PHASE_FAMILY = "Inverter: Advance Series I Three Phase"

    def test_three_phase_idle_payload_not_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Reported idle three-phase payload passes through unscaled (#189)."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(
                comp_power=0,
                voltage=698.0,
                current=0.0,
                capacity_kw=24.0,
                family=self.THREE_PHASE_FAMILY,
            )
        )

        assert result["comp_power"] == 0
        # 698.0, not 6980.0
        assert result["supply_voltage"] == pytest.approx(698.0)
        assert result["supply_current"] == pytest.approx(0.0)

    def test_three_phase_running_power_not_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Three-phase CompPower is already in W (reported history, #189)."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(
                comp_power=3276,
                voltage=669.0,
                current=0.0,
                capacity_kw=24.0,
                family=self.THREE_PHASE_FAMILY,
            )
        )

        # 3276 W, not 327600 W
        assert result["comp_power"] == pytest.approx(3276.0)
        assert result["supply_voltage"] == pytest.approx(669.0)

    def test_three_phase_marker_case_insensitive(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Synthetic capitalisation variant: the marker match ignores case."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(
                comp_power=3276,
                voltage=669.0,
                family="Inverter: Advance Series I THREE PHASE",
            )
        )

        assert result["comp_power"] == pytest.approx(3276.0)
        assert result["supply_voltage"] == pytest.approx(669.0)


class TestSinglePhasePowerFormat:
    """Native-watt single-phase Inverter units are detected and latched (#200)."""

    def _make_sections(
        self,
        comp_power: Any = 2975,
        voltage: Any = 240.0,
        family: str = "Tru-Inverter",
    ) -> dict:
        """Build a minimal data_sections dict for _parse_outdoor_unit_data."""
        return {
            "live_aircon": {
                "OutdoorUnit": {
                    "CompPower": comp_power,
                    "SupplyVoltage_Vac": voltage,
                    "SupplyCurrentRMS_A": 12.4,
                    "CompressorOn": True,
                }
            },
            "aircon_system": {"OutdoorUnit": {"Family": family}},
        }

    def test_power_above_ceiling_latches_native_watt(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Raw 2975 is reported as 2975 W, not 297,500 W, and sets the latch."""
        assert coordinator_instance.power_format == POWER_FORMAT_UNRESOLVED
        with patch.object(
            coordinator_instance._power_format_store, "async_delay_save"
        ) as delay_save:
            result = coordinator_instance._parse_outdoor_unit_data(
                self._make_sections()
            )

        assert result["comp_power"] == pytest.approx(2975.0)
        assert coordinator_instance.power_format == POWER_FORMAT_NATIVE_WATT
        delay_save.assert_called_once()
        assert delay_save.call_args.args[0]() == {"format": POWER_FORMAT_NATIVE_WATT}

    def test_low_power_after_latch_not_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """After the latch is set, low readings pass through as watts."""
        coordinator_instance._power_format = POWER_FORMAT_NATIVE_WATT
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(comp_power=60)
        )

        assert result["comp_power"] == pytest.approx(60.0)

    def test_low_power_unresolved_still_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Without the latch, readings at or below the ceiling keep the x100."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(comp_power=100, voltage=23.0)
        )

        assert result["comp_power"] == pytest.approx(10000.0)
        assert result["supply_voltage"] == pytest.approx(230.0)
        assert coordinator_instance.power_format == POWER_FORMAT_UNRESOLVED

    def test_native_voltage_not_scaled(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """A raw 240 VAC on an Inverter family passes through unchanged."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(comp_power=0, voltage=240.0)
        )

        assert result["supply_voltage"] == pytest.approx(240.0)

    def test_three_phase_does_not_latch(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """Three-phase units pass through without touching the latch."""
        result = coordinator_instance._parse_outdoor_unit_data(
            self._make_sections(
                comp_power=3276,
                voltage=669.0,
                family="Inverter: Advance Series I Three Phase",
            )
        )

        assert result["comp_power"] == pytest.approx(3276.0)
        assert coordinator_instance.power_format == POWER_FORMAT_UNRESOLVED

    @pytest.mark.asyncio
    async def test_async_setup_restores_latch(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """A stored native-watt format is restored before the first refresh."""
        with patch.object(
            coordinator_instance._power_format_store,
            "async_load",
            AsyncMock(return_value={"format": POWER_FORMAT_NATIVE_WATT}),
        ):
            await coordinator_instance._async_setup()

        assert coordinator_instance.power_format == POWER_FORMAT_NATIVE_WATT

    @pytest.mark.asyncio
    @pytest.mark.parametrize("stored", [None, {}, {"format": "bogus"}])
    async def test_async_setup_ignores_missing_or_unknown(
        self, coordinator_instance: ActronDataCoordinator, stored: Any
    ) -> None:
        """Missing or unknown stored data leaves the format unresolved."""
        with patch.object(
            coordinator_instance._power_format_store,
            "async_load",
            AsyncMock(return_value=stored),
        ):
            await coordinator_instance._async_setup()

        assert coordinator_instance.power_format == POWER_FORMAT_UNRESOLVED

    @pytest.mark.asyncio
    async def test_async_setup_load_failure_is_logged(
        self,
        coordinator_instance: ActronDataCoordinator,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A storage error does not block setup."""
        with patch.object(
            coordinator_instance._power_format_store,
            "async_load",
            AsyncMock(side_effect=OSError("disk")),
        ):
            await coordinator_instance._async_setup()

        assert coordinator_instance.power_format == POWER_FORMAT_UNRESOLVED
        assert "Failed to load the stored compressor power format" in caplog.text

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(45, 45.0), ("23.5", 23.5), (True, None), ("n/a", None), (None, None)],
    )
    def test_as_float(self, value: Any, expected: float | None) -> None:
        """Telemetry coercion rejects booleans and non-numeric values."""
        assert _as_float(value) == expected

    def test_numeric_string_values_are_coerced(
        self, coordinator_instance: ActronDataCoordinator
    ) -> None:
        """String telemetry is compared and scaled as a number."""
        sections = self._make_sections(comp_power="2975", voltage="23")
        result = coordinator_instance._parse_outdoor_unit_data(sections)

        assert result["comp_power"] == pytest.approx(2975.0)
        assert result["supply_voltage"] == pytest.approx(230.0)


class TestQuietModeSupport:
    """Quiet mode support comes from QuietModeEnabled's presence (#199)."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("settings", "supported", "quiet_mode"),
        [
            ({"QuietModeEnabled": True}, True, True),
            ({"QuietModeEnabled": False}, True, False),
            ({"QuietMode": True, "QuietModeEnabled": False}, True, True),
            ({}, False, False),
        ],
    )
    async def test_quiet_mode_supported(
        self,
        coordinator_instance: ActronDataCoordinator,
        settings: dict[str, Any],
        *,
        supported: bool,
        quiet_mode: bool,
    ) -> None:
        """Quiet mode being off does not hide the capability."""
        sections = {
            "user_aircon_settings": {"FanMode": "LOW", "Mode": "COOL", **settings},
            "master_info": {},
            "live_aircon": {},
            "aircon_system": {},
            "indoor_unit": {},
            "alerts": {},
            "remote_zone_info": [],
            "peripherals": [],
        }
        main = await coordinator_instance._parse_main_data(sections)

        assert main["quiet_mode_supported"] is supported
        assert main["quiet_mode"] is quiet_mode
