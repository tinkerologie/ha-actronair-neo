# ActronAir Neo Integration for Home Assistant

<!-- BADGES:START -->

[![Marketplace and HACS](https://img.shields.io/badge/Marketplace%20%7C%20HACS-Default-orange.svg)](https://www.hacs.xyz/docs/marketplace/)
[![GitHub Last Commit](https://img.shields.io/github/last-commit/tinkerologie/ha-actronair-neo)](https://github.com/tinkerologie/ha-actronair-neo/commits/main)
[![GitHub Release](https://img.shields.io/github/v/release/tinkerologie/ha-actronair-neo)](https://github.com/tinkerologie/ha-actronair-neo/releases)
[![codecov](https://codecov.io/gh/tinkerologie/ha-actronair-neo/graph/badge.svg)](https://codecov.io/gh/tinkerologie/ha-actronair-neo)
[![License](https://img.shields.io/github/license/tinkerologie/ha-actronair-neo)](./LICENSE)

<!-- BADGES:END -->

The ActronAir Neo Integration enables seamless control and monitoring of your ActronAir Neo air conditioning system directly from Home Assistant. With this integration, you can automate climate control, monitor indoor and outdoor temperatures, and adjust settings based on real-time data, all from one central location.

## Features

- **Comprehensive Control**: Switch between modes (heat, cool, fan, auto), set temperatures, and adjust fan speeds.
- **Real-time Monitoring**: Indoor/outdoor temperature, humidity, compressor state, and system diagnostics.
- **Zone Control**: Manage individual zones — enable/disable, set temperatures, and adjust damper positions via cover entities.
- **Extended Controls**: Turbo mode, quiet mode, away mode, after-hours scheduling, and continuous fan.
- **Que-to-Neo Support**: Systems with Que outdoor units upgraded to Neo controllers are automatically detected and routed correctly.
- **Automation Friendly**: Integrate ActronAir Neo into your Home Assistant automations for optimal comfort.
- **Periodic Updates**: System state refreshes every 30 seconds via cloud polling.

## Installation

### HACS (Recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tinkerologie&repository=ha-actronair-neo&category=integration)

### Manual

1. Download `actronair_neo.zip` and `SHA256SUMS` from the [latest release](https://github.com/tinkerologie/ha-actronair-neo/releases/latest).
2. Create `config/custom_components/actronair_neo/` and extract the ZIP into that directory. Its files, including `manifest.json`, belong directly there.
3. Restart Home Assistant.

For a source checkout, copy `custom_components/actronair_neo/` into your Home Assistant `config/custom_components/` directory instead, then restart.

#### Verify the download

Run these commands in the directory containing the downloaded ZIP and checksum file. Replace `<tag>` with the release version:

```sh
sha256sum -c SHA256SUMS
gh attestation verify actronair_neo.zip --repo tinkerologie/ha-actronair-neo
gh release verify-asset <tag> actronair_neo.zip --repo tinkerologie/ha-actronair-neo
```

The release-asset verification command requires GitHub CLI 2.81.0 or later.

In HACS or the Marketplace, selecting an older release without an `actronair_neo.zip` asset can fail to download.

## Dashboard cards

Three cards are bundled with the integration and appear in Home Assistant's card picker:

| Card                      | Controls and readings                                                                                          |
| ------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **ActronAir Neo climate** | Neo-style temperature ring, accessible temperature buttons, mode, fan speed, power and supported quick options |
| **ActronAir Neo zones**   | Zone on/off, temperature and humidity, optional zone setpoints and YourZone airflow controls                   |
| **ActronAir Neo system**  | Indoor/outdoor readings, compressor power, estimated compressor energy and optional diagnostics                |

Add a card in the dashboard editor and select your **ActronAir Neo device**. Each card discovers only that device's loaded, readable entities. Entity renaming is supported; multiple systems remain separate. Disabled sensors are omitted. Enable optional sensors on the integration's device page to show their readings.

The cards follow the selected Home Assistant theme and work in Sections and masonry views. The ring is a visual indicator; use the temperature buttons or your keyboard to change a setpoint. Unsupported controls are hidden, unavailable controls are disabled, and commands show pending/error feedback. Zone controls do not change the system's HVAC mode. Damper position and the commanded airflow setpoint are shown separately; position-only sensors remain read-only. Compressor energy is an estimate derived from compressor power.

In storage mode, the integration registers one versioned module resource automatically. Reload the browser after an upgrade. YAML dashboards can explicitly register this module resource:

```yaml
lovelace:
  resource_mode: yaml
  resources:
    - url: /actronair_neo_frontend/actronair-neo-cards.js
      type: module
```

For manually managed resources, add or update a `?v=<installed-version>` query after an upgrade to refresh browser caches. Card YAML is also supported:

```yaml
type: custom:actronair-neo-climate-card
device_id: your_home_assistant_device_id
show_options: true
show_humidity: true
```

Use `custom:actronair-neo-zones-card` with `show_dampers` and `show_humidity`, or `custom:actronair-neo-status-card` with `show_diagnostics`. Each card accepts an optional `title`.

## Configuration

1. In Home Assistant, go to **Settings → Devices & Services → Integrations**.
2. Click **+ ADD INTEGRATION** and search for "ActronAir Neo".
3. A device code and verification URL will be displayed.
4. Open the URL in your browser, enter the code, and authorize.
5. Select your AC system if you have multiple devices.

> **Note:** This integration uses OAuth2 Device Code Flow (RFC 8628). No username or password is entered in Home Assistant.

## Usage

After setup, your ActronAir Neo system will appear as a climate entity in Home Assistant. You can control it from the Home Assistant frontend or include it in your automations.

## Entities

| Platform          | Examples                                                                                      |
| ----------------- | --------------------------------------------------------------------------------------------- |
| **Climate**       | Main HVAC control (mode, fan speed, temperature setpoint)                                     |
| **Sensor**        | Indoor/outdoor temperature, humidity, compressor state, performance metrics, service reminder |
| **Binary Sensor** | Filter status, system health, defrost, fast heating, active warnings                          |
| **Switch**        | Zone toggles, away mode, quiet mode, continuous fan, turbo mode, after hours                  |
| **Cover**         | Zone damper position (open/close/set position)                                                |
| **Number**        | After-hours duration, zone temperature limits                                                 |

Entities update automatically with the coordinator refresh interval (30 seconds).

## Options

You can adjust the following option in the integration settings:

- **Enable Zone Control**: Toggle individual zone management (off by default).

## Troubleshooting

If you encounter any issues:

1. Check the [Docs](docs/index.md)
2. Check that your credentials are correct
3. Ensure your ActronAir Neo system is online and accessible
4. Check the Home Assistant logs for any error messages
5. If you encounter a bug, please report it on our [GitHub issues page](https://github.com/tinkerologie/ha-actronair-neo/issues)

## Contributing

Contributions to this integration are welcome. Please fork the repository and submit a pull request with your changes.

### Development Setup

1. Clone the repository:

   ```bash
   git clone https://github.com/tinkerologie/ha-actronair-neo.git
   cd ha-actronair-neo
   ```

2. Bootstrap the development environment (requires [uv](https://docs.astral.sh/uv/)):

   ```bash
   script/setup/setup
   ```

   Or manually:

   ```bash
   uv sync --all-groups
   ```

### Testing

We encourage adding tests for new features. The test suite can be found in the `tests/` directory.

## License

This integration is released under the Apache License 2.0.

## Disclaimer

This integration is not officially associated with or endorsed by ActronAir. ActronAir trademarks belong to ActronAir, and this integration is independently developed.
