"""Tests for the Neo MQTT push transport."""

from __future__ import annotations

import asyncio
import contextlib
import json
import ssl
from typing import Self
from unittest.mock import AsyncMock, patch

import pytest
from aiomqtt import MqttError

from custom_components.actronair_neo.api.push import create_push_transport
from custom_components.actronair_neo.api.push.models import (
    PushState,
    RealtimeConnectionDetails,
)
from custom_components.actronair_neo.api.push.mqtt_transport import MqttPushTransport

DETAILS = RealtimeConnectionDetails(
    endpoint="mqtt.example", port=8883, protocol="ssl", user_id="u1"
)


def _transport(sink) -> MqttPushTransport:
    return MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=sink,
    )


@pytest.mark.asyncio
async def test_dispatch_full_status_calls_sink_full():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch(
        "actron-cloud/u1/neo/ser1/mwc/full-status", json.dumps({"a": 1}).encode()
    )
    sink.assert_awaited_once_with({"a": 1}, "full")


@pytest.mark.asyncio
async def test_dispatch_status_change_calls_sink_delta():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch("x/mwc/status-change", json.dumps({"a": 2}).encode())
    sink.assert_awaited_once_with({"a": 2}, "delta")


@pytest.mark.asyncio
async def test_dispatch_heartbeat_updates_state_no_sink():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch("x/mwc/heart-beat", b"{}")
    sink.assert_not_awaited()
    assert t.state is PushState.CONNECTED
    assert t.last_heartbeat is not None


@pytest.mark.asyncio
async def test_dispatch_drops_bad_json():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch("x/mwc/full-status", b"\xff\xfe not json")
    sink.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_swallows_sink_error():
    sink = AsyncMock(side_effect=RuntimeError("boom"))
    t = _transport(sink)
    await t._dispatch("x/mwc/full-status", b"{}")  # must not raise


def test_topics_built_correctly():
    t = _transport(AsyncMock())
    assert t._topics == [
        "actron-cloud/u1/neo/SER1/mwc/full-status",
        "actron-cloud/u1/neo/SER1/mwc/status-change",
        "actron-cloud/u1/neo/SER1/mwc/heart-beat",
        "actron-cloud/u1/neo/SER1/mwc/cmd-response/+/+",
    ]


@pytest.mark.asyncio
async def test_dispatch_cmd_response_ack_applies_event():
    """An ack'd command response forwards its embedded event as a delta."""
    sink = AsyncMock()
    t = _transport(sink)
    payload = {
        "correlationId": "m/cmd1",
        "commandResponse": {
            "type": "ack",
            "value": {"UserAirconSettings.QuietMode": False},
        },
        "event": {
            "type": "status-change-broadcast",
            "UserAirconSettings.QuietMode": False,
        },
        "wcFirmware": "2.6.2.3",
    }
    await t._dispatch(
        "actron-cloud/u1/neo/SER1/mwc/cmd-response/m/cmd1", json.dumps(payload).encode()
    )
    sink.assert_awaited_once_with(payload, "delta")


@pytest.mark.asyncio
async def test_dispatch_cmd_response_nack_warns(caplog):
    """A non-ack command response logs a warning."""
    sink = AsyncMock()
    t = _transport(sink)
    payload = {"commandResponse": {"type": "error", "value": {"x": 1}}}
    with caplog.at_level("WARNING"):
        await t._dispatch(
            "actron-cloud/u1/neo/SER1/mwc/cmd-response/m/cmd2",
            json.dumps(payload).encode(),
        )
    assert "not acknowledged" in caplog.text
    # No embedded event → nothing forwarded to the sink.
    sink.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_cmd_response_without_event_not_forwarded():
    """An ack with no embedded event is logged but not forwarded."""
    sink = AsyncMock()
    t = _transport(sink)
    payload = {"commandResponse": {"type": "ack", "value": {}}}
    await t._dispatch(
        "actron-cloud/u1/neo/SER1/mwc/cmd-response/m/cmd3", json.dumps(payload).encode()
    )
    sink.assert_not_awaited()


