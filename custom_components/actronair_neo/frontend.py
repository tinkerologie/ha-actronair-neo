"""Serve bundled dashboard cards and reconcile only their owned resource URL."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http.server import StaticPathConfig
from homeassistant.helpers.collection import ItemNotFound
from homeassistant.helpers.start import async_at_started
from homeassistant.util.hass_dict import HassKey

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
BUNDLE_PATH = Path(__file__).parent / "frontend" / "actronair-neo-cards.js"
BUNDLE_URL = "/actronair_neo_frontend/actronair-neo-cards.js"
FRONTEND_DATA: HassKey[dict[str, Any]] = HassKey("actronair_neo_frontend")


def _versioned_url() -> str:
    """Read the asset and manifest in the executor for cache invalidation."""
    version = json.loads(
        BUNDLE_PATH.parent.parent.joinpath("manifest.json").read_text()
    )["version"]
    digest = hashlib.sha256(BUNDLE_PATH.read_bytes()).hexdigest()[:12]
    return f"{BUNDLE_URL}?v={version}-{digest}"


def _resource_collection(hass: HomeAssistant) -> tuple[Any, bool]:
    """Resolve the current Lovelace collection, including YAML reloads."""
    # Import optional Lovelace internals only when the UI is configured.
    from homeassistant.components.lovelace.const import (  # noqa: PLC0415
        LOVELACE_DATA,
    )
    from homeassistant.components.lovelace.resources import (  # noqa: PLC0415
        ResourceStorageCollection,
    )

    lovelace = hass.data.get(LOVELACE_DATA)
    resources = lovelace.resources if lovelace is not None else None
    return resources, isinstance(resources, ResourceStorageCollection)


async def _async_reconcile(resources: Any, url: str) -> None:
    """Update our module and remove only duplicate instances of its exact path."""
    await resources.async_get_info()
    matches = [
        item
        for item in resources.async_items()
        if item["url"].partition("?")[0] == BUNDLE_URL
    ]
    if not matches:
        await resources.async_create_item({"url": url, "res_type": "module"})
    elif matches[0]["url"] != url or matches[0]["type"] != "module":
        await resources.async_update_item(
            matches[0]["id"], {"url": url, "res_type": "module"}
        )
    for item in matches[1:]:
        with suppress(ItemNotFound):
            await resources.async_delete_item(item["id"])


def _remove_fallback(hass: HomeAssistant) -> None:
    """Remove the extra-module path when a native resource owns loading."""
    if url := hass.data[FRONTEND_DATA].pop("extra_url", None):
        remove_extra_js_url(hass, url)


async def _async_fallback(hass: HomeAssistant, resources: Any, url: str) -> None:
    """Respect YAML resources and avoid registering an extra copy of the module."""
    if resources is not None and hasattr(resources, "async_items"):
        if hasattr(resources, "async_get_info"):
            await resources.async_get_info()
        if any(
            item["url"].partition("?")[0] == BUNDLE_URL
            for item in resources.async_items()
        ):
            _remove_fallback(hass)
            return
    data = hass.data[FRONTEND_DATA]
    if data.get("extra_url") != url:
        _remove_fallback(hass)
        add_extra_js_url(hass, url)
        data["extra_url"] = url


async def async_register_frontend(hass: HomeAssistant, *, _force: bool = False) -> None:
    """Register shared assets once; frontend failure must not block HVAC setup."""
    if not {"http", "frontend"} <= hass.config.components:
        return
    data = hass.data.setdefault(FRONTEND_DATA, {})
    async with data.setdefault("lock", asyncio.Lock()):
        try:
            resources, storage = _resource_collection(hass)
            key = (storage, id(resources))
            if not _force and data.get("key") == key:
                return
            url = await hass.async_add_executor_job(_versioned_url)
            if not data.get("static"):
                await hass.http.async_register_static_paths(
                    [
                        StaticPathConfig(
                            "/actronair_neo_frontend",
                            str(BUNDLE_PATH.parent),
                            cache_headers=True,
                        )
                    ]
                )
                data["static"] = True
            if storage:
                if not data.get("startup"):

                    async def after_start(started_hass: HomeAssistant) -> None:
                        await async_register_frontend(started_hass, _force=True)

                    data["startup"] = True
                    async_at_started(hass, after_start)
                await _async_reconcile(resources, url)
                _remove_fallback(hass)
            else:
                await _async_fallback(hass, resources, url)
            data["key"] = key
        except Exception as error:  # noqa: BLE001 - Dashboard failure must not disable HVAC.
            _LOGGER.warning(
                "Unable to register dashboard cards (%s): %s",
                type(error).__name__,
                error,
            )
