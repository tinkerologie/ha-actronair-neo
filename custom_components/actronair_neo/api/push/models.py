"""Models for the realtime push transport."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, cast

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


class PushState(StrEnum):
    """Lifecycle state of a push transport."""

    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STALE = "stale"


_TLS_PROTOCOLS = frozenset({"ssl", "tls", "mqtts"})


class RealtimeConnectionDetails(BaseModel):
    """Broker connection details returned by the discovery endpoint."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    endpoint: str = Field(
        validation_alias=AliasChoices(
            "endPoint", "endpoint", "Endpoint", "host", "server"
        )
    )
    port: int = Field(
        default=443,
        validation_alias=AliasChoices("port", "Port"),
    )
    protocol: str = Field(
        default="ssl",
        validation_alias=AliasChoices("protocol", "Protocol", "scheme"),
    )
    user_id: str = Field(
        default="unknown",
        validation_alias=AliasChoices("userId", "UserId", "user_id", "username"),
    )
    opt_out_of_logging: bool = Field(
        default=True,
        validation_alias=AliasChoices("OptOutOfLogging", "optOutOfLogging"),
    )

    @model_validator(mode="before")
    @classmethod
    def _unwrap_rtc_details(cls, data: Any) -> Any:
        """Unwrap RTCDetails/rtcDetails envelope and pick first non-empty alias."""
        if not isinstance(data, dict):
            return data
        raw = cast("dict[str, Any]", data)
        inner = raw.get("RTCDetails") or raw.get("rtcDetails")
        details = (
            dict(cast("dict[str, Any]", inner))
            if isinstance(inner, dict)
            else dict(raw)
        )

        # Normalize empty string aliases so AliasChoices selects a non-empty value
        for key in list(details.keys()):
            val = details[key]
            if isinstance(val, str) and not val.strip():
                del details[key]
        return details

    @field_validator("port", mode="before")
    @classmethod
    def _coerce_port(cls, value: Any) -> int:
        """Coerce port value, defaulting booleans and invalid values to 443."""
        if isinstance(value, bool):
            return 443
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return 443

    @field_validator("opt_out_of_logging", mode="before")
    @classmethod
    def _validate_opt_out_of_logging(cls, value: object) -> bool:
        """Opt out of logging when the cloud preference is unknown."""
        return value if isinstance(value, bool) else True

    @property
    def uses_tls(self) -> bool:
        """Return True when the broker connection should use TLS."""
        return self.protocol.lower() in _TLS_PROTOCOLS

    @classmethod
    def from_payload(cls, payload: Any) -> RealtimeConnectionDetails | None:
        """Parse a discovery payload, tolerating field-name variations."""
        if not isinstance(payload, dict):
            return None
        payload_dict = cast("dict[str, Any]", payload)
        details_candidate = payload_dict.get("RTCDetails") or payload_dict.get(
            "rtcDetails"
        )
        if details_candidate is not None and not isinstance(details_candidate, dict):
            return None
        try:
            parsed = cls.model_validate(payload)
        except ValidationError:
            return None
        if not parsed.endpoint:
            return None
        return parsed
