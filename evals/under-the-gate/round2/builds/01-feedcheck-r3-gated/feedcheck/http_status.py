"""HTTP status codes feedcheck interprets, with their sources."""

OK = 200  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.3.1, 200 OK"
REDIRECT_FIRST = 300  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.4, 3xx Redirection class"
REDIRECT_LAST = 399  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.4, 3xx Redirection class"
SERVER_ERROR_FIRST = 500  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.6, 5xx Server Error class"
SERVER_ERROR_LAST = 599  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15.6, 5xx Server Error class"


def is_redirect(status: int) -> bool:
    return REDIRECT_FIRST <= status <= REDIRECT_LAST


def is_server_error(status: int) -> bool:
    return SERVER_ERROR_FIRST <= status <= SERVER_ERROR_LAST