def test_backoff_schedule():
    t = _transport(AsyncMock())
    delays = []
    d = t._reconnect_initial
    for _ in range(9):
        delays.append(d)
        d = min(d * 2, t._reconnect_max)
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


@pytest.mark.asyncio
async def test_token_fetched_each_connect():
    provider = AsyncMock(return_value="tok")
    t = MqttPushTransport(
        details=DETAILS, serial="SER1", token_provider=provider, on_update=AsyncMock()
    )
    token = await t._token_provider()
    assert token == "tok"
    provider.assert_awaited()


def test_factory_neo_returns_mqtt():
    t = create_push_transport(
        platform="neo",
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(),
        on_update=AsyncMock(),
    )
    assert isinstance(t, MqttPushTransport)


def test_factory_passes_ssl_context_to_transport():
    sentinel = ssl.create_default_context()
    t = create_push_transport(
        platform="neo",
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(),
        on_update=AsyncMock(),
        ssl_context=sentinel,
    )
    assert isinstance(t, MqttPushTransport)
    assert t._ssl_context is sentinel


def test_default_client_factory_uses_injected_ssl_context():
    sentinel = ssl.create_default_context()
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        ssl_context=sentinel,
    )
    # The aiomqtt client must be built with our injected TLS context, not a
    # freshly created one (which would do blocking I/O and use the OS trust store).
    with patch(
        "custom_components.actronair_neo.api.push.mqtt_transport.Client"
    ) as mock_client:
        t._default_client_factory("tok")
    assert mock_client.call_args.kwargs["tls_context"] is sentinel


def test_factory_que_returns_none():
    assert (
        create_push_transport(
            platform="que",
            details=DETAILS,
            serial="SER1",
            token_provider=AsyncMock(),
            on_update=AsyncMock(),
        )
        is None
    )


# ---------------------------------------------------------------------------
# Fake helpers for start() integration tests
# ---------------------------------------------------------------------------


class _FakeMessage:
    """Minimal stand-in for an aiomqtt message."""

    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


class _FakeClient:
    """Async-context client that yields messages then blocks (live connection)."""

    def __init__(self, messages: list[_FakeMessage]) -> None:
        self._messages = messages
        self.subscribed: list[str] = []
        self.enter_count = 0

    async def __aenter__(self) -> Self:
        self.enter_count += 1
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def subscribe(self, topic: str) -> None:
        self.subscribed.append(topic)

    async def _gen(self):
        for message in self._messages:
            yield message
        # Emulate an open connection waiting for more messages.
        await asyncio.Event().wait()

    @property
    def messages(self):
        return self._gen()


class _FailingClient:
    """Client whose connect (aenter) raises, to exercise reconnect."""

    async def __aenter__(self) -> Self:
        raise MqttError("connect failed")

    async def __aexit__(self, *_exc: object) -> bool:
        return False


