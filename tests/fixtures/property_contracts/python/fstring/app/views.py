from app.markup import escape, header_value, sanitize
from app.page import send_html


def empty():
    return send_html("")


def escaped(tag):
    return send_html(f"<b>{escape(tag)}</b>")


def sanitized(raw):
    return send_html(sanitize(raw))


def interpolated(tag):
    return send_html(f"<b>{tag}</b>")


def mixed(tag, raw):
    return send_html(f"<b>{tag}</b>" + sanitize(raw))


def joined(items):
    return send_html("".join(f"<li>{escape(i)}</li>" for i in items))


def formatted(tag, raw):
    send_html("<b>{}</b>".format(escape(tag)))
    send_html("<b>%s</b>" % raw)


def respond(response, tag):
    response.body = f"<p>{escape(tag)}</p>"
    response.body = f"<p>{tag}</p>"


def headers_out(response, name, raw):
    response.headers[name] = header_value(raw)
    response.headers[name] = raw
    response.headers[name] += raw


def joined_raw(items):
    return send_html("".join(f"<li>{i}</li>" for i in items))


PREFIX = "    "


def indented(raw):
    return send_html("\n".join(PREFIX + line for line in sanitize(raw).splitlines()))


def listed(raw, tag):
    return send_html("".join([sanitize(raw), f"<b>{escape(tag)}</b>"]))
