# ActronAir Neo MQTT Topics Reference

**Last Updated**: June 2026
**Platform**: Neo (Nimbus)
**Standard**: MQTT 3.1.1
**Broker**: Dynamically discovered via `/api/v0/messaging/connection/details`

---

## Overview

The ActronAir Neo cloud platform uses MQTT for real-time system state updates and command responses. This enables the Home Assistant integration to receive state changes within seconds rather than waiting for the 30-second polling interval.

### MQTT Connection Details

- **Client ID**: Random UUID (changed per connection)
- **Username**: Empty string (`""`)
- **Password**: OAuth2 access token (short-lived, typically 72 hours)
- **QoS**: 0 (at-most-once delivery)
- **Keepalive**: 60 seconds
- **Clean Session**: Yes (fresh subscriptions per connect)
- **TLS**: Yes (verified with certifi certificates)
- **Reconnect Strategy**: Exponential backoff (0.5s → 60s max)

---

## Topic Hierarchy

```
actron-cloud
└── neo                          # Platform identifier
    └── {user_id}                # User account ID (from MQTT connection details)
        └── neo                  # Nested platform marker
            └── {serial}         # AC system serial number
                ├── mwc
                │   ├── full-status
                │   ├── status-change
                │   ├── heart-beat
                │   └── cmd-response
                │       ├── {machine}    # Machine identifier
                │       └── {commandId}  # Unique command ID
```

### Example Full Topic Path

```
actron-cloud/neo/user_abc123/neo/ABC123XYZ/mwc/full-status
```

---

## Topic Details

### 1. **Full Status** (`mwc/full-status`)

**Publishes**: Complete system state snapshot
**Frequency**: On connection, after major changes
**QoS**: 0
**Retained**: Yes

#### Purpose

Provides a complete snapshot of the system state, including all zones, settings, live data, and diagnostics. Used to synchronize state after connection or when incremental updates may have been missed.

#### Payload Structure

```json
{
  "AirconSystem": {
    "SerialNumber": "ABC123XYZ",
    "Model": "NTW-1000",
    "FirmwareVersion": "2.5.0.7"
  },
  "MasterInfo": {
    "LiveTemp_oC": 21.5,
    "LiveHumidity_pc": 45.0
  },
  "UserAirconSettings": {
    "isOn": true,
    "Mode": "COOL",
    "FanMode": "AUTO",
    "TemperatureSetpoint_Cool_oC": 22.0,
    "TemperatureSetpoint_Heat_oC": 18.0,
    "EnabledZones": [true, true, false, false, false, false, false, false]
  },
  "LiveAircon": {
    "CompressorMode": "COOL",
    "CompressorCapacity": 75,
    "FanRPM": 450,
    "Filter": {
      "CleanRequired": false,
      "MonitoringDays": 65
    }
  },
  "RemoteZoneInfo": [
    {
      "ZoneNumber": 0,
      "ZoneName": "Master Bedroom",
      "LiveTemp_oC": 21.2,
      "LiveHumidity_pc": 42.0,
      "TargetSetpoint_oC": 22.0,
      "DamperPosition": 100,
      "BatteryLevel": 85,
      "Signal_of3": 3
    }
    // ... zones 1-7
  ],
  "SystemSettings": {
    "TurboMode": {
      "Supported": true,
      "Enabled": false
    },
    "QuietMode": {
      "Supported": true,
      "Enabled": false
    },
    "AwayMode": {
      "Enabled": false
    }
  },
  "OutdoorUnit": {
    "CompressorPower_kW": 2.5,
    "CompressorSpeed": 45,
    "OutdoorTemp_oC": 18.5,
    "DefrostMode": 0
  },
  "WiFiConnection": {
    "SSID": "MyNetwork",
    "Channel": 6,
    "SignalStrength_dBm": -65,
    "Firmware": "NW2.1.4"
  }
}
```

**Size**: ~2-4 KB
**Parsing**: Complete state merge, replaces coordinator data

---

### 2. **Status Change** (`mwc/status-change`)

**Publishes**: Incremental state changes
**Frequency**: 1-5 seconds after changes
**QoS**: 0
**Retained**: No

#### Purpose

Sends only the fields that have changed since the last update. Dramatically reduces message size and network traffic compared to full-status.

#### Payload Structure (Examples)

**Example 1**: User changed mode

```json
{
  "UserAirconSettings": {
    "Mode": "HEAT",
    "isOn": true
  }
}
```

**Example 2**: Zone damper position changed

```json
{
  "RemoteZoneInfo": [
    {
      "ZoneNumber": 2,
      "DamperPosition": 75
    }
  ]
}
```

**Example 3**: Compressor capacity changed

```json
{
  "LiveAircon": {
    "CompressorCapacity": 50
  }
}
```

**Example 4**: Multiple changes (temperature + compressor)

