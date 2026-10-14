# Expected with a boundary for OSError on this file.
import json


def narrow(path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ReadFailed(path) from exc
    return json.loads(raw)


def two_statements(path):
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except OSError as exc:
        raise ReadFailed(path) from exc
    return data


def with_block(path):
    try:
        with open(path) as handle:
            raw = handle.read()
    except OSError as exc:
        raise ReadFailed(path) from exc
    return raw


def subscript(table, key):
    try:
        value = table[key]
    except OSError as exc:
        raise ReadFailed(key) from exc
    return value


def comprehension(paths):
    try:
        raws = [p.read_bytes() for p in paths]
    except OSError as exc:
        raise ReadFailed(paths) from exc
    return raws


def optional_import():
    try:
        import optional_dependency
    except OSError as exc:
        raise ReadFailed("import") from exc
    return optional_dependency


async def awaited(client, url):
    try:
        response = await client.get(url)
    except OSError as exc:
        raise ReadFailed(url) from exc
    return response
