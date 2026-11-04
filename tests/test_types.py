"""Tests for type definitions in types.py to ensure full coverage.

TypedDicts are covered by importing the module. The class bodies are
executed at import time, so simply importing every name ensures 100%
line coverage for the module.
"""

import pytest

from custom_components.actronair_neo import types as t
from custom_components.actronair_neo.api.models import (
    FALLBACK_SUPPORTED_MODES,
    ActronAirUserInfo,
    DeviceInfo,
    MainData,
    ModeSupport,
    OutdoorUnitData,
    PeripheralData,
    ZoneData,
)


def test_module_has_all_typeddicts() -> None:
    """Verify all expected TypedDict classes are defined."""
    expected = [
        "TokenResponse",
        "DeviceInfo",
        # ZoneCapabilities is a Pydantic model in api.models (dot-accessed at
        # runtime), not a TypedDict here — see ZoneData.capabilities.
        "ZoneData",
        "MainData",
        "MasterSensorInfo",
        "LiveAirconInfo",
        "UserAirconSettings",
        "LastKnownState",
        "AcStatusResponse",
        "CommandResponse",
        "CoordinatorData",
        "PeripheralData",
        "CommandData",
        "ApiResponse",
    ]
    for name in expected:
        assert hasattr(t, name), f"Missing TypedDict: {name}"


def test_literal_types_exist() -> None:
    """Verify FanModeType and HvacModeType are defined."""
    assert hasattr(t, "FanModeType")
    assert hasattr(t, "HvacModeType")


def test_token_response_keys() -> None:
    """Verify TokenResponse has expected keys."""
    data: t.TokenResponse = {
        "access_token": "abc",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "xyz",
    }
    assert data["access_token"] == "abc"
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 3600
    assert data["refresh_token"] == "xyz"


def test_device_info_keys() -> None:
    """Verify DeviceInfo has expected keys."""
    data = t.DeviceInfo(serial="ABC", name="Test", type="Neo", id="1")
    assert data["serial"] == "ABC"


def test_zone_data_keys() -> None:
    """Verify ZoneData constructor works."""
    data = t.ZoneData(
        name="Zone 1",
        temp=22.0,
        setpoint=24.0,
        is_on=True,
        capabilities={
            "exists": True,
            "can_operate": True,
            "has_temp_control": True,
            "has_separate_targets": False,
            "target_temp_cool": 24.0,
            "target_temp_heat": 22.0,
            "peripheral_capabilities": None,
        },
        humidity=45.0,
        is_enabled=True,
        temp_setpoint_cool=24.0,
        temp_setpoint_heat=22.0,
        battery_level=80,
        signal_strength=-50,
        peripheral_type="WallSensor",
        last_connection="2025-01-01T00:00:00Z",
        connection_state="CONNECTED",
        damper_position=75,
        airflow_setpoint=50,
        airflow_control_enabled=False,
        airflow_control_locked=False,
        zone_max_position=100,
        zone_min_position=10,
    )
    assert data["name"] == "Zone 1"
    assert data["temp"] == 22.0


def test_main_data_keys() -> None:
    """Verify MainData has expected keys."""
    data = t.MainData(
        is_on=True,
        mode="COOL",
        fan_mode="AUTO",
        fan_continuous=False,
        base_fan_mode="AUTO",
        supported_fan_modes=["LOW", "MED", "HIGH"],
        temp_setpoint_cool=22.0,
        temp_setpoint_heat=20.0,
        indoor_temp=22.5,
        indoor_humidity=45.0,
        compressor_state="COOL",
        EnabledZones=[True, True],
        model="NEO-12",
        firmware_version="1.2.3",
        away_mode=False,
        quiet_mode=False,
        indoor_model=None,
        serial_number=None,
        filter_clean_required=False,
        defrosting=False,
        turbo_mode_supported=False,
        turbo_mode_enabled=False,
        after_hours_enabled=False,
        after_hours_duration=120,
        outdoor_temp=None,
        fast_heating=False,
        quiet_mode_supported=False,
        quiet_mode_active=False,
        service_reminder_enabled=False,
        service_reminder_time="NA",
        warnings=[],
    )
    assert data["is_on"] is True


