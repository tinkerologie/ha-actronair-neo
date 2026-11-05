---
applyTo: "custom_components/**/services.yaml"
---

# Service Actions Instructions

**Applies to:** `services.yaml`

**Official Documentation:** [Service Actions](https://developers.home-assistant.io/docs/dev_101_services/)

## Registering Services

**Register in `async_setup_entry()`:**

```python
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up actronair_neo from a config entry."""
    ...
    hass.services.async_register(
        DOMAIN,
        "set_away_mode",
        handle_set_away_mode,
        schema=vol.Schema({
            vol.Required(CONF_DEVICE_ID): str,
            vol.Required("away": bool,
        }),
    )
```

**Always remove on unload:**

```python
async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload a config entry."""
    ...
    hass.services.async_remove(DOMAIN, "set_away_mode")
```

## services.yaml Structure

```yaml
set_away_mode:
  name: Set Away Mode
  description: Enable or disable away mode on the ActronAir Neo system.
  fields:
    device_id:
      name: Device ID
      description: The serial number of the AC unit.
      required: true
      selector:
        text:
    away:
      name: Away Mode
      description: Enable (true) or disable (false) away mode.
      required: true
      selector:
        boolean:
```

## Error Handling

| Error type               | Use when                                   |
| ------------------------ | ------------------------------------------ |
| `ServiceValidationError` | Bad user input (wrong device ID, etc.)     |
| `HomeAssistantError`     | Device error (API failure, device offline) |

```python
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


async def handle_set_away_mode(call: ServiceCall) -> None:
    """Handle set_away_mode service call."""
    device_id = call.data[CONF_DEVICE_ID]
    coordinator = _get_coordinator_for_device(hass, device_id)
    if coordinator is None:
        raise ServiceValidationError(f"Device '{device_id}' not found")
    try:
        await coordinator.api.set_away_mode(call.data["away"])
    except ApiError as err:
        raise HomeAssistantError(f"Failed to set away mode: {err}") from err
```

## This Project's Services

Check `services.yaml` for the currently registered services and their schemas
before adding new ones. Avoid duplicating existing functionality.

## Key Rules

- Register in `async_setup_entry()`, unregister in `async_unload_entry()`
- Use voluptuous schema for input validation
- Use `ServiceValidationError` for user input errors
- Use `HomeAssistantError` for device/API errors
- Provide translations for all service names and descriptions in `strings.json`
