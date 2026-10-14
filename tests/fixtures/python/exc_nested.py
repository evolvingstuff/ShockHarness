import json


def nested(path):
    try:
        raw = read(path)
    except OSError as exc:
        try:
            raw = read_fallback(path)
        except OSError:
            return None
        print(exc)
    return json.loads(raw)


def finally_only(path):
    try:
        return read(path)
    finally:
        cleanup(path)


def with_else(path):
    try:
        raw = read(path)
    except OSError as exc:
        raise Failed(path) from exc
    else:
        return json.loads(raw)