def test_coordinator_data_keys() -> None:
    """Verify CoordinatorData structure."""
    data = t.CoordinatorData(
        main=t.MainData(
            is_on=False,
            mode="OFF",
            fan_mode="LOW",
            fan_continuous=False,
            base_fan_mode="LOW",
            supported_fan_modes=[],
            temp_setpoint_cool=None,
            temp_setpoint_heat=None,
            indoor_temp=None,
            indoor_humidity=None,
            compressor_state="OFF",
            EnabledZones=[],
            model="",
            firmware_version="",
            away_mode=False,
            quiet_mode=False,
            indoor_model=None,
            serial_number=None,
            filter_clean_required=False,
            defrosting=False,
            turbo_mode_supported=False,
            turbo_mode_enabled=False,
            after_hours_enabled=False,
            after_hours_duration=120,
            outdoor_temp=None,
            fast_heating=False,
            quiet_mode_supported=False,
            quiet_mode_active=False,
            service_reminder_enabled=False,
            service_reminder_time="NA",
            warnings=[],
        ),
        zones={},
        live_aircon=t.LiveAirconData(
            system_on=False,
            compressor_capacity=0,
            compressor_mode="OFF",
            am_running_fan=False,
            fan_rpm=0,
            fan_pwm=0,
            coil_inlet=None,
            err_code=0,
            compressor_chasing_temp=None,
            compressor_live_temp=None,
        ),
        outdoor_unit=t.OutdoorUnitData(
            comp_power=0,
            compressor_on=False,
            comp_speed=0,
            coil_temp=None,
            amb_temp=None,
            supply_voltage=0,
            supply_current=0,
            supply_power=0,
            reverse_valve_position=None,
            defrost_mode=False,
            drm=None,
            err_codes=[],
            family=None,
            ctrl_board_type=None,
            capacity_kw=0,
        ),
        system_status=t.SystemStatusData(
            uptime_seconds=0,
            board_temp=None,
            wifi_strength=None,
            wifi_ssid=None,
            wifi_channel=None,
            wifi_firmware=None,
            wifi_hw_errors=0,
        ),
        cloud=t.CloudConnectionData(
            connection_state="Unknown",
            session_uptime=0,
            sent_packets=0,
            received_packets=0,
            failed_sent_packets=0,
            session_count_since_reset=0,
            dns_failures=0,
            aborted_sockets=0,
        ),
        servicing=t.ServicingData(
            error_history=[],
            event_history=[],
        ),
        connection_meta=t.ConnectionMetadata(
            is_online=False,
            last_status_update=None,
            time_since_last_contact=None,
        ),
        vft=t.VFTData(
            supported=False,
            airflow=0,
        ),
    )
    assert data["main"]["is_on"] is False
    assert data["zones"] == {}


def test_peripheral_data_keys() -> None:
    """Verify PeripheralData structure."""
    data = t.PeripheralData(
        battery_level=80,
        signal_strength=-50,
        peripheral_type="WallSensor",
        last_connection="2025-01-01",
        connection_state="CONNECTED",
        ZoneAssignment=[0, 1],
        DeviceType="ZoneSensor",
        RemainingBatteryCapacity_pc=80,
        Signal_of3=2,
        LastConnectionTime="2025-01-01",
        ConnectionState="CONNECTED",
        ControlCapabilities={"humidity": True},
    )
    assert data["battery_level"] == 80


def test_command_data_keys() -> None:
    """Verify CommandData structure."""
    data = t.CommandData(UserAirconSettings={"isOn": True, "Mode": "COOL"})
    assert data["UserAirconSettings"]["isOn"] is True


