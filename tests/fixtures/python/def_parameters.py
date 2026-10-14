"""DEF001: parameter defaults. Every default value is a finding; *args/**kwargs are not."""

from abc import abstractmethod
from typing import overload


def plain(a, b=1, c="x"):
    return a, b, c


def keyword_only(a, *, retries=3, verbose=False):
    return a, retries, verbose


def none_default(path, encoding=None):
    return path, encoding


def variadic(*args, **kwargs):
    return args, kwargs


def positional_only(a, b, /, c=()):
    return a, b, c


async def coroutine(url, timeout=DEFAULT_TIMEOUT):
    return url, timeout


square = lambda x, power=2: x**power  # noqa: E731


class Service:
    def __init__(self, client, cache=None):
        self.client = client
        self.cache = cache

    @abstractmethod
    def run(self, mode="fast"):
        raise NotImplementedError

    def nested(self):
        def inner(value, scale=1.5):
            return value * scale

        return inner


@overload
def read(path: str, binary: bool = ...) -> str: ...


def read(path, binary):
    return path, binary


def required_only(host, port, timeout):
    return host, port, timeout
