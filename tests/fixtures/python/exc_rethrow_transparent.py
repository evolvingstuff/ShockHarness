# Expected with rules.exceptions.transparent_rethrow = true.
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


def chained_is_not_transparent(raw):
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ConfigError("bad json") from exc


def bare_except_that_reraises_is_transparent(raw):
    try:
        return json.loads(raw)
    except:
        raise
