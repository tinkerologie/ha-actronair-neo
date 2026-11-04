"""Tests for realtime connection-details parsing."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from custom_components.actronair_neo.api.push.models import RealtimeConnectionDetails


def test_parses_canonical_fields():
    d = RealtimeConnectionDetails.from_payload(
        {"endPoint": "mqtt.example", "port": 8883, "protocol": "tls", "userId": "u1"}
    )
    assert (d.endpoint, d.port, d.protocol, d.user_id) == (
        "mqtt.example",
        8883,
        "tls",
        "u1",
    )


def test_field_name_fallbacks_and_defaults():
    d = RealtimeConnectionDetails.from_payload({"host": "h.example"})
    assert d.endpoint == "h.example"
    assert d.port == 443
    assert d.protocol == "ssl"
    assert d.user_id == "unknown"


def test_non_numeric_port_defaults_to_443():
    d = RealtimeConnectionDetails.from_payload({"endpoint": "h", "port": "abc"})
    assert d.port == 443


def test_string_port_coerced():
    d = RealtimeConnectionDetails.from_payload({"endpoint": "h", "port": "8883"})
    assert d.port == 8883


def test_nested_rtcdetails_unwrapped():
    d = RealtimeConnectionDetails.from_payload({"RTCDetails": {"endpoint": "nested"}})
    assert d.endpoint == "nested"


def test_missing_endpoint_returns_none():
    assert RealtimeConnectionDetails.from_payload({"userId": "u"}) is None


def test_uses_tls():
    assert RealtimeConnectionDetails.from_payload(
        {"endpoint": "h", "protocol": "SSL"}
    ).uses_tls
    assert not RealtimeConnectionDetails.from_payload(
        {"endpoint": "h", "protocol": "tcp"}
    ).uses_tls


def test_uses_tls_all_tls_protocols():
    for proto in ("tls", "mqtts", "ssl", "SSL"):
        details = RealtimeConnectionDetails.from_payload(
            {"endpoint": "h", "protocol": proto}
        )
        assert details.uses_tls


def test_bool_port_defaults_to_443():
    d = RealtimeConnectionDetails.from_payload({"endpoint": "h", "port": True})
    assert d.port == 443


def test_lowercase_rtcdetails_unwrapped():
    d = RealtimeConnectionDetails.from_payload({"rtcDetails": {"endpoint": "nested"}})
    assert d.endpoint == "nested"


@pytest.mark.parametrize("payload", [None, "endpoint", ["endpoint"], 42])
def test_non_dict_payload_returns_none(payload):
    assert RealtimeConnectionDetails.from_payload(payload) is None


@pytest.mark.parametrize("key", ["RTCDetails", "rtcDetails"])
def test_non_dict_rtcdetails_returns_none(key):
    assert RealtimeConnectionDetails.from_payload({key: "mqtt.example"}) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"endpoint": 123},
        {"endpoint": ["h"]},
        {"endpoint": "h", "protocol": 5},
        {"RTCDetails": {"userId": "u"}},
    ],
)
def test_invalid_payload_returns_none(payload):
    assert RealtimeConnectionDetails.from_payload(payload) is None


def test_empty_and_whitespace_aliases_are_dropped():
    d = RealtimeConnectionDetails.from_payload(
        {
            "endPoint": "",
            "endpoint": "   ",
            "host": "real.example",
            "protocol": " ",
            "userId": "",
            "username": "u2",
        }
    )
    assert d.endpoint == "real.example"
    assert d.protocol == "ssl"
    assert d.user_id == "u2"


def test_only_blank_endpoints_returns_none():
    assert RealtimeConnectionDetails.from_payload({"endpoint": " ", "host": ""}) is None


def test_empty_rtcdetails_falls_back_to_top_level():
    d = RealtimeConnectionDetails.from_payload({"RTCDetails": {}, "endpoint": "top"})
    assert d.endpoint == "top"


def test_model_validate_non_dict_is_rejected_by_pydantic():
    with pytest.raises(ValidationError):
        RealtimeConnectionDetails.model_validate("mqtt.example")