```json
{
  "UserAirconSettings": {
    "TemperatureSetpoint_Cool_oC": 23.0
  },
  "LiveAircon": {
    "CompressorCapacity": 85
  },
  "MasterInfo": {
    "LiveTemp_oC": 21.8
  }
}
```

**Size**: ~100-500 bytes
**Parsing**: Deep merge with existing state (uses `deep_merge()` function)
**Efficiency**: ~90% smaller than full-status for typical updates

---

### 3. **Heartbeat** (`mwc/heart-beat`)

**Publishes**: Connection keepalive signal
**Frequency**: Every 60 seconds (guaranteed)
**QoS**: 0
**Retained**: No

#### Purpose

Confirms the connection is alive and broker is routing messages. Detected missing heartbeats indicate potential connection issues.

#### Payload Structure

```json
{
  "Timestamp": "2026-06-07T10:30:45Z",
  "Status": "OK"
}
```

**Size**: ~50 bytes
**Monitoring**: Integration tracks last heartbeat; considers connection stale after 3 minutes (180 seconds) without heartbeat

#### Stale Detection Logic

```python
time_since_heartbeat = now() - last_heartbeat_timestamp
if time_since_heartbeat > 180:  # 3 minutes
    push_state = "DEGRADED"
    # Fall back to HTTP polling
```

---

### 4. **Command Response** (`mwc/cmd-response/{machine}/{commandId}`)

**Publishes**: Response to control commands sent via API
**Frequency**: Within 1-5 seconds of command
**QoS**: 0
**Retained**: No

#### Purpose

Acknowledges command execution and returns the resulting state change. Allows zero-latency feedback to Home Assistant for user-initiated controls.

#### Topic Pattern

```
actron-cloud/neo/{user_id}/neo/{serial}/mwc/cmd-response/{machine_id}/{command_uuid}
```

#### Payload Structure

**Successful Command**:

```json
{
  "CommandId": "550e8400-e29b-41d4-a716-446655440000",
  "Status": "OK",
  "ResultingStateChange": {
    "UserAirconSettings": {
      "Mode": "HEAT"
    }
  }
}
```

**Failed Command**:

```json
{
  "CommandId": "550e8400-e29b-41d4-a716-446655440000",
  "Status": "ERROR",
  "ErrorCode": "INVALID_ZONE",
  "ErrorMessage": "Zone 5 not available on this system"
}
```

**Size**: ~200-1000 bytes
**Timeout**: If no response received within 30 seconds, command considered failed
**State Sync**: On success, also contains a status-change event (no separate message)

---

## Message Timing & Latency

| Scenario                  | Topic         | Latency | Size  |
| ------------------------- | ------------- | ------- | ----- |
| System power on           | status-change | <2s     | ~200B |
| Mode change (user)        | status-change | <2s     | ~150B |
| Temperature sensor update | status-change | 5-10s   | ~100B |
| Compressor state change   | status-change | <1s     | ~80B  |
| Command acknowledgment    | cmd-response  | <5s     | ~300B |
| Scheduled heartbeat       | heart-beat    | ~60s    | ~50B  |
| Connection lost/regain    | full-status   | <10s    | ~3KB  |

---

## Connection Lifecycle

### 1. Initial Connection

```
Client connects with OAuth token
  ↓
Broker authenticates token
  ↓
Client subscribes to:
  - mwc/full-status
  - mwc/status-change
  - mwc/heart-beat
  - mwc/cmd-response/+/+
  ↓
Broker publishes full-status (current state)
  ↓
Integration merges state into coordinator
  ↓
Entities update (climate, sensors, switches, etc.)
```

### 2. Normal Operation

```
User makes change in HA
  ↓
Integration sends command via HTTP POST
  ↓
Cloud API accepts command
  ↓
Cloud system processes command
  ↓
Status-change published to MQTT
  ↓
Integration merges update
  ↓
Entities reflect change
  ↓
(Meanwhile) cmd-response arrives for acknowledgment
```

### 3. Connection Loss Recovery

```
Network interruption
  ↓
MQTT client detects no messages for 2× keepalive (120s)
  ↓
Connection lost
  ↓
Client attempts reconnect with exponential backoff
  ↓
Reconnect successful
  ↓
Broker publishes full-status (latest state)
  ↓
Integration merges (corrects any missed updates)
```

### 4. Token Expiration

```
Token expires (typically 72 hours)
  ↓
Broker disconnects client (AUTH error)
  ↓
Integration falls back to HTTP polling
  ↓
Config flow triggers reauth
  ↓
User approves new token via OAuth flow
  ↓
MQTT reconnects with new token
```

---

## Integration Implementation Details

### State Merging Strategy

The integration uses **deep merge** with path-based updates:

