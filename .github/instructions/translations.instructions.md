---
applyTo: "**/translations/*.json, **/strings.json"
---

# Translation Files Instructions

**Applies to:** `strings.json` and `translations/en.json`

## File Relationship

- `strings.json` — Source of truth (used by hassfest validation and some tools)
- `translations/en.json` — English translations served to HA UI

Both must stay in sync. Update them together whenever changing user-facing strings.

## Critical Rules

### Translation Placeholders

**Runtime values:** Use `{variable}` syntax — replaced with actual values at runtime

```json
"description": "Enter credentials for {device_name}"
```

**CRITICAL: Do NOT use single quotes around placeholders:**

- ✅ `"Service {service} is unavailable"`
- ✅ `"Service \"{service}\" is unavailable"`
- ❌ `"Service '{service}' is unavailable"` (causes hassfest errors)

### Key References

Use `[%key:...]` to reuse translations and avoid duplication:

```json
{
  "config": {
    "abort": {
      "cannot_connect": "[%key:common::config_flow::error::cannot_connect%]"
    }
  }
}
```

Do not add `reauth_successful` or `reconfigure_successful`:
`async_update_reload_and_abort` uses Home Assistant's central translations for
them (HA 2026.10+), so local keys are dead.

### Entity Translations

**Requirements in code:**

- Set `has_entity_name=True` on entity
- Set `translation_key` property to match JSON key

```json
"entity": {
  "sensor": {
    "indoor_temperature": {
      "name": "Indoor Temperature"
    }
  }
}
```

## Structure

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up ActronAir Neo",
        "data": {
          "account_id": "Account ID",
          "auth_code": "Authorization code"
        }
      }
    },
    "error": {
      "cannot_connect": "Failed to connect",
      "invalid_auth": "Invalid credentials",
      "unknown": "Unexpected error"
    },
    "abort": {
      "already_configured": "Already configured"
    }
  }
}
```

## Translation Strategy

- Business logic first, translations later
- Update `en.json` only when asked or at major feature completion
- NEVER update other language files automatically — extremely time-consuming
- Ask before creating new language files

## Common Mistakes

- ❌ Updating `strings.json` but forgetting `translations/en.json` (or vice versa)
- ❌ Missing `translation_key` in entity code when adding entity translations
- ❌ Using entity translations without `has_entity_name=True`
- ❌ Using single quotes around placeholders
- ❌ Invalid JSON syntax (trailing commas, comments)

## References

- [Custom Integration Localization](https://developers.home-assistant.io/docs/internationalization/custom_integration)
