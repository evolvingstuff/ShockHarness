"""DEF002: mapping and attribute fallbacks, and the implicit None of .get(key)."""

from collections import defaultdict
from collections.abc import Mapping

CONFIG = {"timeout": 1}
counts = defaultdict(int)


def known_mapping(options: dict, extra: Mapping):
    timeout = CONFIG.get("timeout", 30)
    retries = options.get("retries", 3)
    mode = extra.get("mode")
    counts.setdefault("hits", 0)
    return timeout, retries, mode


def unknown_receiver(payload, client, url):
    items = payload.get("items", [])
    name = payload.get("name")
    user = payload.get(url)
    response = client.get(url)
    return items, name, user, response


def attributes(obj):
    retries = getattr(obj, "retries", 3)
    present = getattr(obj, "retries")
    return retries, present


def pops(stack, table, key):
    top = stack.pop()
    first = stack.pop(0)
    value = table.pop(key, None)
    return top, first, value


def spelled_out(table, key):
    value = table[key] if key in table else "missing"
    other = "missing" if key not in table else table[key]
    strict = table[key]
    return value, other, strict


def handled_none(table):
    raw = table.get("raw")
    if raw is None:
        raise KeyError("raw")
    checked = table.get("checked") is not None
    return raw, checked


async def awaited(client, url):
    return await client.get(url)
