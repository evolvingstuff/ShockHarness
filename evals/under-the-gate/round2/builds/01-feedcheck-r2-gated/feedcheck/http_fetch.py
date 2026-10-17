"""Fetch a feed over HTTP, retrying server errors and network failures."""

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus

from feedcheck.config import RetryPolicy

FIRST_ATTEMPT = 0


@dataclass(frozen=True)
class Answer:
    """The server answered with ``status`` and ``body``."""

    status: int
    body: bytes
    attempts: int


@dataclass(frozen=True)
class NoAnswer:
    """The server did not answer at all; ``reason`` says what went wrong."""

    reason: str
    attempts: int


class _KeepErrorStatus(urllib.request.HTTPErrorProcessor):
    """Hand 4xx and 5xx responses back as responses; keep following redirects."""

    def http_response(
        self, request: urllib.request.Request, response: http.client.HTTPResponse
    ) -> http.client.HTTPResponse:
        if HTTPStatus.MULTIPLE_CHOICES <= response.status < HTTPStatus.BAD_REQUEST:
            return super().http_response(request, response)
        return response

    https_response = http_response


def is_server_error(status: int) -> bool:
    return status >= HTTPStatus.INTERNAL_SERVER_ERROR


def fetch(url: str, retry: RetryPolicy, sleep: Callable[[float], None]) -> Answer | NoAnswer:
    """Fetch ``url``, retrying a 5xx answer or no answer up to ``retry.attempts`` times.

    Attempt ``n`` (counting from 0) first sleeps ``n * retry.retry_delay_seconds``.
    Returns the outcome of the last attempt made.
    """
    opener = urllib.request.build_opener(_KeepErrorStatus)
    last_attempt = retry.attempts - 1
    for attempt in range(retry.attempts):
        if attempt > FIRST_ATTEMPT:
            sleep(retry.retry_delay_seconds * attempt)
        outcome = _fetch_once(opener, url, retry.timeout_seconds, attempt + 1)
        if attempt == last_attempt:
            return outcome
        if isinstance(outcome, Answer) and not is_server_error(outcome.status):
            return outcome
    raise AssertionError("the retry loop always returns on its last attempt")


def _fetch_once(
    opener: urllib.request.OpenerDirector, url: str, timeout_seconds: float, attempts: int
) -> Answer | NoAnswer:
    # Boundary (declared in .shockharness.toml): one network exchange. A failure
    # becomes a NoAnswer that names it; the caller must handle that outcome.
    try:
        status, body = _download(opener, url, timeout_seconds)
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as exc:
        return NoAnswer(reason=_describe(exc), attempts=attempts)
    return Answer(status=status, body=body, attempts=attempts)


def _download(
    opener: urllib.request.OpenerDirector, url: str, timeout_seconds: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=timeout_seconds) as response:
        return response.status, response.read()


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return f"no answer: {exc.reason}"
    if isinstance(exc, TimeoutError):
        return "no answer: timed out"
    return f"no answer: {type(exc).__name__}: {exc}"
