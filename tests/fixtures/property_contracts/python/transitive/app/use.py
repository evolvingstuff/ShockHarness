from app.contracts import requires
from app.wrappers import looping, thrice, twice, wrapped


def deliver(text):
    requires(text, "redacted")
    return text


def one(raw):
    return deliver(wrapped(raw))


def two(raw):
    return deliver(twice(raw))


def three(raw):
    return deliver(thrice(raw))


def recursive(raw):
    return deliver(looping(raw, 1))
