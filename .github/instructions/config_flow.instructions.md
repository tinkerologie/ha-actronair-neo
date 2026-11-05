---
applyTo: "custom_components/**/config_flow.py"
---

# Config Flow Instructions

**Applies to:** `config_flow.py`

**Official Documentation:**

- [Config Flow Handler](https://developers.home-assistant.io/docs/config_entries_config_flow_handler)
- [Data Entry Flow](https://developers.home-assistant.io/docs/data_entry_flow_index)

## File Organization

This integration uses a single `config_flow.py` file (not a package). Keep all
config flow logic here unless it grows beyond ~400 lines.

## Step Names

**Reserved system steps:**

- `user` — User-initiated setup
- `reauth` — Re-authentication flow
- `reconfigure` — Configuration changes

**Discovery steps** (if added, require manifest entry):

- `dhcp`, `zeroconf`, `bluetooth`, etc.

## Unique IDs

**MUST:**

- Set unique ID using the AC serial number or account identifier
- Call `self._abort_if_unique_id_configured()` to prevent duplicates
- Use `await self.async_set_unique_id(serial_number)`

**NEVER:**

- Use IP addresses (can change)
- Use device names (user-changeable)
- Use hostnames or URLs

## Validation

**Pattern:**

```python
async def async_step_user(self, user_input=None):
    errors = {}
    if user_input is not None:
        try:
            serial = await validate_credentials(user_input)
            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=serial, data=user_input)
        except AuthenticationError:
            errors["base"] = "invalid_auth"
        except ApiError:
            errors["base"] = "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
    return self.async_show_form(step_id="user", data_schema=SCHEMA, errors=errors)
```

**Common error keys:** `cannot_connect`, `invalid_auth`, `unknown`

## Setup Entry Error Handling

**In `async_setup_entry()` in `__init__.py`:**

- Raise `ConfigEntryNotReady` for temporary failures (timeout, device offline)
- Raise `ConfigEntryAuthFailed` for authentication failures

**NEVER log `ConfigEntryNotReady` manually** — HA logs at debug automatically.

## Reauth Flow

**MUST:**

- Implement `async_step_reauth()` forwarding to `async_step_reauth_confirm()`
- Use `self._get_reauth_entry()` to access current entry
- Update entry: `self.async_update_reload_and_abort(entry, data_updates=user_input)`

**NEVER create new entry** — always update existing.

## Reconfigure Flow

**MUST:**

- Use `self._get_reconfigure_entry()` to access current entry
- Pre-fill form with `self.add_suggested_values_to_schema(schema, entry.data)`

## Config Entry Lifecycle

**Setup (`__init__.py`):**

```python
async def async_setup_entry(hass, entry) -> None:
    coordinator = ActronDataCoordinator(hass, ...)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)


async def async_unload_entry(hass, entry) -> None:
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)
```

Setup, unload and migrate return `None` (HA 2026.11). Signal failure by raising
`ConfigEntryNotReady`, `ConfigEntryAuthFailed` or a translated `ConfigEntryError`,
never by returning `False`. Test patches of `async_setup_entry` use
`return_value=None`.

## Rules Summary

**ALWAYS:**

- Set unique ID from stable identifier (serial number)
- Abort if unique ID already configured
- Validate input before creating entry
- Update existing entries in reauth/reconfigure (never create new)
- Use translation keys for errors

**NEVER:**

- Use changeable values as unique IDs
- Create new entries in reauth/reconfigure
- Log `ConfigEntryNotReady` manually
- Mutate ConfigEntry objects directly (use `async_update_entry()`)
