import html

from contracts_runtime import produces, requires


def deliver(text):
    requires(text, "redacted")
    return text


def redact(text):
    return produces(html.escape(text), "redacted")


async def fetch_redacted(text):
    return redact(text)


def chunks(texts):
    for text in texts:
        yield redact(text)


async def awaited(raw):
    value = await fetch_redacted(raw)
    return deliver(value)


def generated(raw):
    for chunk in chunks([raw]):
        deliver(chunk)


def consumed(raw):
    return deliver(list(chunks([raw])))


def expression(raw):
    return deliver(sorted(redact(t) for t in [raw]))


async def asynchronous_for(source):
    async for item in source:
        deliver(item)


def joined(parts):
    return deliver("".join(redact(p) for p in parts))


def destroyed(raw):
    return deliver(html.escape(raw))
