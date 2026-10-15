"""JSON codec for the frozen dataclasses of the per-file phase.

Cache entries are plain JSON, never pickles: nothing read from a cache directory
is ever executed. Encoding walks a dataclass's fields; decoding is driven by the
dataclass's type hints and is strict: a missing or unknown field, a wrong type, or
an inconsistent control tree raises :class:`CacheEntryError`, which the store turns
into "entry ignored, file analyzed afresh". Control trees (the one recursive
structure) are flattened to a pre-order list and rebuilt with an explicit stack,
so a deeply nested unit cannot exhaust the recursion limit.
"""

import dataclasses
import types
import typing
from collections.abc import Callable
from typing import Any

from shockharness.constants import CACHE_CONTROL_FIELDS
from shockharness.ir.model import ControlNode

COMPLEX_KEY = "__complex__"
CONTROL_KEY = "__control__"


class CacheEntryError(Exception):
    """A cache entry does not have the shape the current tool expects."""


def _flatten_control(root: ControlNode) -> list[list[Any]]:
    flat: list[list[Any]] = []
    stack: list[ControlNode] = [root]
    while len(stack) > 0:
        node = stack.pop()
        flat.append(
            [
                node.kind,
                len(node.children),
                node.operators,
                node.sequences,
                node.label,
                node.labeled,
            ]
        )
        stack.extend(reversed(node.children))
    return flat


def _rebuild_control(flat: Any, where: str) -> ControlNode:
    if not isinstance(flat, list) or len(flat) == 0:
        raise CacheEntryError(f"{where}: control tree must be a non-empty list")
    stack: list[ControlNode] = []
    for entry in reversed(flat):
        if not isinstance(entry, list) or len(entry) != CACHE_CONTROL_FIELDS:
            raise CacheEntryError(f"{where}: malformed control tree entry")
        kind, count, operators, sequences, label, labeled = entry
        if not (
            isinstance(kind, str)
            and _is_int(count)
            and _is_int(operators)
            and _is_int(sequences)
            and isinstance(label, str)
            and isinstance(labeled, bool)
        ):
            raise CacheEntryError(f"{where}: malformed control tree entry")
        if count < 0 or count > len(stack):
            raise CacheEntryError(f"{where}: inconsistent control tree")
        children = tuple(stack.pop() for _ in range(count))
        stack.append(ControlNode(kind, children, operators, sequences, label, labeled))
    if len(stack) != 1:
        raise CacheEntryError(f"{where}: inconsistent control tree")
    return stack[0]


def to_plain(value: Any) -> Any:
    """A JSON-ready structure for a dataclass instance or a JSON-compatible value."""
    if isinstance(value, ControlNode):
        return {CONTROL_KEY: _flatten_control(value)}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, complex):
        return {COMPLEX_KEY: [value.real, value.imag]}
    if isinstance(value, tuple | list):
        return [to_plain(item) for item in value]
    if isinstance(value, frozenset | set):
        return sorted(to_plain(item) for item in value)
    raise TypeError(f"cannot encode {type(value).__name__} for the cache")


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


_HINTS: dict[type, dict[str, Any]] = {}


def _hints(cls: type) -> dict[str, Any]:
    if cls not in _HINTS:
        _HINTS[cls] = typing.get_type_hints(cls)
    return _HINTS[cls]


def from_plain(hint: Any, data: Any, where: str) -> Any:
    """Rebuild a value of type ``hint`` from ``data``; strict about shape and types."""
    if hint is ControlNode:
        if not isinstance(data, dict) or set(data) != {CONTROL_KEY}:
            raise CacheEntryError(f"{where}: expected a control tree")
        return _rebuild_control(data[CONTROL_KEY], where)
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        return _dataclass_from_plain(hint, data, where)
    origin = typing.get_origin(hint)
    if origin is types.UnionType or origin is typing.Union:
        return _union_from_plain(typing.get_args(hint), data, where)
    if origin is tuple:
        return _tuple_from_plain(typing.get_args(hint), data, where)
    if origin is frozenset:
        (item_hint,) = typing.get_args(hint)
        if not isinstance(data, list):
            raise CacheEntryError(f"{where}: expected a list")
        return frozenset(from_plain(item_hint, item, where) for item in data)
    if hint in _SCALAR_CHECKERS:
        return _SCALAR_CHECKERS[hint](data, where)
    raise CacheEntryError(f"{where}: unsupported type {hint!r}")


