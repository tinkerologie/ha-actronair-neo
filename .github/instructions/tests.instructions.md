---
applyTo: "tests/**/*.py"
---

# Tests Instructions

**Applies to:** All test files under `tests/`

## General Rules

- **Do NOT write tests unless explicitly requested.** The user will ask when tests are needed.
- Mirror the integration structure: one test file per module (e.g. `test_coordinator.py` → `coordinator.py`)
- Use real HA test fixtures — do NOT mock `hass` itself

## Framework

```toml
# pyproject.toml [test] extras already includes:
# pytest-homeassistant  (Home Assistant's official plugin; loads automatically)
# pytest-asyncio, pytest-freezer, pytest-cov, pytest-timeout, pytest-xdist
```

`pytest-homeassistant` must match the Home Assistant release it was built from.
The `dev` extra pins `homeassistant` exactly, and `[tool.uv.sources]` pins the
plugin to the Core commit for that release. Update both together. Never install
the retired `pytest-homeassistant-custom-component` alongside it.

```bash
# Run all tests
script/test

# Run a specific file
script/test tests/test_coordinator.py -v

# Run with coverage
script/test --cov

# Run with HTML coverage report
script/test --cov-html
```

## Test Structure

```python
"""Tests for coordinator.py."""

from unittest.mock import AsyncMock, patch
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant.common import MockConfigEntry

from custom_components.actronair_neo.const import DOMAIN


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={"username": "test@example.com", "password": "password"},
        unique_id="ABC123",
    )


async def test_coordinator_update(hass: HomeAssistant, mock_entry) -> None:
    """Test coordinator updates correctly."""
    ...
```

## Key Principles

**Test through public interfaces only:**

- `hass.states.get("climate.actron_neo_living_room")`
- `hass.services.async_call(DOMAIN, "set_zone_temperature", {...})`
- Entity state attributes

**Do NOT test internals directly:**

- Don't call private methods (`_update_data()`, `_handle_error()`)
- Don't assert on internal data structures directly (use state machine)

**Mock all external I/O:**

```python
with patch(
    "custom_components.actronair_neo.api_wrapper.ActronNeoApiWrapper.get_ac_status",
    return_value={"some": "data"},
):
    ...
```

**Exception handling tests:**

```python
from custom_components.actronair_neo.exceptions import AuthenticationError

with patch("...get_ac_status", side_effect=AuthenticationError("bad creds")):
    result = await coordinator.async_refresh()
    assert coordinator.last_exception is not None
```

## Conftest Fixtures

Common fixtures belong in `tests/conftest.py`:

- `hass` — provided by `pytest-homeassistant`; custom integrations are enabled by
  default, so do not request `enable_custom_integrations`
- `mock_config_entry` — standard `MockConfigEntry` for `actronair_neo`
- `mock_api_wrapper` — `AsyncMock` of `ActronNeoApiWrapper`

## Naming Conventions

- Files: `test_<module_name>.py`
- Functions: `test_<what>_<condition>_<expected>` e.g. `test_coordinator_auth_error_triggers_reauth`
- Fixtures: descriptive nouns e.g. `mock_ac_status`, `mock_config_entry`

## Coverage

Coverage is tracked via `coverage.json`. Don't obsess over 100% coverage — focus on
testing real user-impacting behaviour and error paths.
