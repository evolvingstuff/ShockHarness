import html

from app.contracts import produces


def escape(text):
    return produces(html.escape(text), "escaped_html")


def sanitize(markup):
    return produces(html.escape(markup, quote=False), "sanitized_html")


def header_value(text):
    return produces(text.replace("\r", "").replace("\n", ""), "header_safe")