```python
# Incoming status-change message
incoming = {"UserAirconSettings": {"Mode": "HEAT"}, "MasterInfo": {"LiveTemp_oC": 21.8}}

# Existing state
existing = {
    "UserAirconSettings": {"Mode": "COOL", "isOn": True, "FanMode": "AUTO"},
    "MasterInfo": {"LiveTemp_oC": 21.5, "LiveHumidity_pc": 45.0},
    "RemoteZoneInfo": [...],
}

# After merge
result = {
    "UserAirconSettings": {
        "Mode": "HEAT",  # Updated
        "isOn": True,  # Preserved
        "FanMode": "AUTO",  # Preserved
    },
    "MasterInfo": {
        "LiveTemp_oC": 21.8,  # Updated
        "LiveHumidity_pc": 45.0,  # Preserved
    },
    "RemoteZoneInfo": [...],  # Preserved
}
```

### Fallback to Polling

The integration gracefully falls back to HTTP polling if:

1. **Initial MQTT connection fails**: Uses polling as primary transport
2. **Heartbeat missing for 3 minutes**: Marks push as degraded, continues polling
3. **MQTT messages arrive but are stale**: Compares with polling data for validation
4. **Token expiration**: Falls back during reauth flow

### Error Handling

| Situation                   | Handling                                                    |
| --------------------------- | ----------------------------------------------------------- |
| Malformed JSON payload      | Log warning, ignore message, continue                       |
| Unknown field in state      | Preserve in raw data, don't crash                           |
| Heartbeat missed (1 time)   | Log info, continue monitoring                               |
| Heartbeat missed (3+ times) | Mark push degraded, recommend polling check                 |
| Command fails               | Entity retains last known state, shows error in diagnostics |
| Broker certificate invalid  | Use certifi bundle, log SSL error                           |
| Broker unreachable          | Exponential backoff (0.5s → 60s), fall back to polling      |

---

## Debugging & Troubleshooting

### Enable MQTT Debugging

```yaml
# config/configuration.yaml
logger:
  logs:
    custom_components.actronair_neo.api.push.mqtt_transport: debug
```

### Monitor MQTT in Real-time

```bash
# Terminal 1: Listen to all topics for your serial
mosquitto_sub -h <broker_host> -p <port> \
  -u "" -P "<token>" \
  -t "actron-cloud/neo/+/neo/<SERIAL>/#" \
  -v
```

### Check Last Heartbeat

Look in Home Assistant diagnostics under "Push Transport" section:

- `last_heartbeat`: ISO timestamp of last heartbeat received
- `reconnect_count`: Total reconnection attempts
- `state`: Current push state (RUNNING, DEGRADED, FAILED)

### Verify Message Parsing

Add temporary debug logging to coordinator:

```python
_LOGGER.debug("MQTT message received: %s", payload)
_LOGGER.debug("Merged state: %s", coordinator.data)
```

---

## Platform-Specific Notes

### Neo (Current)

- ✅ MQTT via aiomqtt library
- ✅ QoS 0 (sufficient for real-time state sync)
- ✅ Broker discovered dynamically
- ✅ Topic structure: `actron-cloud/neo/{user}/{serial}/mwc/*`

### Que (NX-Gen) - NOT IMPLEMENTED

- ❌ Uses SignalR or EventSource instead of MQTT
- ❌ Different topic structure (if MQTT used at all)
- ❌ Requires separate transport implementation

### ACM-2 (Actron Connect) - UNKNOWN

- ❌ API structure unknown
- ❌ Real-time transport method unknown
- ❌ Requires research

---

## Performance Characteristics

### Bandwidth Usage

- **Full status**: ~3KB every 300s (if only polling) = **80 bytes/s**
- **MQTT with heartbeat**: ~200B every 60s (heartbeat) + ~300B per user action = **~100-200 bytes/s** (idle)
- **Reduction**: ~60-70% bandwidth savings vs polling alone

### Latency Improvements

- **Polling**: 0-30 second latency (until next poll interval)
- **MQTT**: <2 second latency for most state changes
- **Improvement**: 93-98% latency reduction

### Broker Load

- **Connections**: 1 per system per user (multiplexed)
- **Messages/minute**: ~1 heartbeat + ~0-5 status changes = **~1-6 messages/min** (typical)
- **Scalability**: Broker can handle thousands of concurrent connections

---

## Related Files

- **Coordinator**: `coordinator.py` (state merging logic)
- **MQTT Transport**: `api/push/mqtt_transport.py` (connection management)
- **Merge Logic**: `api/push/merge.py` (deep_merge, apply_event_paths)
- **Constants**: `api/const.py` (MQTT\_\* constants)
- **Types**: `types.py` (CoordinatorData structure)

---

**End of MQTT Topics Reference**

For questions or to report issues, see the [ActronAir Neo Integration](https://github.com/tinkerologie/ha-actronair-neo/issues).
