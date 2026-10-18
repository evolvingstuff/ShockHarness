from app.contracts import preserves, preserves_except, requires
from app.text import redact


def deliver(text):
    requires(text, "redacted")
    return text


def preserved(raw):
    cleaned = redact(raw)
    copy = preserves(cleaned.strip(), cleaned)
    return deliver(copy)


def preserved_except(raw):
    cleaned = redact(raw)
    other = preserves_except(cleaned.strip(), cleaned, "redacted")
    return deliver(other)


def one_branch(raw, flag):
    value = raw
    if flag:
        value = redact(raw)
    return deliver(value)


def both_branches(raw, flag):
    if flag:
        value = redact(raw)
    else:
        value = redact(raw.lower())
    return deliver(value)


def every_iteration(raw, parts):
    value = redact(raw)
    for part in parts:
        value = redact(value + part)
    return deliver(value)


def not_before_loop(raw, parts):
    value = raw
    for part in parts:
        value = redact(part)
    return deliver(value)


def mid_body(raw):
    value = redact(raw)
    requires(value, "redacted")
    plain = value + "!"
    requires(plain, "redacted")
    return plain


def handler(raw):
    value = raw
    try:
        value = redact(raw)
        deliver(value)
    except ValueError:
        return deliver(value)
    return value


def method_call(raw, service):
    return deliver(service.redact(raw))
