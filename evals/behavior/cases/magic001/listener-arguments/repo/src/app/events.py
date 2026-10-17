"""Listeners registered from a registration: (event name, handler, *options)."""

from collections.abc import Callable, Sequence

Handler = Callable[[str], None]


def register(registry: dict[str, list[Handler]], registration: Sequence[object]) -> None:
    if len(registration) < 2:
        raise ValueError("a registration needs an event name and a handler")
    event, handler = registration[0], registration[1]
    if not isinstance(event, str) or not callable(handler):
        raise TypeError("a registration is (event name, handler, *options)")
    if event not in registry:
        registry[event] = []
    registry[event].append(handler)
