"""One HTTP GET of a feed; a server that does not answer raises FeedUnreachable."""

from __future__ import annotations

import http.client
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus

REQUEST_HEADERS = {"Accept": "application/json", "User-Agent": "feedcheck"}


class FeedUnreachable(Exception):
    """The server did not answer: no connection, a timeout, or a broken response."""

    def __init__(self, url: str, reason: str) -> None:
        super().__init__(f"{url}: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class _StatusPassthrough(urllib.request.HTTPErrorProcessor):
    """Return every final response, whatever its status; redirects are still followed."""

    def http_response(self, request: urllib.request.Request, response: http.client.HTTPResponse) -> http.client.HTTPResponse:
        if HTTPStatus.MULTIPLE_CHOICES <= response.status < HTTPStatus.BAD_REQUEST:
            return super().http_response(request, response)
        return response

    https_response = http_response


def build_opener() -> urllib.request.OpenerDirector:
    """An opener whose responses carry their status instead of raising HTTPError."""
    return urllib.request.build_opener(_StatusPassthrough)


def fetch_once(opener: urllib.request.OpenerDirector, url: str, timeout_seconds: float) -> Response:
    request = urllib.request.Request(url, headers=REQUEST_HEADERS)
    # Boundary (declared in .shockharness.toml): one network call.
    try:
        response = opener.open(request, timeout=timeout_seconds)
    except OSError as exc:
        raise FeedUnreachable(url, _describe(exc)) from exc
    with response:
        status = response.status
        body = _read_body(url, response)
    return Response(status=status, body=body)


def _read_body(url: str, response: http.client.HTTPResponse) -> bytes:
    # Boundary (declared in .shockharness.toml): one network read.
    try:
        body = response.read()
    except (OSError, http.client.HTTPException) as exc:
        raise FeedUnreachable(url, _describe(exc)) from exc
    return body


def _describe(exc: BaseException) -> str:
    detail: object = exc
    if isinstance(exc, urllib.error.URLError):
        detail = exc.reason
    if isinstance(detail, BaseException):
        return f"{type(detail).__name__}: {detail}"
    return str(detail)
