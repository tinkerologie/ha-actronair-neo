---
applyTo: "custom_components/**/repairs.py"
---

# Repairs Instructions

**Applies to:** `repairs.py`

**Official Documentation:** [Repairs Framework](https://developers.home-assistant.io/docs/core/platform/repairs)

## Overview

Repair Flows guide users through fixing issues (expired credentials, deprecated
settings, missing configuration, etc.).

**Key differences from Config Flow:**

- **Location:** `repairs.py` in integration root
- **Base class:** `homeassistant.components.repairs.RepairsFlow`
- **Trigger:** System creates issue → user clicks "Fix" → Repair Flow runs
- **Purpose:** Fix existing problems, not create new config entries

## Creating Issues

Issues that concern one config entry belong to it: make the issue ID unique
per entry and pass `config_entry_id`. Home Assistant deletes entry-owned issues
when the entry is removed and hides them while it is disabled.

```python
from homeassistant.helpers import issue_registry as ir

ir.async_create_issue(
    hass,
    DOMAIN,
    f"device_offline_{entry.entry_id}",  # unique within the domain
    config_entry_id=entry.entry_id,
    is_fixable=True,  # Shows "Fix" button
    severity=ir.IssueSeverity.WARNING,
    translation_key="device_offline",  # bare key; shared translations
    translation_placeholders={"key": "value"},
)
```

**Maintaining issues:** wrap the checks in an entry-scoped refresh and only
create issues whose condition holds. When the block exits, the entry's issues
that were not created (or kept) are deleted. Recreating an existing issue keeps
the user's "ignore". Wrap only the checks, never `async_forward_entry_setups`.

```python
with ir.async_refresh_issues(hass, DOMAIN, config_entry_id=entry.entry_id):
    if not coordinator.last_update_success:
        ir.async_create_issue(...)  # as above
```

Use `ir.async_keep_issue()` for an issue whose state cannot be determined
during the refresh. `async_create_fix_flow` receives the qualified ID, so
dispatch by key prefix.

**When to create issues:**

- During `async_setup_entry()` — Config validity, API compatibility
- In coordinator updates — Deprecated endpoints, expired features

## Repair Flow Implementation

```python
async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create flow for issue_id."""
    return MyRepairFlow()


class MyRepairFlow(RepairsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            entry = self.hass.config_entries.async_get_entry(self.handler)
            ir.async_delete_issue(self.hass, entry.domain, "issue_id")
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="init")
```

## Translations

```json
{
  "issues": {
    "issue_id": {
      "title": "Issue title",
      "description": "Description with {placeholder}",
      "fix_flow": {
        "step": {
          "init": {
            "title": "Repair step title",
            "description": "Instructions"
          }
        }
      }
    }
  }
}
```

## Rules

**MUST:**

- Implement `async_create_fix_flow()` returning `RepairsFlow` subclass
- Delete issue after successful repair: `ir.async_delete_issue()`
- Set `is_fixable=True` only if repair flow exists
- Provide translations for all text

**NEVER:**

- Put repair flows in `config_flow.py` (separate system)
- Leave issues after repair completes (always delete)
- Delete entry-owned issues in `async_unload_entry` (reloads unload too) or
  `async_remove_entry` (Home Assistant removes them with the entry)
- Use domain-global issue IDs for per-entry problems (entries overwrite each
  other's issues)
- Use repair flows for normal config changes (use reconfigure instead)
