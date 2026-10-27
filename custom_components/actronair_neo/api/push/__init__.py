"""Realtime push transport for the ActronAir Neo integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import PushTransport

# Imported at module level so aiomqtt (a manifest requirement) loads while
# Home Assistant imports the integration in its executor, not inside the event
# loop when push starts, where its package metadata reads are blocking I/O.
from .mqtt_transport import MqttPushTransport

if TYPE_CHECKING:
    import ssl

    from .base import TokenProvider, UpdateSink
    from .models import RealtimeConnectionDetails

_LOGGER = logging.getLogger(__name__)

__all__ = ["PushTransport", "create_push_transport"]


def create_push_transport(  # noqa: PLR0913
    *,
    platform: str,
    details: RealtimeConnectionDetails,
    serial: str,
    token_provider: TokenProvider,
    on_update: UpdateSink,
    ssl_context: ssl.SSLContext | None = None,
    username: str = "",
    client_id: str | None = None,
) -> PushTransport | None:
    """Return a push transport for the platform, or None if unsupported."""
    if platform == "neo":
        return MqttPushTransport(
            details=details,
            serial=serial,
            token_provider=token_provider,
            on_update=on_update,
            ssl_context=ssl_context,
            username=username,
            client_id=client_id,
        )
    _LOGGER.info(
        "Realtime push not yet implemented for platform %r; polling only", platform
    )
    return None
