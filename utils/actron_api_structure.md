# ActronAir Neo API Response Structure

Complete documentation of the ActronAir Neo cloud API response structures,
verified against a live Classic series unit in February 2026.

## Table of Contents

- [Authentication](#authentication)
- [AC Systems List](#ac-systems-list)
- [Status Response](#status-response)
  - [Envelope](#envelope)
  - [Serial-Keyed Section](#serial-keyed-section)
  - [AirconSystem](#airconsystem)
  - [UserAirconSettings](#userairconsettings)
  - [MasterInfo](#masterinfo)
  - [RemoteZoneInfo](#remotezoneinfo)
  - [LiveAircon](#liveaircon)
  - [Alerts](#alerts)
  - [NV_Limits](#nv_limits)
  - [NV_SystemSettings](#nv_systemsettings)
  - [NV_Schedule](#nv_schedule)
  - [NV_QuickTimer](#nv_quicktimer)
  - [AwayModeSavedState](#awaymodesavedstate)
  - [Servicing](#servicing)
  - [Installer](#installer)
- [Events Response](#events-response)
- [Command Structure](#command-structure)
- [Error Responses](#error-responses)

## Authentication

### OAuth 2.0 Device Code Flow

**Endpoint**: `POST /api/v0/oauth/token`
**Content-Type**: `application/x-www-form-urlencoded`

See [ActronAirNeoAPI.md](ActronAirNeoAPI.md) for the full authentication flow.

**Key constants**:

| Parameter    | Value                                          |
| ------------ | ---------------------------------------------- |
| `client_id`  | `home_assistant`                               |
| `grant_type` | `urn:ietf:params:oauth:grant-type:device_code` |
| `scope`      | `read write`                                   |

**Token refresh**:

```text
POST /api/v0/oauth/token
client_id=home_assistant&grant_type=refresh_token&refresh_token=<token>
```

**Token response**:

```json
{
  "access_token": "string",
  "token_type": "bearer",
  "expires_in": 259199,
  "refresh_token": "string"
}
```

## AC Systems List

**Endpoint**: `GET /api/v0/client/ac-systems?includeNeo=true`

```json
{
  "items": [
    {
      "serial": "string",
      "name": "string",
      "type": "string",
      "id": "string"
    }
  ],
  "_links": {
    "self": { "href": "string" }
  }
}
```

## Status Response

**Endpoint**: `GET /api/v0/client/ac-systems/status/latest?serial=<serial>`

### Envelope

Top-level fields of the status response:

```json
{
  "isOnline": true,
  "timeSinceLastContact": "00:00:35.9687845",
  "lastStatusUpdate": "2026-02-27T03:40:00+00:00",
  "lastKnownState": { "..." }
}
```

### lastKnownState Top-Level Keys

| Key                  | Description                                     |
| -------------------- | ----------------------------------------------- |
| `<SERIAL>`           | Serial-keyed section (cloud, modbus, system)    |
| `AirconSystem`       | Hardware details (indoor/outdoor unit, sensors) |
| `UserAirconSettings` | User-configurable settings (mode, temp, zones)  |
| `MasterInfo`         | Master controller readings (temp, humidity)     |
| `RemoteZoneInfo`     | Array of zone data (temp, humidity, setpoints)  |
| `LiveAircon`         | Real-time compressor and outdoor unit telemetry |
| `Alerts`             | Active alerts (clean filter, defrosting)        |
| `NV_Limits`          | Temperature setpoint limits                     |
| `NV_SystemSettings`  | System configuration (display, locks, WiFi)     |
| `NV_Schedule`        | Scheduled events                                |
| `NV_QuickTimer`      | Quick timer settings                            |
| `AwayModeSavedState` | Saved setpoints for away mode                   |
| `Servicing`          | Error and event history logs                    |
| `Installer`          | Installer contact details                       |
| `type`               | `"status-change-broadcast"`                     |
| `@metadata`          | Server metadata (connectionId, server)          |

---

### Serial-Keyed Section

Keyed by the unit's serial number (e.g., `lastKnownState.<SERIAL>`).

```json
{
  "Cloud": {
    "ConnectionState": "Connected",
    "FailedSentPackets": 0,
    "ReceivedPackets": 15321,
    "SentPackets": 6928,
    "Connection": {
      "UpTime": {
        "SinceLastMCUReset_s": 185468,
        "CurrentSession_s": 185468
      },
      "SessionCount": {
        "SinceLastMCUReset": 0,
        "PriorToLastMCUReset": 0
      },
      "ErrorCount": {
        "AbortedSockets": 0,
        "LoopbackError": 0,
        "DNSFailures": 0
      }
    }
  },
  "Modbus": {
    "LinkPort": "Opened"
  },
  "NV_SystemSettings_Local": {
    "OTA": {
      "Mode": 2,
      "CheckInterval": {
        "Mode1_Period_min": 1440,
        "Mode2_TimeOfDay": "T02:00:00"
      },
      "LastCheck": {
        "Trigger": "7",
        "Time": "NA",
        "Result": "",
        "Images": [
          {
            "ImageName": "neo2-firmware-slot2",
            "URL": "",
            "Status": "NO_UPDATE_REQUIRED",
            "CheckTime": "2026-02-27T02:06:49"
          }
        ]
      },
      "NextCheck": { "Time": "NA" },
      "InstallationStatus": {
        "TargetDevice": "0",
        "State": "IDLE",
        "Progress": 0
      }
    }
  },
  "SystemState": {
    "CpuId": "string",
    "LastShutdownReason": "Software Trigger",
    "MCUResetCountSincePOR": { "Total": 0, "Remote": 0 },
    "HardFaultDebug": {
      "Type": "0",
      "IncidentCount": 0,
      "LastIncidentTime": "NA",
      "CoreRegisterDump": {
        "R0": "0x00000000",
        "R1": "0x00000000",
        "R2": "0x00000000",
        "R3": "0x00000000",
        "R12": "0x00000000",
        "LR": "0x00000000",
        "PC": "0x00000000",
        "PSR": "0x00000000"
      }
    },
    "RTOS": {
      "BlockingTaskMonitor": {
        "Id": 0,
        "TimeStamp": "NA",
        "Parameters": [],
        "StackDump": []
      }
    },
    "WCFirmwareVersion": "NEO v2.5.0.7, Dec 12 2025 14:54:22",
    "WCBootloaderVersion": "1.0.2.0",
    "ExternalFlash": {
      "GFXAssets": {
        "Primary": {
          "Version": { "Installed": "1.1.0.2", "Required": "1.1.0.2" },
          "CRC": "OK"
        },
        "Secondary": {
          "Version": { "Installed": "1.0.4.2", "Required": "1.0.4.2" },
          "CRC": "OK"
        }
      },
      "FirmwareImages": {
        "STM32_NEO": "",
        "PIC24_ODU": "No Image",
        "PIC24_Inzone": "3.48",
        "PIC24_CMI": "3.48",
        "NRF52_BLECentral": "1.1.0.0",
        "NRF52_BLEPeripheral1": "1.1.4.2",
        "NRF52_BLEPeripheral2": "No Image",
        "WINC1500": "No Image"
      }
    }
  },
  "SystemStatus_Local": {
    "Uptime_s": 185522,
    "WifiStrength_of3": -51,
    "SensorInputs": {
      "SHTC1": {
        "RelativeHumidity_pc": 57.1,
        "Temperature_oC": 28.8
      },
      "RS485": {
        "AInput_Voltage": 1.5,
        "BInput_Voltage": 2.4,
        "Current": 2.0
      },
      "PSU_Voltage": 11.7,
      "AmbientLight": 995.0,
      "Thermistors": {
        "NearAmbient_oC": 29.1,
        "WiFi_oC": 35.5,
        "MainPCB_oC": 39.4,
        "RoomAmbient_oC": 27.3
      },
      "TOF": {
        "Enabled": true,
        "Range_mm": -1.0
      }
    },
    "WiFi": {
      "FirmwareVersion": "19.6.1",
      "DriverVersion": "19.3.0",
      "ModuleMACAddress": "60:8A:10:B3:B5:99",
      "ApSSID": "string",
      "ApBSSID": "string",
      "RFChannel": 6,
      "ConnectionCount": 1,
      "DisconnectCount": 0,
      "DeinitCount": 0,
      "HardwareErrorCount": 0
    },
    "TouchScreen": {
      "LastTouchTime": "NA",
      "State": 0,
      "XCoordinate": 231,
      "YCoordinate": 437,
      "I2CErrorCount": 0,
      "ControllerModel": "Goodix GT9271"
    },
    "TouchButton": {
      "State": 0,
      "I2CErrorCount": 142
    },
    "GUI": {
      "ActiveScreen": "DISPLAY OFF"
    },
    "BTLE": {
      "Central": {
        "Mode": "NEO2 BTLE",
        "FirmwareVersion": "1.1.0.0"
      }
    }
  }
}
```

---

### AirconSystem

Hardware identification and peripheral details.

```json
{
  "MasterWCModel": "NTW-1000",
  "MasterSerial": "22H09780",
  "MasterWCFirmwareVersion": "2.5.0.7",
  "IndoorUnit": {
    "Battery_Backup_Voltage": 3.4,
    "NV_ModelNumber": "EVA150S",
    "SerialNumber": "748836",
    "IndoorFW": "3.48",
    "NV_SupportedFanModes": 3,
    "NV_AutoFanEnabled": false
  },
  "OutdoorUnit": {
    "Family": "Fixed Speed: Classic",
    "Capacity_kW": 15,
    "ModelNumber": "0",
    "SerialNumber": "772902",
    "SoftwareVersion": "1.05",
    "CtrlBoardType": "Type 100: UnoJr (PIC24FJ128GA308)"
  },
  "WallControllers": [
    {
      "Address": "C1",
      "Type": "NEO",
      "FirmwareVersion": "NA"
    }
  ],
  "Sensors": [
    {
      "Designator": "C1",
      "Detected": true,
      "Enabled": true,
      "Temperature_oC": 27.2,
      "TemperatureOffset_oC": 0.0
    }
  ],
  "Peripherals": [
    {
      "LogicalAddress": 1,
      "DeviceType": "Zone Sensor",
      "SerialNumber": "23E01206",
      "MACAddress": "BC:06:12:14:23:CB",
      "ZoneAssignment": [2],
      "IndoorBoardSettings": {
        "Enabled": true,
        "TemperatureOffset_oC": -1.0,
        "DeviceConfig": 2
      },
      "ConnectionState": "Connected",
      "Firmware": {
        "InstalledVersion": { "NRF52": "1.1.4.2", "EFM8": "NA" },
        "Update": {
          "CurrentState": "Idle",
          "CurrentInstallProgress_pc": -1,
          "Events": {
            "LastStartTime": "NA",
            "LastCompleteTime": "NA",
            "LastFailureTime": "NA",
            "LastFailureStep": "Idle"
          },
          "RunCount": 0,
          "FailureCount": 0
        }
      },
      "LastConnectionTime": "NA",
      "ConnectionEventCounts": 1,
      "RSSI": { "Local": -45, "Remote": "NA" },
      "RemainingBatteryCapacity_pc": 63,
      "SensorInputs": {
        "BatteyLevels": { "B1V5": 1.4, "B3V3": 1.4, "B4V5": 1.4 },
        "RS485": { "PSU_Voltage": "NA" },
        "SHTC1": { "RelativeHumidity_pc": 57, "Temperature_oC": 22.7 },
        "Thermistors": { "Ambient_oC": 23.1, "Wall_oC": 23.8 }
      }
    }
  ]
}
```

**Key fields**:

| Field                                       | Description                                       |
| ------------------------------------------- | ------------------------------------------------- |
| `IndoorUnit.NV_SupportedFanModes`           | Bitmask: 1=LOW, 2=MED, 4=HIGH, 8=AUTO             |
| `IndoorUnit.NV_AutoFanEnabled`              | Whether AUTO fan speed is available               |
| `OutdoorUnit.Family`                        | Series identifier (e.g., "Fixed Speed: Classic")  |
| `OutdoorUnit.CtrlBoardType`                 | Control board (e.g., "Type 100: UnoJr")           |
| `Peripherals[].DeviceType`                  | `"Zone Sensor"` for wireless zone controllers     |
| `Peripherals[].RemainingBatteryCapacity_pc` | Battery level for wireless sensors                |
| `Sensors[].Designator`                      | `C1-C3` (controllers), `RS1-RS3` (remote sensors) |

---

### UserAirconSettings

All user-configurable AC settings.

```json
{
  "AfterHours": {
    "Enabled": false,
    "Duration": 120
  },
  "ApplicationMode": "Residential",
  "AwayMode": false,
  "EnabledZones": [true, false, true, false, false, false, false, false],
  "FanMode": "HIGH",
  "Mode": "COOL",
  "NV_SavedZoneState": [true, false, true, false, false, false, false, false],
  "QuietMode": true,
  "QuietModeEnabled": true,
  "QuietModeActive": false,
  "ModeSupport": {
    "Cool": true,
    "Heat": true,
    "Fan": true,
    "Auto": true,
    "Dry": false
  },
  "ServiceReminder": {
    "Enabled": false,
    "Time": "NA"
  },
  "VFT": {
    "Airflow": 708.0,
    "StaticPressure": 275.0,
    "Supported": false,
    "Enabled": false,
    "SelfLearn": {
      "LastRunTime": "NA",
      "CurrentState": "Idle",
      "LastResult": "Idle",
      "MaxStaticPressure": 0
    }
  },
  "TurboMode": {
    "Supported": false,
    "Enabled": false
  },
  "TemperatureSetpoint_Cool_oC": 24.0,
  "TemperatureSetpoint_Heat_oC": 24.0,
  "ZoneTemperatureSetpointVariance_oC": 2.0,
  "isFastHeating": false,
  "isOn": true,
  "ChangeSrc": {
    "Mode": "GUI",
    "isOn": "GUI"
  }
}
```

**Key fields**:

| Field                                | Description                                      |
| ------------------------------------ | ------------------------------------------------ |
| `ModeSupport`                        | Which HVAC modes the unit supports               |
| `VFT`                                | Variable Fan Technology (Advance series only)    |
| `TurboMode.Supported`                | Whether turbo mode is available on this unit     |
| `QuietModeEnabled`                   | Whether quiet mode is available                  |
| `QuietModeActive`                    | Whether quiet mode is currently active           |
| `ChangeSrc`                          | Source of last change (GUI, API, Schedule, etc.) |
| `NV_SavedZoneState`                  | Zone state saved before away mode                |
| `ZoneTemperatureSetpointVariance_oC` | Max zone temp deviation from master setpoint     |

---

### MasterInfo

Master controller live readings.

```json
{
  "LiveHumidity_pc": 56.4,
  "LiveOutdoorTemp_oC": 3000.0,
  "LiveTempHysteresis_oC": 25.0,
  "LiveTemp_oC": 25.0,
  "RemoteHumidity_pc": {
    "<SERIAL>": 57.1
  }
}
```

**Key notes**:

- `LiveOutdoorTemp_oC`: Value of `3000.0` indicates sensor error or unavailable
  (common on Classic series units without an outdoor temperature sensor).
- `RemoteHumidity_pc`: Per-device humidity readings keyed by serial number.

---

### RemoteZoneInfo

Array of zone objects (indices 0-7 for up to 8 zones).

```json
[
  {
    "CanOperate": true,
    "CommonZone": false,
    "LiveHumidity_pc": 57.5,
    "LiveTempHysteresis_oC": 23.1,
    "LiveTemp_oC": 22.9,
    "NV_Exists": true,
    "NV_Title": "Master Bedroom",
    "NV_VAV": false,
    "NV_ITC": false,
    "NV_ITD": false,
    "NV_IHD": true,
    "NV_IAC": true,
    "AirflowControlEnabled": true,
    "AirflowControlLocked": false,
    "NV_amSetup": true,
    "LastZoneProtection": true,
    "Sensors": {
      "<SERIAL>": {
        "Connected": false,
        "NV_Kind": "ZS: 23E01206",
        "NV_isPaired": true,
        "NV_isViaRepeater": false,
        "Signal_of3": "-45",
        "TX_Power": 0,
        "lastRssi": "-45"
      }
    },
    "TemperatureSetpoint_Cool_oC": 24.0,
    "TemperatureSetpoint_Heat_oC": 21.5,
    "AirflowSetpoint": 100,
    "ZonePosition": 20,
    "ZoneMaxPosition": 100,
    "ZoneMinPosition": 0
  }
]
```

**Key fields**:

| Field                | Description                                         |
| -------------------- | --------------------------------------------------- |
| `NV_Exists`          | Whether this zone is configured                     |
| `NV_Title`           | User-assigned zone name                             |
| `NV_VAV`             | Variable Air Volume capable                         |
| `NV_ITC`             | Individual Temperature Control                      |
| `NV_ITD`             | Individual Temperature Display                      |
| `NV_IHD`             | Individual Humidity Display                         |
| `NV_IAC`             | Individual Airflow Control                          |
| `NV_amSetup`         | Zone has been configured                            |
| `LastZoneProtection` | Zone was protected from being turned off            |
| `ZonePosition`       | Current damper position (0-100%)                    |
| `ZoneMaxPosition`    | Maximum damper opening                              |
| `ZoneMinPosition`    | Minimum damper opening                              |
| `AirflowSetpoint`    | Target airflow percentage                           |
| `Sensors.<SERIAL>`   | Per-controller sensor connection info for this zone |

---

### LiveAircon

Real-time compressor and outdoor unit telemetry.

```json
{
  "AmRunningFan": true,
  "CoilInlet": 10.9,
  "CompressorCapacity": 80,
  "CompressorChasingTemperature": 24.0,
  "CompressorLiveTemperature": 25.0,
  "CompressorMode": "COOL",
  "DRM": false,
  "Defrost": false,
  "ErrCode": 0,
  "FanPWM": 79,
  "FanRPM": 1385,
  "IndoorUnitTemp": 0,
  "OutdoorUnit": {
    "AmbTemp": 0.0,
    "AmbientSensErr": true,
    "CoilSenseErr": false,
    "CoilTemp": 42.3,
    "CompPower": 0,
    "CompRunningPWM": 100,
    "CompSpeed": 100.0,
    "CompressorMode": 2,
    "CompressorOn": true,
    "CompressorSetSpeed": 80,
    "CompressorBoostEnable": 0,
    "CompressorBoostScale": 0,
    "FanSpeed": 0,
    "ODFan": "NA",
    "CondPc": 0.0,
    "DRM": 0,
    "DefrostMode": 0,
    "DischargeTemp": 0.0,
    "EEV": {
      "Opening_pc": 0,
      "SuperHeat": 3000.0,
      "SuperHeatRef": 3000,
      "Type": "UKV"
    },
    "EXV": false,
    "ErrCode_1": 0,
    "ErrCode_2": 0,
    "ErrCode_3": 0,
    "ErrCode_4": 0,
    "ErrCode_5": 0,
    "OilReturn": false,
    "OilReturnEnable": false,
    "RemoteOnOff": false,
    "RoomTemp": 24.6,
    "RoomTempODU": 25.0,
    "RoomTempSet": 25.0,
    "SuctP0": 0.0,
    "SuctTemp": 0.0,
    "EnvelopeProtection": false,
    "ReverseValvePosition": "Cool",
    "OverheatProtection": false,
    "SupplyVoltage_Vac": 0.0,
    "SupplyCurrentRMS_A": 0.0,
    "SupplyPowerRMS_W": 0.0,
    "OutputPowerRMS_W": 0.0,
    "DriveTemp": 0.0,
    "VSDODUCommsStatus": "OK",
    "LPErr": false,
    "HPErr": false,
    "OHP": {
      "TargetLine": 0,
      "TargetCondTemp_oC": 0.0,
      "StartTemp_oC": 0.0
    }
  },
  "SystemOn": true
}
```

**Key fields**:

| Field                              | Description                              |
| ---------------------------------- | ---------------------------------------- |
| `CompressorCapacity`               | Current compressor load (%)              |
| `CompressorMode`                   | Active mode: COOL, HEAT, FAN, etc.       |
| `FanPWM` / `FanRPM`                | Indoor fan speed (duty cycle / RPM)      |
| `CoilInlet`                        | Indoor coil inlet temperature (°C)       |
| `OutdoorUnit.AmbTemp`              | Ambient temperature at outdoor unit      |
| `OutdoorUnit.AmbientSensErr`       | Ambient sensor error flag                |
| `OutdoorUnit.CompPower`            | Compressor power consumption             |
| `OutdoorUnit.CompSpeed`            | Compressor speed (%)                     |
| `OutdoorUnit.RoomTemp`             | Indoor room temp as seen by outdoor unit |
| `OutdoorUnit.RoomTempODU`          | Room temp measured by ODU sensor         |
| `OutdoorUnit.SupplyVoltage_Vac`    | Mains supply voltage                     |
| `OutdoorUnit.SupplyCurrentRMS_A`   | Mains supply current                     |
| `OutdoorUnit.SupplyPowerRMS_W`     | Mains supply power                       |
| `OutdoorUnit.OutputPowerRMS_W`     | Compressor output power                  |
| `OutdoorUnit.DriveTemp`            | VSD drive temperature                    |
| `OutdoorUnit.VSDODUCommsStatus`    | Comms status between VSD and ODU         |
| `OutdoorUnit.EEV`                  | Electronic Expansion Valve data          |
| `OutdoorUnit.EnvelopeProtection`   | Compressor envelope protection active    |
| `OutdoorUnit.OverheatProtection`   | Overheat protection active               |
| `OutdoorUnit.LPErr` / `HPErr`      | Low/High pressure error flags            |
| `OutdoorUnit.OHP`                  | Overheat Protection parameters           |
| `OutdoorUnit.ReverseValvePosition` | Reversing valve state ("Cool" or "Heat") |

> **Note**: Many outdoor unit fields return `0.0` or `"NA"` on Classic (fixed-speed)
> units. Inverter units (Advance, Aires) will report more meaningful values for
> power, speed, and VSD-related fields.

---

### Alerts

```json
{
  "CleanFilter": false,
  "Defrosting": false
}
```

---

### NV_Limits

Temperature setpoint constraints.

```json
{
  "UserSetpoint_oC": {
    "MinGap": 0.0,
    "VarianceAboveMasterCool": 0.0,
    "VarianceAboveMasterHeat": 0.0,
    "VarianceBelowMasterCool": 0.0,
    "VarianceBelowMasterHeat": 0.0,
    "setCool_Max": 30.0,
    "setCool_Min": 16.0,
    "setHeat_Max": 30.0,
    "setHeat_Min": 16.0
  }
}
```

---

### NV_SystemSettings

System display, lock, and control configuration (partial — large section).

```json
{
  "AwayMode": {
    "TemperatureSetpoint_Cool_oC": 26.0,
    "TemperatureSetpoint_Heat_oC": 19.0,
    "TemperatureMinLimit_Cool_oC": 26.0,
    "TemperatureMaxLimit_Cool_oC": 36.0,
    "TemperatureMinLimit_Heat_oC": 10.0,
    "TemperatureMaxLimit_Heat_oC": 20.0
  },
  "Logs": {
    "snapshotTime_ms": 900000
  },
  "Display": {
    "HomeScreen": { "BackgroundColour": "Black", "Brightness": 50 },
    "ScreenSaver": { "Enabled": true, "Timeout_s": 60, "Brightness": 30 },
    "ScreenOff": { "Enabled": true, "Timeout_s": 60 }
  },
  "ProxmitySensor": {
    "Enabled": true,
    "Range_cm": 60
  },
  "LEDIndicators": {
    "WallGlow": { "Enabled": false },
    "OnOffButton": { "Enabled": true }
  },
  "Locks": {
    "PIN": "",
    "RentryTimeout_s": 0,
    "HomeScreen": {
      "ModeSelector": false,
      "TemperatureSetpoint": false,
      "FanSpeed": false,
      "OnOffButton": false
    },
    "MenuSystem": {
      "OptionsButton": false,
      "Timer": false,
      "Schedule": false,
      "WiFiAccount": false,
      "SystemSettings": false
    }
  },
  "SystemName": "NEO_22H09780",
  "Time": {
    "SetAutomatically": true,
    "TimeMode24h": true,
    "Timezone": "Australia/Queensland",
    "Timezone_Readable": "QLD, Australia"
  },
  "UpdateTime": "T02:00:00",
  "UserACSettings": {
    "ControlParameters": {
      "Compressor": {
        "CutIn": { "Cool_degC": 1.0, "Heat_degC": -1.0 },
        "CutOut": { "Cool_degC": 0.5, "Heat_degC": -0.5 },
        "LowDemand": {
          "Heat": {
            "Supported": true,
            "Enabled": true,
            "Trigger_pc": 20,
            "RunTime_m": 35
          },
          "Cool": {
            "Supported": true,
            "Enabled": true,
            "Trigger_pc": 20,
            "RunTime_m": 16
          }
        }
      }
    }
  }
}
```

---

### NV_Schedule

```json
{
  "Enabled": false,
  "Events": []
}
```

---

### NV_QuickTimer

```json
{
  "Master": [
    {
      "OriginalTime": "01:00",
      "Status": "Stopped",
      "Mode": "Timer",
      "Time": "00:00:00",
      "Zones": [true, true, true, true, true, true, true, true]
    }
  ]
}
```

---

### AwayModeSavedState

```json
{
  "Master": {
    "TemperatureSetpoint_Cool_oC": 26.0,
    "TemperatureSetpoint_Heat_oC": 19.0
  }
}
```

---

### Servicing

Error and event history.

```json
{
  "NV_ErrorHistory": [],
  "NV_AC_EventHistory": [
    {
      "Id": 0,
      "Task": "GUI",
      "TimeStamp": "2026-02-26T08:46:24",
      "Event": "AC On/Off",
      "Parameters": ["AC On"]
    }
  ],
  "NV_WC_EventHistory": [
    {
      "Id": 0,
      "Task": "Touch Button Controller",
      "TimeStamp": "2026-02-26T08:46:24",
      "Event": "Cap Touch Button Event",
      "Parameters": [{ "State": "1" }]
    },
    {
      "Id": 4,
      "Task": "WiFi",
      "TimeStamp": "2026-02-25T10:37:57",
      "Event": "AP Connect (DHCP IP)",
      "Parameters": [0]
    }
  ]
}
```

---

### Installer

```json
{
  "Id": "",
  "Name": "",
  "Email": "",
  "Phone": ""
}
```

---

## Events Response (DEPRECATED)

> **WARNING**: The Events API was **disabled by Actron in July 2025**. The endpoint
> returns errors. This section is retained for historical reference only.

**Endpoint**: `GET /api/v0/client/ac-systems/events/latest?serial=<serial>`

Previously returned status-change-broadcast events with delta updates:

```json
{
  "items": [
    {
      "id": "string",
      "type": "status-change-broadcast",
      "pairedUserId": "string",
      "timestamp": "string",
      "data": {
        "LiveAircon.Defrost": false,
        "RemoteZoneInfo[0].LiveTemp_oC": 24.0,
        "@metadata": { "connectionId": "string", "server": "string" }
      }
    }
  ],
  "_links": {
    "self": { "href": "string" },
    "ac-newer-events": { "href": "string" },
    "ac-older-events": { "href": "string" }
  }
}
```

## Command Structure

**Endpoint**: `POST /api/v0/client/ac-systems/cmds/send?serial=<serial>`

See [ActronAirNeoAPI.md](ActronAirNeoAPI.md) for the full command reference.

**Wrapper format**:

```json
{
  "command": {
    "UserAirconSettings.isOn": true,
    "UserAirconSettings.Mode": "COOL",
    "type": "set-settings"
  }
}
```

## Error Responses

### Authentication Error

```json
{
  "error": "invalid_grant",
  "error_description": "The refresh token is invalid."
}
```

### Device Unavailable (HTTP 503)

```json
{
  "correlationId": "<uuid>",
  "type": "unavailable",
  "value": null,
  "mwcResponseTime": "00:00:00.0000381"
}
```

### Rate Limit Error

```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit has been exceeded"
  }
}
```

## Model-Specific Differences

Based on the live API data and GitHub issue reports:

| Feature                    | Classic                | Advance         | Aires          |
| -------------------------- | ---------------------- | --------------- | -------------- |
| `OutdoorUnit.Family`       | "Fixed Speed: Classic" | "Tru-Inverter"  | "Inverter"     |
| `NV_AutoFanEnabled`        | `false`                | `true`          | varies         |
| `TurboMode.Supported`      | `false`                | `true`          | varies         |
| `VFT.Supported`            | `false`                | `true`          | `false`        |
| `ModeSupport.Dry`          | `false`                | varies          | varies         |
| `LiveOutdoorTemp_oC`       | `3000.0` (error)       | actual reading  | actual reading |
| Compressor power telemetry | Limited (fixed speed)  | Full (VSD data) | Partial        |

### Advance/Inverter (NTW-series) Telemetry Scaling

NTW-series units (e.g. NTW-1000, firmware 2.6.2.5) report certain live
telemetry fields at reduced scale in the raw API payload. The integration
applies correction factors at parse time (see `const.py`):

| Raw field            | Scale factor | Corrected unit | Evidence / reasoning                        |
| -------------------- | ------------ | -------------- | ------------------------------------------- |
| `SupplyVoltage_Vac`  | × 10         | VAC            | Raw 23.0 → 230 VAC; confirmed NTW-1000 #133 |
| `CompPower`          | × 100        | W              | Raw 45 → 4500 W; P ≈ V×I = 230×19 ≈ 4370 W  |
| `SupplyCurrentRMS_A` | × 1 (none)   | A              | Reads correctly at face value               |
| `Capacity_kW`        | × 1 (none)   | kW             | Reads correctly at face value               |

**Three-phase exception (#189).** Three-phase Advance units report the same
controller model (NTW-1000) and firmware, so the model can't separate the two
cases. Their `Family` can (`"Inverter: Advance Series I Three Phase"`), and
these units are **not** scaled:

| Raw field            | Scale factor | Example raw values (24 kW system) | Notes                                         |
| -------------------- | ------------ | --------------------------------- | --------------------------------------------- |
| `CompPower`          | × 1 (none)   | 122 – 5142                        | Already in W                                  |
| `SupplyVoltage_Vac`  | × 1 (none)   | 665 – 715                         | Not confirmed as line voltage; passed through |
| `SupplyCurrentRMS_A` | × 1 (none)   | 0.0                               | Reads 0.0 even under load                     |

**Native-watt single-phase exception (#200).** Some single-phase Inverter
units on the same controller model and firmware (NTW-1000, 2.6.2.5) report
`CompPower` in W already (raw 2975 → 2975 W). The payload has no unit flag,
so the integration uses magnitude:

- `CompPower`: a raw value above 100 would be more than 10 kW after ×100, which
  a single-phase compressor can't draw. The first such reading marks the system
  as native-watt. The integration stores this per device
  (`.storage/actronair_neo.power_format_<serial>`), so later low readings are
  not scaled, also after a restart. Before that first reading, values of 100 or
  lower are still scaled ×100.
- `SupplyVoltage_Vac`: checked separately. Only raw values above 0 and at most
  100 are scaled ×10; a raw 230 passes through unchanged.

The diagnostics download shows the raw values, the normalised values and the
detected format under `data.electrical`.

> **⚠️ Unconfirmed:** `SupplyPowerRMS_W` and `OutputPowerRMS_W` scaling has
> not yet been verified from a live payload with non-zero values. These
> fields are left unscaled pending confirmation from additional NTW-series
> devices. If you have a live payload showing non-zero values for these
> fields, please share it in GitHub issue #133.

## Changelog

- **October 2026**: Native-watt single-phase units detected by `CompPower`
  magnitude and remembered per device; voltage scaled only when the raw value
  is 100 or lower. See issue #200.
- **October 2026**: Three-phase Advance units excluded from the NTW-series
  scaling; their `CompPower` is already in W. See issue #189.
- **July 2026**: Documented NTW-series telemetry scaling for
  `SupplyVoltage_Vac` (×10) and `CompPower` (×100). Flagged
  `SupplyPowerRMS_W` / `OutputPowerRMS_W` as unconfirmed. See issue #133.
- **February 2026**: Complete rewrite from live API data. Documented all
  `lastKnownState` sections including serial-keyed section, SystemState,
  SystemStatus_Local, Peripherals, NV_SystemSettings. Updated auth to Device
  Code Flow. Marked Events API as deprecated. Added model-specific differences
  table.
