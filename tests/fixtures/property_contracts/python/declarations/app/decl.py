from app.contracts import produces, requires

PROPERTY = "redacted"


def typo(text):
    requires(text, "redcated")
    return text


def computed(text):
    requires(text, PROPERTY)
    return produces(text)


def keyword(text):
    return produces(text, "redacted", strict=True)


def late(text):
    size = len(text)
    requires(text, "redacted")
    return size


def branch(text, flag):
    if flag:
        requires(text, "redacted")
    return text


def rebound(text):
    text = text + "!"
    requires(text, "redacted")
    return text

