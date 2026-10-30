"""Verify card resource ownership and safe optional frontend registration."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.setup import async_setup_component

from custom_components.actronair_neo.frontend import BUNDLE_URL, async_register_frontend


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
