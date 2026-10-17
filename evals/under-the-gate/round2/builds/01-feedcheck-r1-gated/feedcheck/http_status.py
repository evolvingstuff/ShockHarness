"""HTTP status classes used to decide whether a feed answered and whether to retry."""

from http import HTTPStatus

# RFC 9110 section 15: the first digit of a status code defines its class; 5xx is the
# server error class and ends below 600.
SERVER_ERROR_FIRST = HTTPStatus.INTERNAL_SERVER_ERROR
SERVER_ERROR_END = 600  # shockharness: ignore[MAGIC001] reason="RFC 9110 section 15: status codes are three digits; the 5xx class ends below 600"


def is_server_error(status: int) -> bool:
    return SERVER_ERROR_FIRST <= status < SERVER_ERROR_END
