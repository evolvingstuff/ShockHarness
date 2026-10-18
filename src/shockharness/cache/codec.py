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
import functools
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


# Where a value sits in the entry, for an error message: the root's name, or a pair
# (parent, ".field"). A pair costs nothing to build; it is rendered only on an error.
Where = str | tuple[Any, str]
Decoder = Callable[[Any, Any], Any]


def _render(where: Where) -> str:
    parts: list[str] = []
    node: Any = where
    while isinstance(node, tuple):
        parent, part = node
        parts.append(part)
        node = parent
    parts.append(node)
    return "".join(reversed(parts))


@functools.cache
def _hints(cls: type) -> dict[str, Any]:
    return typing.get_type_hints(cls)


def from_plain(hint: Any, data: Any, where: str) -> Any:
    """Rebuild a value of type ``hint`` from ``data``; strict about shape and types."""
    return _decoder(hint)(data, where)


@functools.cache
def _decoder(hint: Any) -> Decoder:
    """The decoder for one type hint, built once: the hints are read when the decoder is
    built, never per value."""
    if hint is ControlNode:
        return _control_from_plain
    if isinstance(hint, type) and dataclasses.is_dataclass(hint):
        return _dataclass_decoder(hint)
    origin = typing.get_origin(hint)
    if origin is types.UnionType or origin is typing.Union:
        return _union_decoder(typing.get_args(hint))
    if origin is tuple:
        return _tuple_decoder(typing.get_args(hint))
    if origin is frozenset:
        (item_hint,) = typing.get_args(hint)
        return _frozenset_decoder(_decoder(item_hint))
    if hint not in _SCALAR_CHECKERS:
        # The model's own types are fixed: a hint no decoder handles is a bug in the
        # tool, not a malformed entry.
        raise TypeError(f"the cache codec has no decoder for {hint!r}")
    return _SCALAR_CHECKERS[hint]


def _control_from_plain(data: Any, where: Where) -> ControlNode:
    if not isinstance(data, dict) or set(data) != {CONTROL_KEY}:
        raise CacheEntryError(f"{_render(where)}: expected a control tree")
    return _rebuild_control(data[CONTROL_KEY], _render(where))


def _frozenset_decoder(item: Decoder) -> Decoder:
    def decode(data: Any, where: Where) -> frozenset[Any]:
        if not isinstance(data, list):
            raise CacheEntryError(f"{_render(where)}: expected a list")
        return frozenset(item(value, where) for value in data)

    return decode


def _check_bool(data: Any, where: Where) -> bool:
    if not isinstance(data, bool):
        raise CacheEntryError(f"{_render(where)}: expected a boolean")
    return data


def _check_int(data: Any, where: Where) -> int:
    if not _is_int(data):
        raise CacheEntryError(f"{_render(where)}: expected an integer")
    return data


def _check_float(data: Any, where: Where) -> float:
    if isinstance(data, bool) or not isinstance(data, int | float):
        raise CacheEntryError(f"{_render(where)}: expected a number")
    return float(data)


def _check_str(data: Any, where: Where) -> str:
    if not isinstance(data, str):
        raise CacheEntryError(f"{_render(where)}: expected a string")
    return data


def _check_none(data: Any, where: Where) -> None:
    if data is not None:
        raise CacheEntryError(f"{_render(where)}: expected null")
    return None


def _check_complex(data: Any, where: Where) -> complex:
    if not isinstance(data, dict) or set(data) != {COMPLEX_KEY}:
        raise CacheEntryError(f"{_render(where)}: expected a complex number")
    parts = data[COMPLEX_KEY]
    if not isinstance(parts, list) or len(parts) != 1 + 1:
        raise CacheEntryError(f"{_render(where)}: expected a complex number")
    return complex(_check_float(parts[0], where), _check_float(parts[1], where))


_SCALAR_CHECKERS: dict[Any, Decoder] = {
    bool: _check_bool,
    int: _check_int,
    float: _check_float,
    str: _check_str,
    type(None): _check_none,
    complex: _check_complex,
}


def _dataclass_decoder(cls: type) -> Decoder:
    hints = _hints(cls)
    names = tuple(f.name for f in dataclasses.fields(cls))
    expected = frozenset(names)
    fields = tuple((name, "." + name, _decoder(hints[name])) for name in names)

    def decode(data: Any, where: Where) -> Any:
        if not isinstance(data, dict):
            raise CacheEntryError(f"{_render(where)}: expected an object for {cls.__name__}")
        if data.keys() != expected:
            raise CacheEntryError(f"{_render(where)}: fields of {cls.__name__} do not match")
        return cls(**{name: field(data[name], (where, part)) for name, part, field in fields})

    return decode


def _union_decoder(members: tuple[Any, ...]) -> Decoder:
    """The unions of the model are ``X | None`` and ``int | float | complex``: the JSON
    shape of ``data`` selects the member, so no member is tried speculatively."""
    choices = tuple((member, _decoder(member)) for member in members)

    def decode(data: Any, where: Where) -> Any:
        for member, member_decoder in choices:
            if _shape_matches(member, data):
                return member_decoder(data, where)
        raise CacheEntryError(f"{_render(where)}: no member of the union accepts the value")

    return decode


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


def _tuple_decoder(args: tuple[Any, ...]) -> Decoder:
    if len(args) == 1 + 1 and args[1] is Ellipsis:
        item = _decoder(args[0])

        def decode_all(data: Any, where: Where) -> tuple[Any, ...]:
            if not isinstance(data, list):
                raise CacheEntryError(f"{_render(where)}: expected a list")
            return tuple(item(value, where) for value in data)

        return decode_all
    positions = tuple(_decoder(arg) for arg in args)

    def decode_fixed(data: Any, where: Where) -> tuple[Any, ...]:
        if not isinstance(data, list):
            raise CacheEntryError(f"{_render(where)}: expected a list")
        if len(data) != len(positions):
            raise CacheEntryError(f"{_render(where)}: expected {len(positions)} items")
        return tuple(d(value, where) for d, value in zip(positions, data, strict=True))

    return decode_fixed