@pytest.mark.asyncio
async def test_start_fetches_token_subscribes_and_dispatches():
    sink = AsyncMock()
    provider = AsyncMock(return_value="tok")
    msg = _FakeMessage("actron-cloud/u1/neo/SER1/mwc/full-status", b'{"a": 1}')
    client = _FakeClient([msg])
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=provider,
        on_update=sink,
        client_factory=lambda _token: client,
    )
    task = asyncio.create_task(t.start())
    try:
        # Allow the loop to connect, subscribe, and dispatch the one message.
        for _ in range(20):
            await asyncio.sleep(0)
            if sink.await_count:
                break
        provider.assert_awaited()
        assert client.subscribed == t._topics
        sink.assert_awaited_once_with({"a": 1}, "full")
        assert t.state is PushState.CONNECTED
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_reconnects_with_backoff_and_refetches_token(monkeypatch):
    sink = AsyncMock()
    provider = AsyncMock(return_value="tok")
    clients = [_FailingClient(), _FakeClient([])]
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=provider,
        on_update=sink,
        client_factory=lambda _token: clients.pop(0),
    )
    sleeps: list[float] = []
    _real_sleep = asyncio.sleep  # save before patching

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        await _real_sleep(0)  # yield to event loop without the real delay

    monkeypatch.setattr(
        "custom_components.actronair_neo.api.push.mqtt_transport.asyncio.sleep",
        _fake_sleep,
    )
    task = asyncio.create_task(t.start())
    try:
        for _ in range(200):
            await _real_sleep(0)
            if t.reconnect_count >= 1 and provider.await_count >= 2:
                break
        assert t.reconnect_count == 1
        assert sleeps  # backoff sleep was called
        assert sleeps[0] == 0.5  # first backoff is the initial 0.5s
        assert provider.await_count >= 2  # token refetched on the retry connect
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# _dispatch edge cases
# ---------------------------------------------------------------------------

CMD_TOPIC = "actron-cloud/u1/neo/SER1/mwc/cmd-response/m/cmd9"


@pytest.mark.asyncio
async def test_dispatch_truncated_json_warns(caplog):
    sink = AsyncMock()
    t = _transport(sink)
    with caplog.at_level("WARNING"):
        await t._dispatch("x/mwc/full-status", b'{"a": 1')
    sink.assert_not_awaited()
    assert "Failed to decode JSON payload on x/mwc/full-status" in caplog.text


@pytest.mark.asyncio
async def test_dispatch_repairs_invalid_apostrophe_escape():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch("x/mwc/status-change", b'{"name": "Kurt\\\'s Office"}')
    sink.assert_awaited_once_with({"name": "Kurt's Office"}, "delta")


@pytest.mark.asyncio
async def test_dispatch_ignores_non_dict_json():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch("x/mwc/full-status", b"[1, 2, 3]")
    sink.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_ignores_unknown_topic():
    sink = AsyncMock()
    t = _transport(sink)
    await t._dispatch("x/mwc/something-else", b'{"a": 1}')
    sink.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_cmd_response_non_dict_response_still_applies_event(caplog):
    sink = AsyncMock()
    t = _transport(sink)
    payload = {"commandResponse": "ack", "event": {"UserAirconSettings.isOn": True}}
    with caplog.at_level("WARNING"):
        await t._dispatch(CMD_TOPIC, json.dumps(payload).encode())
    assert "not acknowledged" not in caplog.text
    sink.assert_awaited_once_with(payload, "delta")


@pytest.mark.asyncio
async def test_dispatch_cmd_response_non_ack_without_value_warns(caplog):
    sink = AsyncMock()
    t = _transport(sink)
    payload = {"commandResponse": {"type": "nack"}}
    with caplog.at_level("WARNING"):
        await t._dispatch(CMD_TOPIC, json.dumps(payload).encode())
    assert "not acknowledged (type=nack): None" in caplog.text
    sink.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_cmd_response_without_type_is_not_a_warning(caplog):
    sink = AsyncMock()
    t = _transport(sink)
    payload = {"commandResponse": {"value": 1}}
    with caplog.at_level("WARNING"):
        await t._dispatch(CMD_TOPIC, json.dumps(payload).encode())
    assert "not acknowledged" not in caplog.text
    sink.assert_not_awaited()


# ---------------------------------------------------------------------------
# _request_full_status
# ---------------------------------------------------------------------------


class _PublishRecorder:
    def __init__(self, *, sync: bool = False, error: Exception | None = None):
        self.calls: list[tuple[str, str]] = []
        self._sync = sync
        self._error = error

    def publish(self, topic: str, *, payload: str):
        self.calls.append((topic, payload))
        if self._error is not None:
            raise self._error
        if self._sync:
            return None

        async def _done() -> None:
            return None

        return _done()


