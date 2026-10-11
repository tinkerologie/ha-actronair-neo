---
applyTo: "**/manifest.json"
---

# Manifest Instructions

**Applies to:** `custom_components/actronair_neo/manifest.json`

## Required Fields

```json
{
  "domain": "actronair_neo",
  "name": "ActronAir Neo",
  "codeowners": ["@ruaan-deysel"],
  "config_flow": true,
  "documentation": "https://github.com/tinkerologie/ha-actronair-neo",
  "integration_type": "hub",
  "iot_class": "cloud_polling",
  "issue_tracker": "https://github.com/tinkerologie/ha-actronair-neo/issues",
  "requirements": ["actron-neo-api==0.4.1"],
  "version": "x.x.x"
}
```

## Integration Type

`integration_type: "hub"` — ActronAir Neo is a hub because it controls multiple
zone devices through a central AC unit connected to the ActronAir cloud.

## IoT Class

`iot_class: "cloud_polling"` — Data is fetched by polling the ActronAir cloud API
at regular intervals.

## Requirements

Use exact versions for `actron-neo-api` to ensure reproducibility:

```json
"requirements": ["actron-neo-api==0.4.1"]
```

Update version only after testing with the new library release.

## Version

Use semantic versioning: `YEAR.MINOR.PATCH` (Home Assistant convention: `2025.1.0`)

- Increment last segment for bug fixes
- Increment middle for new features
- First segment is the year

## Common Mistakes

- ❌ Missing `version` (required for HACS)
- ❌ Missing `issue_tracker` (required for HACS)
- ❌ Wrong `domain` (must match directory name `actronair_neo`)
- ❌ Trailing commas in JSON
- ❌ Changing `integration_type` or `iot_class` without explicit reason

## References

- [Manifest Documentation](https://developers.home-assistant.io/docs/creating_integration_manifest/)
- [HACS Requirements](https://hacs.xyz/docs/publish/include)
