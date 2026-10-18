from app.text import redact


def wrapped(text):
    return redact(text)


def twice(text):
    return wrapped(text)


def thrice(text):
    return twice(text)


def looping(text, n):
    if n > 0:
        return looping(text, n)
    return redact(text)