@pytest.mark.asyncio
async def test_request_full_status_publishes_get_all_with_default_prefix():
    t = _transport(AsyncMock())
    client = _PublishRecorder()
    await t._request_full_status(client)
    assert len(client.calls) == 1
    topic, payload = client.calls[0]
    assert topic == "actron-cloud/u1/neo/SER1/app/cmd"
    body = json.loads(payload)
    assert body["command"] == {"type": "getAll"}
    assert body["correlationId"].startswith("HA/")
    assert body["OptOutOfLogging"] is False


@pytest.mark.asyncio
async def test_request_full_status_uses_client_id_prefix_and_sync_publish():
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        client_id="cid",
    )
    client = _PublishRecorder(sync=True)
    await t._request_full_status(client)
    assert json.loads(client.calls[0][1])["correlationId"].startswith("cid/")


@pytest.mark.asyncio
async def test_request_full_status_suppresses_publish_error():
    t = _transport(AsyncMock())
    client = _PublishRecorder(error=RuntimeError("boom"))
    await t._request_full_status(client)  # must not raise
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_request_full_status_without_publish_is_noop():
    t = _transport(AsyncMock())
    await t._request_full_status(object())  # must not raise


# ---------------------------------------------------------------------------
# _default_client_factory
# ---------------------------------------------------------------------------


def test_default_client_factory_non_tls_with_username_and_client_id():
    details = RealtimeConnectionDetails(
        endpoint="mqtt.plain", port=1883, protocol="tcp", user_id="u1"
    )
    t = MqttPushTransport(
        details=details,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        username="user@example.com",
        client_id="cid",
    )
    with patch(
        "custom_components.actronair_neo.api.push.mqtt_transport.Client"
    ) as mock_client:
        t._default_client_factory("tok")
    args, kwargs = mock_client.call_args
    assert args == ("mqtt.plain", 1883)
    assert "tls_context" not in kwargs
    assert kwargs["username"] == "user@example.com"
    assert kwargs["password"] == "tok"
    assert kwargs["identifier"] == "cid"
    assert kwargs["clean_session"] is False


def test_default_client_factory_random_identifier_and_default_tls():
    t = _transport(AsyncMock())
    with patch(
        "custom_components.actronair_neo.api.push.mqtt_transport.Client"
    ) as mock_client:
        t._default_client_factory("tok")
    kwargs = mock_client.call_args.kwargs
    assert kwargs["clean_session"] is True
    assert len(kwargs["identifier"]) == 32
    assert isinstance(kwargs["tls_context"], ssl.SSLContext)


# ---------------------------------------------------------------------------
# start() reconnect, stop and cancellation
# ---------------------------------------------------------------------------

SLEEP_PATH = "custom_components.actronair_neo.api.push.mqtt_transport.asyncio.sleep"


class _DroppingClient(_FakeClient):
    """Connects, then the message stream fails with ``error``."""

    def __init__(self, error: Exception) -> None:
        super().__init__([])
        self._error = error

    async def _gen(self):
        raise self._error
        yield  # pragma: no cover - makes this an async generator


class _GatedClient(_FakeClient):
    """Connects, then raises MqttError once ``release`` is set."""

    def __init__(self) -> None:
        super().__init__([])
        self.connected = asyncio.Event()
        self.release = asyncio.Event()

    async def _gen(self):
        self.connected.set()
        await self.release.wait()
        raise MqttError("connection lost")
        yield  # pragma: no cover - makes this an async generator