def test_api_response_keys() -> None:
    """Verify ApiResponse total=False allows partial dicts."""
    data = t.ApiResponse(success=True)
    assert data["success"] is True


# ---------------------------------------------------------------------------
# api/models.py validators
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (22.5, 22.5),
        ("21", 21.0),
        (999.9, 999.9),
        (1000, None),
        (3000.0, None),
        ("abc", None),
        ([1], None),
        (True, None),
        (False, None),
        (None, None),
    ],
)
def test_temperature_sentinels(raw, expected):
    zone = ZoneData(name="Z", temp=raw, MinCoolSetpoint=raw, MaxHeatSetpoint=raw)
    assert zone.temp == expected
    assert zone.min_cool_setpoint == expected
    assert zone.max_heat_setpoint == expected
    main = MainData(indoor_temp=raw, outdoor_temp=raw)
    assert main.indoor_temp == expected
    assert main.outdoor_temp == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0.0),
        (55.5, 55.5),
        ("40", 40.0),
        (100, 100.0),
        (100.1, None),
        (-0.1, None),
        (3000.0, None),
        ("NA", None),
        ({}, None),
        (True, None),
        (None, None),
    ],
)
def test_humidity_bounds(raw, expected):
    assert ZoneData(name="Z", humidity=raw).humidity == expected
    assert MainData(indoor_humidity=raw).indoor_humidity == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (2, 2),
        (0, 0),
        ("3", 3),
        (" 1 ", 1),
        ("NA", None),
        ("", None),
        ("-1", None),
        (2.5, None),
        (True, None),
        (None, None),
    ],
)
def test_coerce_signal(raw, expected):
    assert ZoneData(name="Z", signal_strength=raw).signal_strength == expected
    assert PeripheralData(Signal_of3=raw).signal_of3 == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(12345, "12345"), ("ABC", "ABC"), (True, None), (None, None)],
)
def test_optional_serial_coercion(raw, expected):
    assert PeripheralData(SerialNumber=raw).serial_number == expected
    main = MainData(serial_number=raw, indoor_model=raw)
    assert main.serial_number == expected
    assert main.indoor_model == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(561, "561"), ("X", "X"), (None, ""), (False, "")],
)
def test_required_string_coercion(raw, expected):
    main = MainData(model=raw, firmware_version=raw)
    assert (main.model, main.firmware_version) == (expected, expected)
    outdoor = OutdoorUnitData(
        model_number=raw,
        family=raw,
        ctrl_board_type=raw,
        software_version=raw,
        SerialNumber=raw,
    )
    assert outdoor.model_number == expected
    assert outdoor.family == expected
    assert outdoor.ctrl_board_type == expected
    assert outdoor.software_version == expected
    assert outdoor.serial_number == expected


def test_device_info_coerces_strings():
    info = DeviceInfo(serial=None, name=42, type=True, id=7)
    assert (info.serial, info.name, info.type, info.id) == ("", "42", "", "7")


def test_mode_support_defaults_and_dry():
    assert ModeSupport().supported_modes == ["COOL", "HEAT", "FAN", "AUTO"]
    support = ModeSupport(Cool=False, Heat=True, Fan=False, Auto=False, Dry=True)
    assert support.supported_modes == ["HEAT", "DRY"]


def test_mode_support_all_disabled_uses_fallback():
    support = ModeSupport(Cool=False, Heat=False, Fan=False, Auto=False, Dry=False)
    assert support.supported_modes == list(FALLBACK_SUPPORTED_MODES)


@pytest.mark.parametrize("alias", ["id", "sub", "userId"])
def test_user_info_id_aliases(alias):
    info = ActronAirUserInfo.model_validate({alias: "user-1", "email": "a@b.c"})
    assert info.id == "user-1"
    assert info.email == "a@b.c"
    assert info.name == ""


def test_user_info_defaults():
    assert ActronAirUserInfo.model_validate({}).id == ""
