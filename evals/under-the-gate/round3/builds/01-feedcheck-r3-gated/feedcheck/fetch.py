"""Fetch a feed over HTTP, retrying when the server answers 5xx or does not answer."""

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus


@dataclass(frozen=True)
class Answer:
    """The server answered with `status`; `body` is the response body."""

    status: int
    body: bytes


@dataclass(frozen=True)
class NoAnswer:
    """The server did not answer (connection failure, timeout, broken response)."""

    reason: str


class _KeepErrorStatus(urllib.request.HTTPErrorProcessor):
    """Hand every response back as-is so the status is judged by the caller, not raised."""

    def http_response(self, request: urllib.request.Request, response: http.client.HTTPResponse) -> http.client.HTTPResponse:
        return response

    https_response = http_response


_OPENER = urllib.request.build_opener(_KeepErrorStatus())


def fetch_once(url: str, timeout_seconds: float) -> Answer | NoAnswer:
    """Make one request; a failure to get a complete answer is a NoAnswer."""
    # Boundary (declared in .shockharness.toml): one network call.
    try:
        response = _OPENER.open(url, timeout=timeout_seconds)
    except OSError as exc:
        return NoAnswer(reason=_describe(exc))
    except http.client.HTTPException as exc:
        return NoAnswer(reason=_describe(exc))
    with response:
        # Boundary (declared in .shockharness.toml): reading the body from the network.
        try:
            body = response.read()
        except OSError as exc:
            return NoAnswer(reason=_describe(exc))
        except http.client.HTTPException as exc:
            return NoAnswer(reason=_describe(exc))
    return Answer(status=response.status, body=body)


def fetch_with_retries(
    url: str,
    timeout_seconds: float,
    attempts: int,
    retry_delay_seconds: float,
    sleep: Callable[[float], None],
) -> Answer | NoAnswer:
    """Fetch `url` up to `attempts` times; retry number n waits n * retry_delay_seconds first."""
    if attempts < 1:
        raise ValueError(f"attempts must be at least 1, got {attempts}")
    outcome = fetch_once(url, timeout_seconds)
    for retry in range(1, attempts):
        if not _should_retry(outcome):
            break
        sleep(retry_delay_seconds * retry)
        outcome = fetch_once(url, timeout_seconds)
    return outcome


def _should_retry(outcome: Answer | NoAnswer) -> bool:
    if isinstance(outcome, NoAnswer):
        return True
    return outcome.status >= HTTPStatus.INTERNAL_SERVER_ERROR


def _describe(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return f"{type(exc).__name__}: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"