@pytest.mark.asyncio
async def test_start_backoff_doubles_caps_and_resets(monkeypatch):
    provider = AsyncMock(return_value="tok")
    clients: list = [
        _FailingClient(),
        _FailingClient(),
        _FailingClient(),
        _DroppingClient(OSError("socket closed")),
        _FailingClient(),
    ]
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=provider,
        on_update=AsyncMock(),
        client_factory=lambda _token: clients.pop(0),
    )
    t._reconnect_max = 1.0
    sleeps: list[float] = []
    errors: list[str | None] = []

    async def _fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        errors.append(t.last_error)
        if not clients:
            await t.stop()

    monkeypatch.setattr(SLEEP_PATH, _fake_sleep)
    await asyncio.wait_for(t.start(), timeout=5)

    # 0.5 → 1.0 → capped at 1.0, reset to 0.5 by the successful connect,
    # then doubling resumes.
    assert sleeps == [0.5, 1.0, 1.0, 0.5, 1.0]
    assert errors == [
        "MqttError",
        "MqttError",
        "MqttError",
        "OSError",
        "MqttError",
    ]
    assert t.reconnect_count == 5
    assert t.last_error == "MqttError"
    assert t.state is PushState.DISCONNECTED
    assert provider.await_count == 5


@pytest.mark.asyncio
async def test_start_successful_connect_clears_last_error(monkeypatch):
    client = _GatedClient()
    clients: list = [_FailingClient(), client]
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        client_factory=lambda _token: clients.pop(0),
    )
    monkeypatch.setattr(SLEEP_PATH, AsyncMock())
    task = asyncio.create_task(t.start())
    try:
        await asyncio.wait_for(client.connected.wait(), timeout=5)
        assert t.reconnect_count == 1
        assert t.last_error is None
        assert t.state is PushState.CONNECTED
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_token_provider_mqtt_error_triggers_reconnect(monkeypatch):
    provider = AsyncMock(side_effect=[MqttError("token broker"), "tok"])
    client = _GatedClient()
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=provider,
        on_update=AsyncMock(),
        client_factory=lambda _token: client,
    )
    seen: list[str | None] = []

    async def _fake_sleep(_delay: float) -> None:
        seen.append(t.last_error)

    monkeypatch.setattr(SLEEP_PATH, _fake_sleep)
    task = asyncio.create_task(t.start())
    try:
        await asyncio.wait_for(client.connected.wait(), timeout=5)
        assert seen == ["MqttError"]
        assert t.reconnect_count == 1
        assert provider.await_count == 2
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_stop_from_other_task_exits_loop_without_reconnect(monkeypatch):
    client = _GatedClient()
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        client_factory=lambda _token: client,
    )
    sleep_mock = AsyncMock()
    monkeypatch.setattr(SLEEP_PATH, sleep_mock)
    task = asyncio.create_task(t.start())
    try:
        await asyncio.wait_for(client.connected.wait(), timeout=5)
        stopper = asyncio.create_task(t.stop())
        await stopper
        assert t.state is PushState.DISCONNECTED
        # The connection drops after stop(); the loop must break, not retry.
        client.release.set()
        await asyncio.wait_for(task, timeout=5)
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    assert t.state is PushState.DISCONNECTED
    assert t.reconnect_count == 0
    assert t.last_error is None
    sleep_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_cancelled_during_backoff_sleep_propagates(monkeypatch):
    sleeping = asyncio.Event()

    async def _blocking_sleep(_delay: float) -> None:
        sleeping.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(SLEEP_PATH, _blocking_sleep)
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        client_factory=lambda _token: _FailingClient(),
    )
    task = asyncio.create_task(t.start())
    try:
        await asyncio.wait_for(sleeping.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    assert t.reconnect_count == 1


@pytest.mark.asyncio
async def test_start_cancelled_during_message_iteration_propagates():
    client = _GatedClient()
    t = MqttPushTransport(
        details=DETAILS,
        serial="SER1",
        token_provider=AsyncMock(return_value="tok"),
        on_update=AsyncMock(),
        client_factory=lambda _token: client,
    )
    task = asyncio.create_task(t.start())
    try:
        await asyncio.wait_for(client.connected.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    assert t.reconnect_count == 0


def test_initial_base_state_properties():
    t = _transport(AsyncMock())
    assert t.state is PushState.DISCONNECTED
    assert t.last_heartbeat is None
    assert t.reconnect_count == 0
    assert t.last_error is None
