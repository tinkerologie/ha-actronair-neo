# AI Agent Instructions

## Mandatory Development Workflow for AI Agents

All AI coding assistants (Claude Code, Gemini, GitHub Copilot, Cursor, Roo, Devin, etc.) MUST strictly adhere to the following workflow when working on this repository:

1. Issue-First Requirement: Never start writing code or creating pull requests without an existing GitHub Issue.
2. Issue Template: Issues must be created using the official Issue Forms (`01-bug-report.yml` for bugs or `02-enhancement-request.yml` for enhancements).
3. CodeRabbit AI Plan: Every issue must have a generated Coding Plan from CodeRabbit AI (`@coderabbitai plan`). AI agents must read and implement strictly according to the approved plan.
4. Branch Discipline: Always create and work on a dedicated branch (`feat/<issue-id>-<description>` or `fix/<issue-id>-<description>`). NEVER commit directly to `main`.
5. Documentation & Changelog: Update `CHANGELOG.md` under `## [Unreleased]` for any user-facing or architectural changes.
6. Local Verification: Run all test, lint, format, and typecheck commands locally before committing. All tests must pass with zero errors and zero warnings.
7. PR Template Completion: Always use `.github/PULL_REQUEST_TEMPLATE.md`. Complete all fields, link the issue using `Fixes #<id>` or `Closes #<id>`, and check all Pre-Submission Governance boxes with real terminal output.
8. Draft PR First: ALWAYS open pull requests as DRAFT (`gh pr create --draft`).
9. CI Verification: Wait for CI workflows to run on the draft PR and verify that all status checks pass.
10. Ready for Review: Only mark the PR as ready for review (`gh pr ready`) once all checks pass and all due diligence is verified.
11. Review Clearance: Review and resolve all CodeRabbit AI and GitHub Copilot comments. Ensure Codecov reports show zero errors, zero warnings, and no coverage drop.

This document provides guidance for AI coding agents working on the ActronAir Neo Home
Assistant custom integration project.

## Project Overview

This is a Home Assistant custom integration for controlling **ActronAir Neo** air
conditioning systems via the ActronAir cloud API.

**Integration details:**

- **Domain:** `actronair_neo`
- **Title:** ActronAir Neo
- **Class prefix:** `ActronAirNeo`
- **Repository:** ruaan-deysel/ha-actronair-neo
- **iot_class:** `cloud_polling`

**Key directories:**

- `custom_components/actronair_neo/` — Main integration code
- `config/` — Home Assistant configuration for local testing
- `tests/` — Unit and integration tests
- `script/` — Development and validation scripts

**Local Home Assistant instance:**

**Always use the project's scripts** — do NOT craft your own `hass`, `pip`,
`pytest`, or similar commands. The scripts handle virtual environments, Python
paths, and environment setup that raw commands miss.

**Start Home Assistant:**

```bash
script/develop
```

**Validate code before committing:**

```bash
script/lint
```

**Run tests:**

```bash
script/test
script/test --cov           # with coverage
script/test --cov-html      # HTML report in htmlcov/
```

**Other useful scripts:**

```bash
script/check          # type-check + lint-check + spell-check (before commits)
script/clean          # clean build artifacts
script/type-check     # Pyright type checking
script/spell          # spell check with auto-fix
script/help           # list all available scripts
script/setup/reset    # reset HA config to fresh state
```

**Reading logs:**

- Live: Terminal where `script/develop` runs
- File: `config/home-assistant.log` (most recent), `config/home-assistant.log.1` (previous)

**Adjust log levels** for debugging in `config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.actronair_neo: debug
```

**Context-specific instructions:**

If you're using GitHub Copilot, path-specific instructions in
`.github/instructions/*.instructions.md` provide additional guidance for specific file
types. This document serves as the primary reference for all agents.

**Other agent entry points:**

