"""Tests for the ActronAir Neo sensor platform."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.actronair_neo.const import ATTR_BATTERY_LEVEL, ATTR_ZONE_TYPE
from custom_components.actronair_neo.sensor import (
    ActronCompressorEnergySensor,
    ActronCompressorPowerSensor,
    ActronConnectivitySensor,
    ActronMainSensor,
    ActronOutdoorTemperatureSensor,
    ActronPerformanceSensor,
    ActronServiceReminderSensor,
    ActronSystemDiagnosticSensor,
    ActronZoneBatterySensor,
    ActronZoneHumiditySensor,
    ActronZoneSensor,
    async_setup_entry,
)

from .conftest import create_mock_coordinator


@pytest.fixture
def coordinator(mock_api, mock_status):
    """Create a coordinator for sensor tests."""
    coord = create_mock_coordinator(MagicMock(), mock_api, mock_status)
    coord.last_update_success = True
    coord.get_zone_peripheral = MagicMock(return_value={})
    return coord


class TestHelperFunctions:
    """Test power monitoring support via coordinator."""

    def test_supports_power_monitoring_false_on_no_data(self, coordinator):
        coordinator.data = None
        coordinator.supports_power_monitoring = MagicMock(return_value=False)
        assert coordinator.supports_power_monitoring() is False

    def test_supports_power_monitoring_true(self, coordinator, mock_status):
        mock_status["outdoor_unit"]["comp_power"] = 700
        mock_status["outdoor_unit"]["supply_voltage"] = 230.0
        mock_status["outdoor_unit"]["supply_current"] = 3.0
        mock_status["outdoor_unit"]["compressor_on"] = True
        mock_status["outdoor_unit"]["family"] = "Advance"
        mock_status["outdoor_unit"]["ctrl_board_type"] = "Type 300"
        coordinator.supports_power_monitoring = MagicMock(return_value=True)
        assert coordinator.supports_power_monitoring() is True

    def test_supports_power_monitoring_false_fixed_speed(
        self, coordinator, mock_status
    ):
        mock_status["outdoor_unit"]["family"] = "Fixed Speed"
        mock_status["outdoor_unit"]["ctrl_board_type"] = "Type 100"
        mock_status["outdoor_unit"]["comp_power"] = 0
        mock_status["outdoor_unit"]["compressor_on"] = True
        coordinator.supports_power_monitoring = MagicMock(return_value=False)
        assert coordinator.supports_power_monitoring() is False


class TestAsyncSetupEntry:
    """Test platform setup entry."""

    @pytest.mark.asyncio
    async def test_setup_adds_entities(self, coordinator, mock_status):
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        added: list = []

        mock_status["main"]["outdoor_temp"] = 21.0
        mock_status["zones"]["zone_1"]["battery_level"] = 80
        mock_status["zones"]["zone_1"]["humidity"] = 50

        await async_setup_entry(MagicMock(), mock_entry, added.extend)

        names = {type(entity).__name__ for entity in added}
        assert "ActronMainSensor" in names
        assert "ActronSystemDiagnosticSensor" in names
        assert "ActronConnectivitySensor" in names
        assert "ActronPerformanceSensor" in names
        assert "ActronServiceReminderSensor" in names
        assert "ActronOutdoorTemperatureSensor" in names
        assert "ActronZoneSensor" in names
        assert "ActronZoneHumiditySensor" in names
        assert "ActronZoneBatterySensor" in names


class TestMainAndZoneSensors:
    """Test main and zone sensors."""

    def test_main_sensor_values(self, coordinator):
        sensor = ActronMainSensor(coordinator)
        assert sensor.native_value == 22.5
        assert sensor.extra_state_attributes["Inside Humidity"] == 45.0

    def test_zone_sensor_native_and_available(self, coordinator, mock_status):
        sensor = ActronZoneSensor(coordinator, "zone_1")
        assert sensor.native_value == 22.0
        assert sensor.available is True

        mock_status["zones"]["zone_1"]["temp"] = None
        assert sensor.available is False

    def test_zone_sensor_format_signal(self, coordinator):
        sensor = ActronZoneSensor(coordinator, "zone_1")
        assert "Excellent" in sensor._format_signal_strength(-45)
        assert "Good" in sensor._format_signal_strength(-55)
        assert "Fair" in sensor._format_signal_strength(-65)
        assert "Poor" in sensor._format_signal_strength(-80)
        assert sensor._format_signal_strength(None) == "Unknown"

    def test_zone_sensor_attributes_with_peripheral(self, coordinator, mock_status):
        sensor = ActronZoneSensor(coordinator, "zone_1")
        coordinator.get_zone_peripheral.return_value = {
            "RemainingBatteryCapacity_pc": 77,
            "DeviceType": "WallSensor",
            "Signal_of3": "3",
            "LastConnectionTime": "2025-01-01T00:00:00Z",
            "ConnectionState": "CONNECTED",
        }
        mock_status["zones"]["zone_1"]["battery_level"] = None
        mock_status["zones"]["zone_1"]["peripheral_type"] = None
        mock_status["zones"]["zone_1"]["signal_strength"] = None
        attrs = sensor.extra_state_attributes
        assert attrs[ATTR_BATTERY_LEVEL] == 77
        assert attrs[ATTR_ZONE_TYPE] == "WallSensor"
        assert attrs["signal_strength"] == "Excellent (3 bars)"

    def test_zone_sensor_handles_bad_data(self, coordinator):
        sensor = ActronZoneSensor(coordinator, "zone_1")
        coordinator.data["zones"] = None
        assert sensor.extra_state_attributes == {}

    def test_zone_humidity_sensor(self, coordinator, mock_status):
        sensor = ActronZoneHumiditySensor(coordinator, "zone_1")
        assert sensor.native_value == 45.0
        assert sensor.available is True
        del mock_status["zones"]["zone_1"]
        assert sensor.native_value is None

    def test_zone_battery_sensor(self, coordinator, mock_status):
        sensor = ActronZoneBatterySensor(coordinator, "zone_1")
        assert sensor.native_value == 80
        attrs = sensor.extra_state_attributes
        assert attrs["sensor_type"] == "WallSensor"
        assert attrs["connection_state"] == "CONNECTED"

        del mock_status["zones"]["zone_1"]
        assert sensor.extra_state_attributes == {}


class TestDiagnosticAndConnectivitySensors:
    """Test diagnostic and connectivity sensors."""

    def test_system_diagnostic_native_value(self, coordinator, mock_status):
        sensor = ActronSystemDiagnosticSensor(coordinator)
        assert "Running" in sensor.native_value

        mock_status["main"]["is_on"] = False
        assert sensor.native_value == "Standby"

    def test_system_diagnostic_attributes_and_formatters(self, coordinator):
        sensor = ActronSystemDiagnosticSensor(coordinator)
        assert sensor._format_uptime(65) == "1m"
        assert sensor._format_uptime(-1) == "Unknown"
        assert sensor._format_temperature(21.234).endswith("°C")
        assert sensor._format_temperature("bad") == "bad"
        assert sensor._format_power_value(0) == "0 W"
        assert "kW" in sensor._format_power_value(2500)
        assert "W" in sensor._format_power_value(250)
        attrs = sensor.extra_state_attributes
        assert "model" in attrs
        assert "compressor_running" in attrs

    def test_system_diagnostic_error_path(self, coordinator):
        sensor = ActronSystemDiagnosticSensor(coordinator)
        coordinator.data = None
        assert sensor.extra_state_attributes["error"] == (
            "Failed to retrieve system diagnostics"
        )

    def test_connectivity_statuses(self, coordinator, mock_status):
        sensor = ActronConnectivitySensor(coordinator)
        mock_status["connection_meta"]["is_online"] = True
        mock_status["cloud"]["connection_state"] = "Connected"
        assert sensor.native_value == "Online"

        coordinator.last_update_success = False
        assert "Limited" in sensor.native_value

        mock_status["connection_meta"]["is_online"] = False
        mock_status["cloud"]["connection_state"] = "Disconnected"
        assert "Offline" in sensor.native_value

    def test_connectivity_attrs_and_signal_format(self, coordinator):
        sensor = ActronConnectivitySensor(coordinator)
        signal = sensor._format_wifi_signal(-45)
        assert signal["bars"] == "4/4"
        assert sensor._format_wifi_signal(None)["quality"] == "Unknown"
        attrs = sensor.extra_state_attributes
        assert "cloud_connection" in attrs
        assert "device_online" in attrs

    def test_connectivity_error_paths(self, coordinator):
        sensor = ActronConnectivitySensor(coordinator)
        coordinator.data = {
            "connection_meta": {"is_online": False},
            "cloud": {"connection_state": "Unknown"},
        }
        assert sensor.native_value == "Offline"


class TestPerformanceAndPowerSensors:
    """Test performance/power/energy/outdoor/service sensors."""

    def test_performance_sensor_paths(self, coordinator, mock_status):
        sensor = ActronPerformanceSensor(coordinator)
        assert sensor.available is True
        assert sensor.native_value is not None

        attrs = sensor.extra_state_attributes
        assert "operational_status" in attrs
        assert "active_zones" in attrs

        mock_status["live_aircon"] = {}
        assert sensor.available is False
        assert sensor.extra_state_attributes["status"] == "No live data available"

    def test_performance_helpers(self, coordinator):
        sensor = ActronPerformanceSensor(coordinator)
        assert sensor._format_temperature(None) == "Unknown"
        assert sensor._format_temperature(23) == "23.0°C"
        assert sensor._format_power(None) == "Unknown"
        assert sensor._format_power(800) == "800 W"
        assert sensor._format_power(1800).endswith("kW")
        assert sensor._get_operational_status({"system_on": False}) == "Standby"

    def test_compressor_power_sensor_paths(self, coordinator, mock_status):
        sensor = ActronCompressorPowerSensor(coordinator)
        mock_status["live_aircon"]["system_on"] = False
        assert sensor.native_value == 0.0

        mock_status["live_aircon"]["system_on"] = True
        mock_status["outdoor_unit"]["comp_power"] = -10
        assert sensor.native_value == 0.0
        assert "compressor_running" in sensor.extra_state_attributes

        mock_status["live_aircon"] = {}
        assert sensor.extra_state_attributes["error"] == (
            "No live aircon data available"
        )

    def test_compressor_energy_sensor_paths(self, coordinator, mock_status):
        sensor = ActronCompressorEnergySensor(coordinator)
        first = sensor.native_value
        assert first is not None
        attrs = sensor.extra_state_attributes
        assert attrs["integration_method"] == "trapezoidal"

        mock_status["live_aircon"] = {}
        assert sensor.native_value is None
        assert sensor.extra_state_attributes["error"] == (
            "No live aircon data available"
        )

    def test_outdoor_and_service_sensors(self, coordinator, mock_status):
        outdoor = ActronOutdoorTemperatureSensor(coordinator)
        service = ActronServiceReminderSensor(coordinator)
        mock_status["main"]["outdoor_temp"] = 19.5
        mock_status["main"]["service_reminder_time"] = "30d"
        mock_status["main"]["service_reminder_enabled"] = True

        assert outdoor.native_value == 19.5
        assert outdoor.available is True
        assert service.native_value == "30d"
        assert service.extra_state_attributes["enabled"] is True

        mock_status["main"]["outdoor_temp"] = None
        assert outdoor.available is False


class TestSensorRemainingBranches:
    """Targeted tests for remaining uncovered sensor branches."""

    def test_supports_power_monitoring_edge_paths(self, coordinator, mock_status):
        mock_status["outdoor_unit"] = {}
        coordinator.supports_power_monitoring = MagicMock(return_value=False)
        assert coordinator.supports_power_monitoring() is False

        mock_status["outdoor_unit"] = {
            "family": "Fixed Speed",
            "ctrl_board_type": "Type 100",
            "comp_power": 0,
            "supply_voltage": 0,
            "supply_current": 0,
            "compressor_on": True,
        }
        coordinator.supports_power_monitoring = MagicMock(return_value=False)
        assert coordinator.supports_power_monitoring() is False

    @pytest.mark.asyncio
    async def test_setup_without_power_sensors(self, coordinator, mock_status):
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        mock_status["main"]["outdoor_temp"] = None
        mock_status["zones"]["zone_1"]["humidity"] = None
        mock_status["zones"]["zone_1"]["battery_level"] = None

        added: list = []
        coordinator.supports_power_monitoring = MagicMock(return_value=False)
        await async_setup_entry(MagicMock(), mock_entry, added.extend)

        names = {type(entity).__name__ for entity in added}
        assert "ActronCompressorPowerSensor" not in names
        assert "ActronCompressorEnergySensor" not in names

    @pytest.mark.asyncio
    async def test_setup_with_power_sensors(self, coordinator):
        mock_entry = MagicMock()
        mock_entry.runtime_data = coordinator
        added: list = []
        coordinator.supports_power_monitoring = MagicMock(return_value=True)
        await async_setup_entry(MagicMock(), mock_entry, added.extend)
        names = {type(entity).__name__ for entity in added}
        assert "ActronCompressorPowerSensor" in names
        assert "ActronCompressorEnergySensor" in names

    def test_zone_sensor_additional_paths(self, coordinator, mock_status):
        sensor = ActronZoneSensor(coordinator, "zone_1")
        del mock_status["zones"]["zone_1"]
        assert sensor.native_value is None

        mock_status["zones"]["zone_1"] = {
            "name": "Zone 1",
            "temp": 22.0,
            "humidity": 40,
            "is_enabled": True,
            "battery_level": 70,
            "peripheral_type": "WallSensor",
            "last_connection": "2025-01-01",
            "connection_state": "CONNECTED",
            "signal_strength": -55,
        }
        attrs = sensor.extra_state_attributes
        assert attrs[ATTR_BATTERY_LEVEL] == 70
        assert attrs[ATTR_ZONE_TYPE] == "WallSensor"
        assert "signal_strength" in attrs

        coordinator.get_zone_peripheral.return_value = {"Signal_of3": "invalid"}
        attrs = sensor.extra_state_attributes
        assert attrs["signal_strength"]

    def test_zone_sensor_enrich_peripheral_fields(self, coordinator, mock_status):
        sensor = ActronZoneSensor(coordinator, "zone_1")
        mock_status["zones"]["zone_1"]["battery_level"] = None
        mock_status["zones"]["zone_1"]["peripheral_type"] = None
        mock_status["zones"]["zone_1"]["signal_strength"] = None
        mock_status["zones"]["zone_1"]["last_connection"] = None
        mock_status["zones"]["zone_1"]["connection_state"] = None
        coordinator.get_zone_peripheral.return_value = {
            "RemainingBatteryCapacity_pc": 50,
            "DeviceType": "Remote",
            "Signal_of3": "1",
            "LastConnectionTime": "now",
            "ConnectionState": "connected",
        }
        attrs = sensor.extra_state_attributes
        assert attrs["signal_strength"] == "Fair (1 bar)"
        assert attrs["connection_state"] == "connected"
        assert attrs["last_updated"] == "now"

        coordinator.get_zone_peripheral.return_value = {
            "Signal_of3": "10",
            "ConnectionState": "ok",
        }
        attrs = sensor.extra_state_attributes
        assert "dBm" in attrs["signal_strength"]

        coordinator.get_zone_peripheral.return_value = {
            "Signal_of3": "NaN",
            "ConnectionState": "ok",
        }
        attrs = sensor.extra_state_attributes
        assert attrs["signal_strength"] == "NaN"

    def test_zone_battery_sensor_keyerror_and_available(self, coordinator, mock_status):
        sensor = ActronZoneBatterySensor(coordinator, "zone_1")
        assert sensor.available is True
        del mock_status["zones"]["zone_1"]
        assert sensor.native_value is None
        assert sensor.available is False

    def test_system_diagnostic_remaining_helpers(self, coordinator):
        sensor = ActronSystemDiagnosticSensor(coordinator)
        assert sensor._format_uptime(90061) == "1d 1h 1m"
        assert sensor._format_uptime(3660) == "1h 1m"
        coordinator.data = {}
        assert sensor.native_value == "Unknown"

    def test_service_reminder_values(self, coordinator, mock_status):
        sensor = ActronSystemDiagnosticSensor(coordinator)
        mock_status["outdoor_unit"]["capacity_kw"] = 12.5
        mock_status["vft"]["supported"] = True
        mock_status["vft"]["airflow"] = 123.4
        attrs = sensor.extra_state_attributes
        assert attrs["system_capacity"] == "12.5 kW"
        assert attrs["air_volume"] == "123.4 m³/h"

    def test_connectivity_remaining_paths(self, coordinator, mock_status):
        sensor = ActronConnectivitySensor(coordinator)
        coordinator.last_update_success = True
        mock_status["connection_meta"]["is_online"] = True
        mock_status["cloud"]["connection_state"] = "Unknown"
        assert sensor.native_value == "Online (Cloud Status Unknown)"

        mock_status["cloud"]["connection_state"] = "Retrying"
        assert sensor.native_value == "Online (Cloud: Retrying)"

        signal = sensor._format_wifi_signal(-62)
        assert signal["quality"] == "Fair"
        assert sensor._format_wifi_signal(-55)["quality"] == "Good"
        assert sensor._format_wifi_signal(-75)["bars"] == "1/4"
        assert sensor._format_uptime(-1) == "Unknown"
        assert sensor._format_uptime(90000) == "1d 1h"
        assert sensor._format_uptime(3700) == "1h 1m"

        with patch.object(
            sensor, "_determine_connectivity_status", side_effect=TypeError
        ):
            assert sensor.native_value == "Unknown"

        coordinator.data = None  # Subscript on None raises TypeError
        assert sensor.extra_state_attributes["error"]

    def test_connectivity_extra_state_exception_path(self, coordinator):
        sensor = ActronConnectivitySensor(coordinator)
        coordinator.data = None  # Subscript on None raises TypeError
        assert sensor.extra_state_attributes["error"]

    def test_performance_native_exception_path(self, coordinator, mock_status):
        sensor = ActronPerformanceSensor(coordinator)
        mock_status["live_aircon"]["compressor_capacity"] = "bad"
        assert sensor.native_value is None

    def test_performance_remaining_paths(self, coordinator, mock_status):
        sensor = ActronPerformanceSensor(coordinator)
        coordinator.last_update_success = False
        assert sensor.available is False

        coordinator.last_update_success = True
        mock_status["live_aircon"].clear()
        assert sensor.native_value is None
        assert sensor.extra_state_attributes["status"] == "No live data available"

        assert sensor._format_temperature("bad") == "bad"
        assert sensor._format_power("bad") == "bad"
        assert (
            sensor._get_operational_status(
                {"system_on": True, "compressor_mode": "ON", "am_running_fan": True}
            )
            == "Active Cooling/Heating"
        )
        assert (
            sensor._get_operational_status(
                {"system_on": True, "compressor_mode": "OFF", "am_running_fan": True}
            )
            == "Fan Only"
        )
        assert (
            sensor._get_operational_status(
                {
                    "system_on": True,
                    "compressor_mode": "OFF",
                    "am_running_fan": False,
                }
            )
            == "System On (Idle)"
        )
        assert (
            sensor._get_operational_status(
                {"system_on": True, "compressor_mode": "ON", "am_running_fan": False}
            )
            == "Compressor Only"
        )

        mock_status["live_aircon"]["system_on"] = True
        with patch.object(sensor, "_get_operational_status", side_effect=TypeError):
            assert sensor.extra_state_attributes["error"]

        coordinator.data = {"live_aircon": {"system_on": True}}
        assert sensor.available is True

        coordinator.data = {"live_aircon": {}}
        assert sensor.available is False

    def test_power_and_energy_remaining_paths(self, coordinator, mock_status):
        power_sensor = ActronCompressorPowerSensor(coordinator)
        energy_sensor = ActronCompressorEnergySensor(coordinator)

        mock_status["live_aircon"].update(
            {
                "system_on": True,
                "compressor_capacity": 40,
            }
        )
        mock_status["outdoor_unit"]["comp_power"] = 800
        _ = energy_sensor.native_value
        energy_sensor._last_update = (
            energy_sensor._last_update.replace(microsecond=0)
            if energy_sensor._last_update
            else energy_sensor._last_update
        )
        _ = energy_sensor.native_value

        mock_status["live_aircon"].clear()
        assert power_sensor.native_value is None
        assert power_sensor.extra_state_attributes["error"]
        assert energy_sensor.native_value is None
        assert energy_sensor.extra_state_attributes["error"]

        mock_status["live_aircon"]["system_on"] = True
        mock_status["outdoor_unit"]["comp_power"] = "bad"
        assert power_sensor.native_value is None
        assert energy_sensor.native_value is None

        coordinator.data = MagicMock()
        coordinator.data.get = MagicMock(side_effect=TypeError)
        assert power_sensor.extra_state_attributes["error"]
        assert energy_sensor.extra_state_attributes["error"]


class TestFormatPowerHelper:
    """Tests for the module-level _format_power helper and delegating wrappers."""

    def test_module_level_format_power(self):
        from custom_components.actronair_neo.sensor import _format_power

        assert _format_power(0) == "0 W"
        assert _format_power(0.0) == "0 W"
        assert _format_power(None) == "Unknown"
        assert _format_power("Unknown") == "Unknown"
        assert _format_power(999) == "999 W"
        assert _format_power(1000) == "1.0 kW"
        assert _format_power(4500) == "4.5 kW"
        assert _format_power(230) == "230 W"
        # Non-numeric string falls back gracefully to the original string
        assert _format_power("bad") == "bad"

    def test_diagnostic_sensor_delegates_to_shared_helper(self, coordinator):
        """_format_power_value delegates to the module-level _format_power."""
        sensor = ActronSystemDiagnosticSensor(coordinator)
        assert sensor._format_power_value(0) == "0 W"
        assert sensor._format_power_value(4500) == "4.5 kW"
        assert sensor._format_power_value(800) == "800 W"

    def test_performance_sensor_delegates_to_shared_helper(self, coordinator):
        """ActronPerformanceSensor._format_power delegates to _format_power."""
        sensor = ActronPerformanceSensor(coordinator)
        assert sensor._format_power(None) == "Unknown"
        assert sensor._format_power(4500) == "4.5 kW"
        assert sensor._format_power(800) == "800 W"

    def test_corrected_comp_power_renders_as_kw(self, coordinator, mock_status):
        """After scaling, ~4500 W renders as '4.5 kW' in diagnostic attributes."""
        mock_status["outdoor_unit"]["comp_power"] = 4500.0
        sensor = ActronSystemDiagnosticSensor(coordinator)
        attrs = sensor.extra_state_attributes
        assert attrs["compressor_power"] == "4.5 kW"

    def test_corrected_supply_voltage_renders_correctly(self, coordinator, mock_status):
        """After scaling, 230.0 VAC renders as '230.0 VAC' in diagnostic attributes."""
        mock_status["outdoor_unit"]["supply_voltage"] = 230.0
        sensor = ActronSystemDiagnosticSensor(coordinator)
        attrs = sensor.extra_state_attributes
        assert attrs["supply_voltage"] == "230.0 VAC"

    def test_system_capacity_has_one_decimal(self, coordinator, mock_status):
        """system_capacity is formatted with one decimal place."""
        mock_status["outdoor_unit"]["capacity_kw"] = 13.0
        sensor = ActronSystemDiagnosticSensor(coordinator)
        attrs = sensor.extra_state_attributes
        assert attrs["system_capacity"] == "13.0 kW"


def test_compressor_energy_entity_id_change_delegates_to_base(coordinator):
    """The compressor-energy override still runs the base opt-in (#232)."""
    from unittest.mock import patch as _patch

    from custom_components.actronair_neo.entity import ActronAirNeoEntity
    from custom_components.actronair_neo.sensor import ActronCompressorEnergySensor

    sensor = ActronCompressorEnergySensor(coordinator)
    with _patch.object(ActronAirNeoEntity, "async_entity_id_changed") as base:
        sensor.async_entity_id_changed("sensor.old_compressor_energy")
    base.assert_called_once_with("sensor.old_compressor_energy")
