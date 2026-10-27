"""Pure helpers for applying realtime status deltas and repairing Actron JSON."""

from __future__ import annotations

import copy
import json
import re
from typing import Any, cast

# Matches either a key segment (preserving <...> peripheral identifiers with dots)
# or a bracketed list index like [0].
_FLAT_KEY_SEGMENT_RE = re.compile(r"(<[^>]+>|[^.\[\]]+)|\[(\d+)\]")

# Matches valid JSON escape sequences first, or an invalid \' escape sequence.
# Stepping over valid escapes ensures \\' (escaped backslash before quote) is untouched.
_ESCAPE_SEQUENCE_RE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|["\\/bfnrtu])|(\\\')')


def loads_repairing_escapes(text: str) -> Any:
    r"""
    Parse JSON text, repairing invalid ``\'`` apostrophe escapes from firmware.

    Actron Neo/Que firmware escapes single quotes inside JSON strings (e.g. zone
    names like ``"Kurt\'s Office"``), which violates RFC 8259.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "\\'" not in text:
            raise
        repaired = _ESCAPE_SEQUENCE_RE.sub(
            lambda m: "'" if m.group(1) else m.group(0),
            text,
        )
        return json.loads(repaired)


def apply_event_paths(state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    """
    Apply an Actron ``status-change-broadcast`` event onto a copy of ``state``.

    The broker sends incremental changes as flattened path → value pairs, e.g.::

        {"type": "status-change-broadcast",
         "UserAirconSettings.Mode": "COOL",
         "UserAirconSettings.EnabledZones[6]": True,
         "RemoteZoneInfo[0].LiveTemp_oC": 24.2}

    Each path is split into nested dict keys and ``[index]`` list positions and
    written into a deep copy of ``state`` (so the input is not mutated). The
    ``type`` marker and any unparsable path are ignored.
    """
    result = copy.deepcopy(state)
    for path, value in event.items():
        if path == "type":
            continue
        _set_path(result, path, value)
    return result


def _parse_flat_path(path: str) -> list[tuple[str | None, int | None]]:
    """Tokenize a flattened path into ``(key, index)`` pairs."""
    tokens: list[tuple[str | None, int | None]] = []
    pos = 0
    length = len(path)
    while pos < length:
        if path[pos] == ".":
            pos += 1
            continue
        match = _FLAT_KEY_SEGMENT_RE.match(path, pos)
        if not match:
            return []
        key_token, idx_token = match.group(1), match.group(2)
        tokens.append((key_token, int(idx_token) if idx_token is not None else None))
        pos = match.end()
    return tokens


def _step_dict(
    cur: dict[str, Any],
    key: str,
    *,
    is_last: bool,
    next_is_index: bool,
    value: Any,
) -> Any:
    """Advance or write a dict key segment."""
    if is_last:
        cur[key] = value
        return None
    expected_type = list if next_is_index else dict
    nxt: Any = cur.get(key)
    if not isinstance(nxt, expected_type):
        new_val: Any = [] if next_is_index else {}
        cur[key] = new_val
        return new_val
    return cast("Any", nxt)


def _step_list(
    cur: list[Any],
    idx: int,
    *,
    is_last: bool,
    next_is_index: bool,
    value: Any,
) -> Any:
    """Advance or write a list index segment, padding missing elements."""
    default_pad: Any = (
        False
        if is_last and isinstance(value, bool)
        else (None if is_last else ([] if next_is_index else {}))
    )
    while len(cur) <= idx:
        cur.append(copy.deepcopy(default_pad))
    if is_last:
        cur[idx] = value
        return None
    expected_type = list if next_is_index else dict
    if not isinstance(cur[idx], expected_type):
        cur[idx] = [] if next_is_index else {}
    return cur[idx]


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    """Write ``value`` into ``root`` at a flattened ``path`` like ``a.b[2].c``."""
    tokens = _parse_flat_path(path)
    if not tokens or tokens[0][0] is None:
        return

    cur: Any = root
    for i, (key, idx) in enumerate(tokens):
        is_last = i == len(tokens) - 1
        next_is_index = not is_last and tokens[i + 1][1] is not None
        if key is not None and isinstance(cur, dict):
            cur = _step_dict(
                cast("dict[str, Any]", cur),
                key,
                is_last=is_last,
                next_is_index=next_is_index,
                value=value,
            )
        elif idx is not None and isinstance(cur, list):
            cur = _step_list(
                cast("list[Any]", cur),  # type: ignore[redundant-cast]  # needed by pyright strict
                idx,
                is_last=is_last,
                next_is_index=next_is_index,
                value=value,
            )
        else:
            return
        if cur is None:
            return


def deep_merge(base: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
    """
    Return a new dict with ``delta`` deep-merged onto ``base``.

    Nested dicts merge recursively; any non-dict value (including lists) in
    ``delta`` replaces the corresponding value in ``base`` wholesale. Inputs
    are not mutated.
    """
    result: dict[str, Any] = dict(base)
    for key, delta_value in delta.items():
        base_value = result.get(key)
        if isinstance(base_value, dict) and isinstance(delta_value, dict):
            result[key] = deep_merge(
                cast("dict[str, Any]", base_value),
                cast("dict[str, Any]", delta_value),
            )
        else:
            result[key] = delta_value
    return result