- **Claude Code:** See [`CLAUDE.md`](CLAUDE.md) (pointer to this file)
- **Gemini:** See [`GEMINI.md`](GEMINI.md) (pointer to this file)
- **GitHub Copilot:** See [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
  (compact version of this file)

---

## Working With Developers

### When Instructions Conflict With Requests

If a developer requests something that contradicts these instructions:

1. **Clarify the intent** — Ask if they want you to deviate from documented guidelines
2. **Confirm understanding** — Restate what you understood to avoid misinterpretation
3. **Suggest instruction updates** — If this represents a permanent change in approach,
   offer to update these instructions
4. **Proceed once confirmed** — Follow the developer's explicit direction after clarification

### Maintaining These Instructions

Instructions should evolve as the project matures:

- Refine guidelines based on actual project needs
- Remove outdated rules that no longer apply
- Consolidate redundant sections to prevent bloat

**Propose updates when:**

- You notice repeated deviations from documented patterns
- Instructions become outdated or contradict actual code
- New patterns emerge that should be standardized

### Documentation vs. Instructions

**Three types of content with clear separation:**

1. **Agent Instructions** — How AI should write code (`.github/instructions/`, `AGENTS.md`)
2. **Developer Documentation** — Architecture and design decisions (`docs/`)
3. **User Documentation** — End-user guides (README, CHANGELOG)

**AI Planning:** Use `.ai-scratch/` for temporary notes (never committed)

**Rules:**

- **NEVER** create random markdown files in code directories
- **NEVER** create documentation in `.github/` unless it's a GitHub-specified file
- **ALWAYS ask first** before creating permanent documentation
- **Prefer module docstrings** over separate markdown files

### Session and Context Management

**Commit suggestions:**

When a task completes and the developer moves to a new topic, suggest committing
changes. Offer a commit message based on the work done.

**Commit message format:** Follow [Conventional Commits](https://www.conventionalcommits.org/)
specification

**Common types:** `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`

---

## Integration Architecture

This integration controls ActronAir Neo HVAC systems via cloud push (MQTT) with REST polling fallback (`iot_class: cloud_push`).

### File Structure

```text
custom_components/actronair_neo/
├── __init__.py          # Integration setup (async_setup_entry, async_unload_entry)
├── api/                 # API client package (client.py, auth.py, models.py, const.py, push/)
├── entity.py            # ActronAirNeoEntity and ActronZoneEntity base classes
├── binary_sensor.py     # Binary sensor platform
├── climate.py           # Main climate platform (HVAC control)
├── config_flow.py       # Configuration flow (OAuth2 device code flow)
├── const.py             # All constants (DOMAIN, modes, features)
├── coordinator.py       # DataUpdateCoordinator (ActronDataCoordinator)
├── cover.py             # Cover platform (YourZone damper position control)
├── diagnostics.py       # Diagnostics (redact sensitive data!)
├── exceptions.py        # Custom exception hierarchy
├── icons.json           # Entity MDI icon mappings
├── manifest.json        # Integration metadata
├── number.py            # Number platform (temperature setpoints, after-hours duration)
├── repairs.py           # Repair flows for issue recovery
├── sensor.py            # Sensor platform (temperature, humidity, energy, status)
├── strings.json         # Translation source
├── switch.py            # Switch platform (zone toggles, continuous fan, quiet, turbo)
├── types.py             # Pydantic v2 models and TypedDict definitions for coordinator data
├── zone_presets.py      # Zone preset and schedule management
└── translations/
    └── en.json          # English translations
```

### Data Flow (CRITICAL)

Entities → Coordinator (`entry.runtime_data`) → API Client (`api/client.py`) — Never skip layers

- **Entities:** Read `coordinator.data` only, never call API directly
- **Coordinator:** Calls `api/client.py` and subscribes to `api/push/`, transforms data using Pydantic v2 models, handles errors
- **API Client:** HTTP/MQTT communication with ActronAir cloud, OAuth2 auth, command dispatch

### Entity Platforms

| Platform           | Purpose                                                    |
| ------------------ | ---------------------------------------------------------- |
| `climate.py`       | Main HVAC entity — mode, fan speed, setpoint, zones        |
| `cover.py`         | Zone damper position control (`CoverDeviceClass.DAMPER`)   |
| `sensor.py`        | Temperature, humidity, compressor, indoor/outdoor readings |
| `binary_sensor.py` | On/off states (defrost, compressor on, warnings, etc.)     |
| `switch.py`        | Zone toggles, continuous fan, quiet mode, turbo, after-hrs |
| `number.py`        | Zone temperature limits, after-hours duration              |

### Zone Architecture

ActronAir Neo uses a zone-based architecture:

- **Master AC unit** controls overall settings (mode, setpoint)
- **Zones** (numbered 0-N) can be individually enabled/disabled
- **Zone presets** in `zone_presets.py` allow saving/restoring zone configurations
- Zone data is fetched per-AC-serial via the coordinator

### Exception Hierarchy

Defined in `exceptions.py`:

- `ApiError` — Base exception for all API errors
- `AuthenticationError` — Invalid or expired credentials
- `ConfigurationError` — Configuration issues
- `ZoneError` — Zone-related errors
- `DeviceOfflineError` — Device unreachable
- `RateLimitError` — API rate limiting

**Coordinator mapping:**

| Exception             | Coordinator Raises      | HA Behaviour       |
| --------------------- | ----------------------- | ------------------ |
| `AuthenticationError` | `ConfigEntryAuthFailed` | Triggers reauth    |
| `DeviceOfflineError`  | `UpdateFailed`          | Retry with backoff |
| `RateLimitError`      | `UpdateFailed`          | Retry with backoff |
| `ApiError`            | `UpdateFailed`          | Retry with backoff |

---

## Code Style and Quality

**Python:** 4 spaces, 88 char lines, double quotes, full type hints, async for all I/O

**YAML:** 2 spaces, modern HA syntax

**JSON:** 2 spaces, no trailing commas, no comments

**Validation:** Run `script/lint` before committing (runs `ruff format` +
`ruff check --fix`)

**Linting command:**

```bash
script/lint
```

**For comprehensive standards, see:**

- `.github/instructions/python.instructions.md` — Python patterns, imports, type hints
- `.github/instructions/yaml.instructions.md` — YAML structure
- `.github/instructions/json.instructions.md` — JSON formatting

---

## Project-Specific Rules

### Integration Identifiers

This integration uses the following identifiers consistently:

- **Domain:** `actronair_neo`
- **Title:** ActronAir Neo
- **Class prefix:** `ActronAirNeo`

**When creating new files:**

- Use the domain `actronair_neo` for all DOMAIN references
- Prefix integration-specific classes with `ActronAirNeo`
- Never hardcode different values

### Key Constants (const.py)

Always import from `const.py` rather than hardcoding:

- `DOMAIN` — `"actronair_neo"`
- `MANUFACTURER` — `"ActronAir"`
- AC mode constants, feature flags, service names

### Types (types.py)

- All API response structures use `TypedDict` from `types.py`
- Coordinator data structures should be typed
- Do NOT add new untyped dicts for API data — extend `types.py`

### Diagnostics (diagnostics.py)

**CRITICAL:** Always use `async_redact_data()` to redact:

- API tokens / credentials
- User account identifiers
- Serial numbers (if considered sensitive)

See `.github/instructions/diagnostics.instructions.md` for patterns.

### Config Flow

Located in `config_flow.py` (single file, not a package — current project structure).

- Supports user setup and options flow
- Unique ID must be the AC serial number or account identifier
- Never use IP addresses or hostnames as unique IDs

### Coordinator

Located in `coordinator.py` as `ActronDataCoordinator`.

- Inherits from `DataUpdateCoordinator`
- Fetches and caches all AC data per update cycle
- Maps API exceptions to `ConfigEntryAuthFailed` / `UpdateFailed`
- Use `async_config_entry_first_refresh()` on setup

### API Wrapper (api_wrapper.py)

Primary API client. Key responsibilities:

- Authentication with ActronAir cloud
- Fetching AC system status and zone data
- Sending commands (mode changes, setpoint, zone toggles)
- Session management (accept session from `async_get_clientsession(hass)`)

---

## Home Assistant Patterns

**Config flow:**

- See `.github/instructions/config_flow.instructions.md` for comprehensive patterns
- Always set unique_id, abort if already configured

**Entities:**

- Inherit from platform base + `ActronAirNeoBaseEntity` (from `base_entity.py`)
- Read from `coordinator.data`, never call API directly
- Use `EntityDescription` dataclasses for static entity metadata

**Coordinator:**

- Entities → Coordinator → API Wrapper (never skip layers)
- Raise `ConfigEntryAuthFailed` (triggers reauth) or `UpdateFailed` (retry)
- Use `async_config_entry_first_refresh()` for first update

**Diagnostics:**

- **CRITICAL:** Use `async_redact_data()` to remove sensitive data
- Redact: API keys, tokens, account IDs, serial numbers

---

## Validation Scripts

**Before committing, run:**

```bash
script/lint      # Format + lint with ruff (auto-fix)
script/test      # Run unit tests
script/check     # Type-check + lint-check + spell-check (comprehensive)
```

**Generate code that passes these checks on first run.** Type hints, async patterns,
and naming conventions should be correct before handing back to the developer.

### Error Recovery Strategy

**When validation fails:**

1. **First attempt** — Fix the specific error reported by the tool
2. **Second attempt** — If it fails again, reconsider your approach
3. **Third attempt** — If still failing, ask for clarification
4. **After 3 failed attempts** — Stop and explain what you tried

---

## Testing

**Test structure:**

- `tests/` mirrors `custom_components/actronair_neo/` modules
- Use fixtures for common setup (HA mock, coordinator, etc.)
- Mock external API calls — never make real network requests

**Running tests:**

```bash
script/test
script/test --cov
script/test --cov-html
script/test tests/test_coordinator.py -v
```

See `.github/instructions/tests.instructions.md` for comprehensive patterns.

---

## Breaking Changes

**Always warn the developer before making changes that:**

- Change entity IDs or unique IDs (users' automations will break)
- Modify config entry data structure (existing installations will fail)
- Change state values or attribute format (dashboards and automations affected)
- Alter service call signatures (user scripts will break)
- Remove or rename config options (users must reconfigure)

**Never do without explicit approval:**

- Removing config options
- Changing service parameters or return values
- Renaming entities or changing device classes
- Changing unique_id generation logic

---

## File Changes

**Scope Management:**

**Single logical feature or fix:**

- Implement completely even if it spans multiple files
- Example: New sensor needs entity class + platform init → implement all together

**Multiple independent features:**

- Implement one at a time
- Suggest committing before proceeding to the next

**Large refactoring (>10 files or architectural changes):**

- Propose a plan first before starting implementation
- Get explicit confirmation from developer

**Important: Do NOT create or modify tests unless explicitly requested.**

**Translation strategy:**

- Update `strings.json` and `translations/en.json` together
- NEVER update other language files automatically (use key references instead)
- Ask before creating new translation files

---

## Research and Validation

**When uncertain, consult official documentation:**

- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Developer Blog](https://developers.home-assistant.io/blog/) for recent changes
- [Ruff Rules](https://docs.astral.sh/ruff/rules/)

**Don't rely on assumptions — Home Assistant APIs evolve frequently.**

---

## Tool Parallelization

**Safe to call in parallel:**

- Multiple `read_file` operations
- `file_search` + `read_file` + `grep_search` (independent read-only operations)

**Never call in parallel:**

- Multiple `run_in_terminal` commands
- Multiple `replace_string_in_file` on the same file (use `multi_replace_string_in_file`)
- Multiple `semantic_search` calls

---

## Additional Resources

- [Home Assistant Developer Docs](https://developers.home-assistant.io/)
- [Integration Quality Scale](https://developers.home-assistant.io/docs/integration_quality_scale_index)
- [Ruff Rules](https://docs.astral.sh/ruff/rules/)
- [pytest Documentation](https://docs.pytest.org/)
- See `CONTRIBUTING.md` for contribution guidelines

## Issue and Pull Request Governance

These rules apply to every contributor, including AI coding agents. The full org-wide rules are in
[GOVERNANCE.md](https://github.com/tinkerologie/.github/blob/main/GOVERNANCE.md).

1. **Issue first.** Open an issue with the bug or enhancement template before opening a pull
   request. Keep the title prefix `[Bug]:` or `[Enhancement]:`, followed by a space and the title.
   Automation applies the `bug` or `enhancement` label when it can tell the type, and CodeRabbit
   then posts a Coding Plan on the issue. Implement from that plan.
2. **Link the issue.** In the PR's **Related Issues** section write `Closes #<number>` (`Fixes`,
   `Resolves`, `Part of`, and `Related to` also work). `None` is only for maintainer housekeeping
   such as CI, documentation, or dependency updates; contributor changes need an issue.
3. **One change at a time.** Contributors without write access can have at most 2 open, non-draft
   pull requests here. GitHub enforces this limit, and draft pull requests do not count toward it.
   Do not open PRs that edit the same files as another open PR, such as `CHANGELOG.md`,
   translations, `README.md`, or generated bundles. Wait for the first to merge, rebase, then
   continue.
4. **Rebase before review.** Rebase on `main` before marking a PR ready for review.
5. **Resolve conflicts first.** When a PR gets the `conflicts` label, rebase on `main`,
   resolve the conflicts (keep every `CHANGELOG.md` entry under `[Unreleased]`), re-run the tests,
   and force-push before doing any other work.
6. **Stale items.** Issues and PRs with no activity for 14 days are labeled `stale` and closed 30
   days later unless there is new activity. These labels are exempt:
   - Issues: `pinned`, `security`, `confirmed`, `work-in-progress`, `priority: critical`, `priority: high`.
   - Pull requests: `pinned`, `security`, `work-in-progress`.
