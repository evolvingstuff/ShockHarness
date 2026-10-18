import re

from app.contracts import produces


def redact(text):
    return produces(re.sub("@", "[at]", text), "redacted")


def careless(text):
    return produces(text, "redacted")


def maybe(text, flag):
    if flag:
        return redact(text)
    return text
