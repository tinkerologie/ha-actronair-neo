"""Tests for the push delta deep-merge helper."""

from __future__ import annotations

import json

import pytest

from custom_components.actronair_neo.api.push.merge import (
    apply_event_paths,
    deep_merge,
    loads_repairing_escapes,
)


def test_apply_event_paths_nested_dict():
    state = {"UserAirconSettings": {"Mode": "HEAT", "isOn": True}}
    event = {"type": "status-change-broadcast", "UserAirconSettings.Mode": "COOL"}
    out = apply_event_paths(state, event)
    assert out["UserAirconSettings"]["Mode"] == "COOL"
    assert out["UserAirconSettings"]["isOn"] is True  # sibling preserved


def test_apply_event_paths_list_index():
    state = {"RemoteZoneInfo": [{"LiveTemp_oC": 20.0}, {"LiveTemp_oC": 21.0}]}
    out = apply_event_paths(state, {"RemoteZoneInfo[1].LiveTemp_oC": 26.0})
    assert out["RemoteZoneInfo"][1]["LiveTemp_oC"] == 26.0
    assert out["RemoteZoneInfo"][0]["LiveTemp_oC"] == 20.0  # other zone preserved


def test_apply_event_paths_deeply_nested():
    state = {"LiveAircon": {"OutdoorUnit": {"RoomTemp": 25.0}}}
    out = apply_event_paths(state, {"LiveAircon.OutdoorUnit.RoomTemp": 26.9})
    assert out["LiveAircon"]["OutdoorUnit"]["RoomTemp"] == 26.9


def test_apply_event_paths_extends_list_when_index_missing():
    out = apply_event_paths({}, {"RemoteZoneInfo[2].LiveTemp_oC": 22.5})
    assert out["RemoteZoneInfo"][2]["LiveTemp_oC"] == 22.5
    assert len(out["RemoteZoneInfo"]) == 3


def test_apply_event_paths_ignores_type_and_does_not_mutate():
    state = {"UserAirconSettings": {"Mode": "HEAT"}}
    event = {"type": "status-change-broadcast", "UserAirconSettings.Mode": "COOL"}
    apply_event_paths(state, event)
    assert state["UserAirconSettings"]["Mode"] == "HEAT"  # input untouched
    assert "type" not in apply_event_paths(state, event)


def test_nested_merge_preserves_siblings():
    base = {"a": {"x": 1, "y": 2}, "b": 9}
    delta = {"a": {"y": 20, "z": 30}}
    assert deep_merge(base, delta) == {"a": {"x": 1, "y": 20, "z": 30}, "b": 9}


def test_scalar_overwrite_and_new_key():
    assert deep_merge({"a": 1}, {"a": 2, "b": 3}) == {"a": 2, "b": 3}


def test_lists_replaced_wholesale():
    base = {"zones": [True, True, False]}
    delta = {"zones": [False]}
    assert deep_merge(base, delta) == {"zones": [False]}


def test_empty_delta_is_noop():
    base = {"a": {"x": 1}}
    assert deep_merge(base, {}) == {"a": {"x": 1}}


def test_merge_into_empty_base():
    assert deep_merge({}, {"a": {"x": 1}}) == {"a": {"x": 1}}


def test_inputs_not_mutated():
    base = {"a": {"x": 1}}
    delta = {"a": {"y": 2}}
    deep_merge(base, delta)
    assert base == {"a": {"x": 1}}
    assert delta == {"a": {"y": 2}}


# ---------------------------------------------------------------------------
# loads_repairing_escapes
# ---------------------------------------------------------------------------


def test_loads_repairing_escapes_valid_json():
    assert loads_repairing_escapes('{"a": [1, "b"]}') == {"a": [1, "b"]}


def test_loads_repairing_escapes_repairs_apostrophe_and_keeps_valid_escapes():
    text = r'{"name": "Kurt\'s \"Office\"", "path": "a\\b", "u": "\u00e9"}'
    assert loads_repairing_escapes(text) == {
        "name": 'Kurt\'s "Office"',
        "path": "a\\b",
        "u": "\u00e9",
    }


def test_loads_repairing_escapes_reraises_without_apostrophe_escape():
    with pytest.raises(json.JSONDecodeError):
        loads_repairing_escapes('{"a": 1')


def test_loads_repairing_escapes_reraises_when_repair_still_invalid():
    with pytest.raises(json.JSONDecodeError):
        loads_repairing_escapes(r'{"a": "x\'s"')


# ---------------------------------------------------------------------------
# apply_event_paths edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["", "[0].a", "a..b[", "a[x]", "]"])
def test_apply_event_paths_ignores_unparsable_paths(path):
    state = {"a": {"b": 1}}
    assert apply_event_paths(state, {path: 99}) == state


def test_apply_event_paths_leading_dots_are_skipped():
    assert apply_event_paths({}, {".a.b": 1}) == {"a": {"b": 1}}


def test_apply_event_paths_pads_bool_list_with_false():
    out = apply_event_paths({}, {"UserAirconSettings.EnabledZones[3]": True})
    assert out["UserAirconSettings"]["EnabledZones"] == [False, False, False, True]


def test_apply_event_paths_pads_non_bool_list_with_none():
    out = apply_event_paths({"a": [1]}, {"a[3]": 5})
    assert out["a"] == [1, None, None, 5]


def test_apply_event_paths_pads_nested_list_with_lists():
    out = apply_event_paths({}, {"a[1][2]": "x"})
    assert out["a"] == [[], [None, None, "x"]]


def test_apply_event_paths_pads_with_independent_dicts():
    out = apply_event_paths({}, {"a[1].b": 1})
    assert out["a"] == [{}, {"b": 1}]
    assert out["a"][0] is not out["a"][1]


def test_apply_event_paths_replaces_wrong_type_list_element():
    out = apply_event_paths({"a": [5, [1]]}, {"a[0].b": 1, "a[1][0]": 2})
    assert out["a"] == [{"b": 1}, [2]]


def test_apply_event_paths_replaces_wrong_type_list_element_with_list():
    out = apply_event_paths({"a": [{"k": 1}]}, {"a[0][1]": True})
    assert out["a"] == [[False, True]]


def test_apply_event_paths_replaces_wrong_type_intermediate_dict_value():
    state = {"a": 5, "b": {"x": 1}, "c": [1]}
    out = apply_event_paths(state, {"a.b": 1, "b[0]": 2, "c.d": 3})
    assert out == {"a": {"b": 1}, "b": [2], "c": {"d": 3}}
    assert state == {"a": 5, "b": {"x": 1}, "c": [1]}


def test_apply_event_paths_overwrites_existing_list_element():
    out = apply_event_paths({"a": [1, 2, 3]}, {"a[1]": 20})
    assert out["a"] == [1, 20, 3]


def test_apply_event_paths_angle_bracket_key_keeps_dots():
    out = apply_event_paths(
        {}, {"Peripherals.<10.0.0.1>.Battery": 80, "<x.y>[1]": True}
    )
    assert out == {
        "Peripherals": {"<10.0.0.1>": {"Battery": 80}},
        "<x.y>": [False, True],
    }
