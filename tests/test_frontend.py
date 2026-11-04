"""Verify card resource ownership and safe optional frontend registration."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState
from homeassistant.helpers.collection import ItemNotFound
from homeassistant.setup import async_setup_component

from custom_components.actronair_neo.frontend import (
    BUNDLE_URL,
    FRONTEND_DATA,
    _resource_collection,
    _versioned_url,
    async_register_frontend,
)

_MOD = "custom_components.actronair_neo.frontend"


async def test_resource_reconciles_only_owned_duplicates(hass):
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    resources = MagicMock()
    resources.async_get_info = AsyncMock()
    items = [
        {"id": "old", "url": BUNDLE_URL + "?v=old", "type": "module"},
        {"id": "duplicate", "url": BUNDLE_URL, "type": "module"},
        {"id": "other", "url": "/other/custom.js", "type": "module"},
    ]
    resources.async_items.side_effect = lambda: list(items)

    async def update(item_id, data):
        next(item for item in items if item["id"] == item_id).update(
            url=data["url"], type=data["res_type"]
        )

    async def delete(item_id):
        items[:] = [item for item in items if item["id"] != item_id]

    resources.async_update_item = AsyncMock(side_effect=update)
    resources.async_delete_item = AsyncMock(side_effect=delete)
    with (
        patch(
            "custom_components.actronair_neo.frontend._resource_collection",
            return_value=(resources, True),
        ),
        patch.object(
            hass.http, "async_register_static_paths", new_callable=AsyncMock
        ) as static,
    ):
        await async_register_frontend(hass)
        await async_register_frontend(hass)
    static.assert_awaited_once()
    resources.async_update_item.assert_awaited_once()
    resources.async_delete_item.assert_awaited_once_with("duplicate")


async def test_yaml_existing_resource_prevents_fallback(hass):
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    resources = MagicMock()
    resources.async_get_info = AsyncMock()
    resources.async_items.return_value = [{"url": BUNDLE_URL, "type": "module"}]
    with (
        patch(
            "custom_components.actronair_neo.frontend._resource_collection",
            return_value=(resources, False),
        ),
        patch("custom_components.actronair_neo.frontend.add_extra_js_url") as fallback,
        patch.object(hass.http, "async_register_static_paths", new_callable=AsyncMock),
    ):
        await async_register_frontend(hass)
    fallback.assert_not_called()


async def test_missing_frontend_is_optional(hass):
    with patch("custom_components.actronair_neo.frontend._versioned_url") as read:
        await async_register_frontend(hass)
    read.assert_not_called()


async def test_missing_bundle_does_not_fail_setup(hass, caplog):
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with (
        patch(
            "custom_components.actronair_neo.frontend._versioned_url",
            side_effect=FileNotFoundError("missing bundle"),
        ),
        patch(
            "custom_components.actronair_neo.frontend._resource_collection",
            return_value=(None, False),
        ),
    ):
        await async_register_frontend(hass)
    assert "Unable to register dashboard cards" in caplog.text


async def test_yaml_fallback_is_added_only_once(hass):
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    with (
        patch(
            "custom_components.actronair_neo.frontend._resource_collection",
            return_value=(None, False),
        ),
        patch("custom_components.actronair_neo.frontend.add_extra_js_url") as fallback,
        patch.object(
            hass.http, "async_register_static_paths", new_callable=AsyncMock
        ) as static,
    ):
        await async_register_frontend(hass)
        await async_register_frontend(hass)
    fallback.assert_called_once()
    static.assert_awaited_once()


async def test_storage_creates_resource_and_removes_yaml_fallback(hass):
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")
    resources = MagicMock()
    resources.async_get_info = AsyncMock()
    items = []
    resources.async_items.side_effect = lambda: list(items)

    async def create(data):
        items.append({"id": "created", "url": data["url"], "type": data["res_type"]})

    resources.async_create_item = AsyncMock(side_effect=create)
    with (
        patch(
            "custom_components.actronair_neo.frontend._resource_collection",
            side_effect=[(None, False), (resources, True), (resources, True)],
        ),
        patch("custom_components.actronair_neo.frontend.add_extra_js_url"),
        patch("custom_components.actronair_neo.frontend.remove_extra_js_url") as remove,
        patch.object(
            hass.http, "async_register_static_paths", new_callable=AsyncMock
        ) as static,
    ):
        await async_register_frontend(hass)
        await async_register_frontend(hass)
        await hass.async_block_till_done()
    resources.async_create_item.assert_awaited_once()
    remove.assert_called_once()
    static.assert_awaited_once()


def _storage_resources(items):
    """Return a storage-collection double backed by ``items``."""
    resources = MagicMock()
    resources.async_get_info = AsyncMock()
    resources.async_items.side_effect = lambda: list(items)

    async def create(data):
        items.append({"id": "new", "url": data["url"], "type": data["res_type"]})

    async def update(item_id, data):
        next(item for item in items if item["id"] == item_id).update(
            url=data["url"], type=data["res_type"]
        )

    resources.async_create_item = AsyncMock(side_effect=create)
    resources.async_update_item = AsyncMock(side_effect=update)
    resources.async_delete_item = AsyncMock()
    return resources


async def _setup_http(hass):
    assert await async_setup_component(hass, "http", {})
    hass.config.components.add("frontend")


async def test_missing_http_component_returns_early(hass):
    hass.config.components.add("frontend")
    with patch("custom_components.actronair_neo.frontend._versioned_url") as read:
        await async_register_frontend(hass)
    read.assert_not_called()
    assert FRONTEND_DATA not in hass.data


def test_resource_collection_without_lovelace(hass):
    assert _resource_collection(hass) == (None, False)


def test_resource_collection_with_lovelace(hass):
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from homeassistant.components.lovelace.resources import (
        ResourceStorageCollection,
    )

    storage = MagicMock(spec=ResourceStorageCollection)
    hass.data[LOVELACE_DATA] = MagicMock(resources=storage)
    try:
        assert _resource_collection(hass) == (storage, True)
        yaml_resources = MagicMock()
        hass.data[LOVELACE_DATA] = MagicMock(resources=yaml_resources)
        assert _resource_collection(hass) == (yaml_resources, False)
    finally:
        hass.data.pop(LOVELACE_DATA)


def test_versioned_url_includes_version_and_digest():
    url = _versioned_url()
    assert url.startswith(BUNDLE_URL + "?v=")


async def test_reconcile_updates_non_module_and_suppresses_missing_delete(hass):
    await _setup_http(hass)
    items = [
        {"id": "a", "url": BUNDLE_URL + "?v=1", "type": "js"},
        {"id": "b", "url": BUNDLE_URL + "?v=dup", "type": "module"},
    ]
    resources = _storage_resources(items)
    resources.async_delete_item.side_effect = ItemNotFound("b")
    with (
        patch(f"{_MOD}._versioned_url", return_value=BUNDLE_URL + "?v=1"),
        patch(f"{_MOD}._resource_collection", return_value=(resources, True)),
        patch.object(hass.http, "async_register_static_paths", new_callable=AsyncMock),
    ):
        # Same URL but wrong type still triggers an update.
        await async_register_frontend(hass)
    resources.async_update_item.assert_awaited_once_with(
        "a", {"url": BUNDLE_URL + "?v=1", "res_type": "module"}
    )
    resources.async_delete_item.assert_awaited_once_with("b")


async def test_reconcile_noop_when_current(hass):
    await _setup_http(hass)
    items = [{"id": "a", "url": BUNDLE_URL + "?v=1", "type": "module"}]
    resources = _storage_resources(items)
    with (
        patch(f"{_MOD}._versioned_url", return_value=BUNDLE_URL + "?v=1"),
        patch(f"{_MOD}._resource_collection", return_value=(resources, True)),
        patch.object(hass.http, "async_register_static_paths", new_callable=AsyncMock),
    ):
        await async_register_frontend(hass)
    resources.async_create_item.assert_not_awaited()
    resources.async_update_item.assert_not_awaited()


async def test_force_bypasses_key_and_fallback_url_change(hass):
    await _setup_http(hass)
    urls = iter([BUNDLE_URL + "?v=1", BUNDLE_URL + "?v=1", BUNDLE_URL + "?v=2"])
    with (
        patch(f"{_MOD}._versioned_url", side_effect=lambda: next(urls)),
        patch(f"{_MOD}._resource_collection", return_value=(None, False)),
        patch(f"{_MOD}.add_extra_js_url") as add,
        patch(f"{_MOD}.remove_extra_js_url") as remove,
        patch.object(
            hass.http, "async_register_static_paths", new_callable=AsyncMock
        ) as static,
    ):
        await async_register_frontend(hass)
        # Same key short-circuits without re-reading the bundle.
        await async_register_frontend(hass)
        # Forced with an unchanged URL keeps the fallback as is.
        await async_register_frontend(hass, _force=True)
        assert add.call_count == 1
        remove.assert_not_called()
        # Forced with a new URL swaps the fallback.
        await async_register_frontend(hass, _force=True)
    assert add.call_count == 2
    remove.assert_called_once_with(hass, BUNDLE_URL + "?v=1")
    assert hass.data[FRONTEND_DATA]["extra_url"] == BUNDLE_URL + "?v=2"
    static.assert_awaited_once()


async def test_yaml_resources_without_get_info_or_match_use_fallback(hass):
    await _setup_http(hass)

    class _YamlResources:
        def async_items(self):
            return [{"url": "/other/card.js", "type": "module"}]

    with (
        patch(f"{_MOD}._versioned_url", return_value=BUNDLE_URL + "?v=1"),
        patch(f"{_MOD}._resource_collection", return_value=(_YamlResources(), False)),
        patch(f"{_MOD}.add_extra_js_url") as add,
        patch.object(hass.http, "async_register_static_paths", new_callable=AsyncMock),
    ):
        await async_register_frontend(hass)
    add.assert_called_once_with(hass, BUNDLE_URL + "?v=1")


async def test_storage_reregisters_after_started(hass):
    await _setup_http(hass)
    items = []
    resources = _storage_resources(items)
    hass.set_state(CoreState.not_running)
    try:
        with (
            patch(f"{_MOD}._versioned_url", return_value=BUNDLE_URL + "?v=1"),
            patch(f"{_MOD}._resource_collection", return_value=(resources, True)),
            patch.object(
                hass.http, "async_register_static_paths", new_callable=AsyncMock
            ),
        ):
            await async_register_frontend(hass)
            assert resources.async_get_info.await_count == 1
            # A second registration does not schedule another start listener.
            await async_register_frontend(hass, _force=True)
            assert resources.async_get_info.await_count == 2
            hass.set_state(CoreState.running)
            hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
            await hass.async_block_till_done()
            assert resources.async_get_info.await_count == 3
    finally:
        hass.set_state(CoreState.running)
    resources.async_create_item.assert_awaited_once()


async def test_concurrent_registration_is_serialised(hass):
    await _setup_http(hass)
    with (
        patch(f"{_MOD}._versioned_url", return_value=BUNDLE_URL + "?v=1") as read,
        patch(f"{_MOD}._resource_collection", return_value=(None, False)),
        patch(f"{_MOD}.add_extra_js_url") as add,
        patch.object(
            hass.http, "async_register_static_paths", new_callable=AsyncMock
        ) as static,
    ):
        await asyncio.gather(
            async_register_frontend(hass), async_register_frontend(hass)
        )
    read.assert_called_once()
    add.assert_called_once()
    static.assert_awaited_once()
