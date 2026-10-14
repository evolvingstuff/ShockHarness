import json


def bare_reraise(raw):
    try:
        return json.loads(raw)
    except ValueError:
        raise


def reraise_bound(raw):
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise exc


def chained(raw):
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ConfigError("bad json") from exc


def unchained(raw):
    try:
        return json.loads(raw)
    except ValueError:
        raise ConfigError("bad json")


def from_none(raw):
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ConfigError("bad json") from None


def log_then_reraise(raw):
    try:
        return json.loads(raw)
    except ValueError as exc:
        print("bad json", exc)
        raise
