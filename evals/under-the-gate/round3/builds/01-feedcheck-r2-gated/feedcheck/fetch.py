"""Fetch one feed over HTTP: an answer with any status, or no answer at all."""

import http.client
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus

# Redirects are still followed; every other status is answered to the caller.
REDIRECT_STATUSES = frozenset(
    {
        HTTPStatus.MOVED_PERMANENTLY,
        HTTPStatus.FOUND,
        HTTPStatus.SEE_OTHER,
        HTTPStatus.TEMPORARY_REDIRECT,
        HTTPStatus.PERMANENT_REDIRECT,
    }
)


@dataclass(frozen=True)
class Answer:
    """The server answered with `status`; `body` is the full response body."""

    status: int
    body: bytes


@dataclass(frozen=True)
class NoAnswer:
    """The server did not answer (refused, timed out, broke the connection)."""

    reason: str


class _AnswerEveryStatus(urllib.request.HTTPErrorProcessor):
    """Return non-2xx responses instead of raising HTTPError, except redirects."""

    def http_response(
        self, request: urllib.request.Request, response: http.client.HTTPResponse
    ) -> http.client.HTTPResponse:
        if response.status in REDIRECT_STATUSES:
            return super().http_response(request, response)
        return response

    https_response = http_response


_OPENER = urllib.request.build_opener(_AnswerEveryStatus)


def fetch_once(url: str, timeout_seconds: float) -> Answer | NoAnswer:
    """Make one request; a failure to get an answer is a NoAnswer, never a raise."""
    # Boundary (declared in .shockharness.toml): one network exchange.
    try:
        answer = _download(url, timeout_seconds)
    except (OSError, http.client.HTTPException) as exc:
        return NoAnswer(reason=_describe(exc))
    return answer


def _download(url: str, timeout_seconds: float) -> Answer:
    with _OPENER.open(url, timeout=timeout_seconds) as response:
        return Answer(status=response.status, body=response.read())


def _describe(exc: BaseException) -> str:
    text = str(exc)
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__
