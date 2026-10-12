# ActronAir Neo Integration for Home Assistant

[![HACS Integration](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub Last Commit](https://img.shields.io/github/last-commit/ruaan-deysel/ha-actronair-neo)](https://github.com/tinkerologie/ha-actronair-neo/commits/main)
[![License](https://img.shields.io/github/license/ruaan-deysel/ha-actronair-neo)](./LICENSE)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/tinkerologie/ha-actronair-neo)

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

1. Copy the `actronair_neo` folder into your `custom_components` directory.
2. Restart Home Assistant.

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