def _check_bool(data: Any, where: str) -> bool:
    if not isinstance(data, bool):
        raise CacheEntryError(f"{where}: expected a boolean")
    return data


def _check_int(data: Any, where: str) -> int:
    if not _is_int(data):
        raise CacheEntryError(f"{where}: expected an integer")
    return data


def _check_float(data: Any, where: str) -> float:
    if isinstance(data, bool) or not isinstance(data, int | float):
        raise CacheEntryError(f"{where}: expected a number")
    return float(data)


def _check_str(data: Any, where: str) -> str:
    if not isinstance(data, str):
        raise CacheEntryError(f"{where}: expected a string")
    return data


def _check_none(data: Any, where: str) -> None:
    if data is not None:
        raise CacheEntryError(f"{where}: expected null")
    return None


def _check_complex(data: Any, where: str) -> complex:
    if not isinstance(data, dict) or set(data) != {COMPLEX_KEY}:
        raise CacheEntryError(f"{where}: expected a complex number")
    parts = data[COMPLEX_KEY]
    if not isinstance(parts, list) or len(parts) != 1 + 1:
        raise CacheEntryError(f"{where}: expected a complex number")
    return complex(_check_float(parts[0], where), _check_float(parts[1], where))


_SCALAR_CHECKERS: dict[Any, Callable[[Any, str], Any]] = {
    bool: _check_bool,
    int: _check_int,
    float: _check_float,
    str: _check_str,
    type(None): _check_none,
    complex: _check_complex,
}


def _dataclass_from_plain(cls: type, data: Any, where: str) -> Any:
    if not isinstance(data, dict):
        raise CacheEntryError(f"{where}: expected an object for {cls.__name__}")
    hints = _hints(cls)
    names = [f.name for f in dataclasses.fields(cls)]
    if set(data) != set(names):
        raise CacheEntryError(f"{where}: fields of {cls.__name__} do not match")
    values = {name: from_plain(hints[name], data[name], f"{where}.{name}") for name in names}
    return cls(**values)


def _union_from_plain(members: tuple[Any, ...], data: Any, where: str) -> Any:
    """The unions of the model are ``X | None`` and ``int | float | complex``: the JSON
    shape of ``data`` selects the member, so no member is tried speculatively."""
    for member in members:
        if _shape_matches(member, data):
            return from_plain(member, data, where)
    raise CacheEntryError(f"{where}: no member of the union accepts the value")


def _shape_matches(member: Any, data: Any) -> bool:
    if member is type(None):
        return data is None
    if member is bool:
        return isinstance(data, bool)
    if member is int:
        return _is_int(data)
    if member is float:
        return isinstance(data, float)
    if member is str:
        return isinstance(data, str)
    if member is complex:
        return isinstance(data, dict) and COMPLEX_KEY in data
    if isinstance(member, type) and dataclasses.is_dataclass(member):
        return isinstance(data, dict) and COMPLEX_KEY not in data
    return isinstance(data, list)


def _tuple_from_plain(args: tuple[Any, ...], data: Any, where: str) -> tuple[Any, ...]:
    if not isinstance(data, list):
        raise CacheEntryError(f"{where}: expected a list")
    if len(args) == 1 + 1 and args[1] is Ellipsis:
        return tuple(from_plain(args[0], item, where) for item in data)
    if len(data) != len(args):
        raise CacheEntryError(f"{where}: expected {len(args)} items")
    return tuple(from_plain(arg, item, where) for arg, item in zip(args, data, strict=True))
