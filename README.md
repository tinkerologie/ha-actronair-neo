# ActronAir Neo for Home Assistant

<!-- BADGES:START -->

[![Marketplace and HACS](https://img.shields.io/badge/Marketplace%20%7C%20HACS-Default-orange.svg)](https://www.hacs.xyz/docs/marketplace/)
[![GitHub Last Commit](https://img.shields.io/github/last-commit/tinkerologie/ha-actronair-neo)](https://github.com/tinkerologie/ha-actronair-neo/commits/main)
[![GitHub Release](https://img.shields.io/github/v/release/tinkerologie/ha-actronair-neo)](https://github.com/tinkerologie/ha-actronair-neo/releases)
[![Code coverage](https://codecov.io/gh/tinkerologie/ha-actronair-neo/graph/badge.svg)](https://codecov.io/gh/tinkerologie/ha-actronair-neo)
[![License](https://img.shields.io/github/license/tinkerologie/ha-actronair-neo)](./LICENSE)

<!-- BADGES:END -->

Control and monitor your ActronAir Neo air conditioner from Home Assistant.
Set the temperature, select a mode, and control the zones that your system supports.
Use the entities in dashboards and automations.

The integration gets updates from the ActronAir cloud through MQTT.
If MQTT is unavailable, the integration polls the cloud every 30 seconds by default.
The integration also supports Que outdoor units with Neo controllers.

## Install

You need Home Assistant 2026.11.0 or later and an ActronAir account with access to your system.

### Install with HACS

[![Open ActronAir Neo in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=tinkerologie&repository=ha-actronair-neo&category=integration)

1. Open the ActronAir Neo repository in HACS.
2. Download the integration.
3. Restart Home Assistant.

Use a release that includes the `actronair_neo.zip` asset. Some older releases do not have this asset.

### Install manually

1. Download `actronair_neo.zip` and `SHA256SUMS` from the [latest release](https://github.com/tinkerologie/ha-actronair-neo/releases/latest).
2. [Verify the download](#verify-the-download).
3. In your Home Assistant configuration directory, create `custom_components/actronair_neo/`.
4. Extract the ZIP file into the `actronair_neo` directory.
5. Make sure that `manifest.json` is directly in the `actronair_neo` directory.
6. Restart Home Assistant.

#### Verify the download

Open a terminal in the directory that contains the two files.
Replace `TAG` with the release tag in the last command.
Use GitHub CLI 2.81.0 or later to verify the release asset.

```sh
sha256sum -c SHA256SUMS
gh attestation verify actronair_neo.zip --repo tinkerologie/ha-actronair-neo
gh release verify-asset TAG actronair_neo.zip --repo tinkerologie/ha-actronair-neo
```

## Set up the integration

1. In Home Assistant, go to **Settings** → **Devices & services** → **Integrations**.
2. Select **Add integration**.
3. Search for **ActronAir Neo**.
4. Select **ActronAir Neo**.
5. Open the verification URL in your browser.
6. Sign in to ActronAir.
7. Enter the device code if the browser does not fill it in.
8. Authorize Home Assistant.
9. If your account has more than one system, select the system to add.

The integration uses OAuth 2.0 Device Authorization Grant (RFC 8628).
Enter your ActronAir credentials on the ActronAir website only.

### Options

| Option                                         | Effect                                                      |
| ---------------------------------------------- | ----------------------------------------------------------- |
| **Enable zone control**                        | Adds climate entities for individual zones. Off by default. |
| **Enable realtime push updates (recommended)** | Gets cloud updates through MQTT. On by default.             |

## Entities

Your system model and settings determine which entities are available.

| Platform          | Controls and readings                                                                   |
| ----------------- | --------------------------------------------------------------------------------------- |
| **Climate**       | System mode, fan speed, and temperature setpoint                                        |
| **Sensor**        | Temperature, humidity, compressor state, power, estimated energy, and service reminders |
| **Binary sensor** | Filter status, system health, defrost, fast heating, and active warnings                |
| **Switch**        | Zones, away mode, quiet mode, continuous fan, turbo mode, and after hours               |
| **Cover**         | Zone damper position and airflow controls on supported systems                          |
| **Number**        | After-hours duration and zone temperature limits                                        |

### Controller schedules

On systems that report controller schedules, **Scheduler** shows if the scheduler is on.
Each schedule has a switch with the name from the controller.
If you change the name on the controller, the switch keeps the same entity ID.
Schedule switches show available settings such as times, days, modes, and setpoints.

Use a schedule switch to enable or disable one schedule.
On the tested Neo controller, **Scheduler** changed when a schedule was enabled or disabled.
Commands to **Scheduler** did not change its state on that controller.
If a switch does not change, check the ActronAir app or the wall controller.

## Dashboard cards

| Card                      | Controls and readings                                                     |
| ------------------------- | ------------------------------------------------------------------------- |
| **ActronAir Neo climate** | Temperature, system mode, fan speed, power, and supported system controls |
| **ActronAir Neo zones**   | Zone switches, temperature, humidity, setpoints, and YourZone controls    |
| **ActronAir Neo system**  | Indoor and outdoor readings, compressor power, and estimated energy       |

1. Open the dashboard editor.
2. Add an ActronAir Neo card from the card picker.
3. Select the **ActronAir Neo device** for the card.

A card uses the available entities for the selected device.
To show a disabled sensor, enable it on the device page.
Use the temperature buttons or the keyboard to change a setpoint.
The zone card shows the airflow setpoint separately from the damper position.

### YAML dashboards

Home Assistant registers the card resource automatically in storage mode.
If you manage resources in YAML, add this resource.

```yaml
lovelace:
  resource_mode: yaml
  resources:
    - url: /actronair_neo_frontend/actronair-neo-cards.js
      type: module
```

For manually managed resources, update the `?v=<installed-version>` URL query after an upgrade.
Reload the browser.

This example adds a climate card.

```yaml
type: custom:actronair-neo-climate-card
device_id: your_home_assistant_device_id
show_options: true
show_humidity: true
```

| Other card types                   | Options                         |
| ---------------------------------- | ------------------------------- |
| `custom:actronair-neo-zones-card`  | `show_dampers`, `show_humidity` |
| `custom:actronair-neo-status-card` | `show_diagnostics`              |

You can set a `title` on each card.

## Troubleshoot

1. Check that the ActronAir app can connect to your system.
2. Check **Settings** → **System** → **Logs** for ActronAir Neo errors.
3. If the problem continues, [open a GitHub issue](https://github.com/tinkerologie/ha-actronair-neo/issues/new/choose).
4. Before you attach diagnostics, remove any private information.

## Contribute

Read the [contribution guide](./CONTRIBUTING.md) for setup and test procedures.
See the [changelog](./CHANGELOG.md) for changes in each release.

## License

The integration uses the [Apache License 2.0](./LICENSE).
Independent contributors maintain this integration. ActronAir owns its trademarks.
