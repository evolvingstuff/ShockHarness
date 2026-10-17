"""Fetch a feed over HTTP, retrying when the server answers 5xx or does not answer."""

import http.client
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus

from feedcheck.http_status import is_server_error


@dataclass(frozen=True)
class Answer:
    """The server answered with a status; body holds the payload of a 200 answer only."""

    status: int
    body: bytes


@dataclass(frozen=True)
class NoAnswer:
    """The server could not be reached or did not answer in time."""

    reason: str


@dataclass(frozen=True)
class RetryPolicy:
    timeout_seconds: float
    attempts: int
    retry_backoff_seconds: float


def fetch(url: str, policy: RetryPolicy, sleep: Callable[[float], None]) -> Answer | NoAnswer:
    """Fetch url up to policy.attempts times; attempt n + 1 first waits n * retry_backoff_seconds."""
    outcome = fetch_once(url, policy.timeout_seconds)
    for retry in range(1, policy.attempts):
        if not _should_retry(outcome):
            return outcome
        sleep(policy.retry_backoff_seconds * retry)
        outcome = fetch_once(url, policy.timeout_seconds)
    return outcome


def fetch_once(url: str, timeout_seconds: float) -> Answer | NoAnswer:
    opened = _open(url, timeout_seconds)
    if not isinstance(opened, http.client.HTTPResponse):
        return opened
    with opened as response:
        if response.status != HTTPStatus.OK:
            return Answer(status=response.status, body=b"")
        body = _read(response)
    if isinstance(body, NoAnswer):
        return body
    return Answer(status=HTTPStatus.OK, body=body)


def _should_retry(outcome: Answer | NoAnswer) -> bool:
    return isinstance(outcome, NoAnswer) or is_server_error(outcome.status)


def _open(url: str, timeout_seconds: float) -> http.client.HTTPResponse | Answer | NoAnswer:
    # Boundary (declared in .shockharness.toml): one network request. A non-2xx answer
    # arrives as HTTPError and becomes an Answer with its status; a failure to answer
    # becomes a NoAnswer carrying the reason.
    try:
        response = urllib.request.urlopen(url, timeout=timeout_seconds)
    except urllib.error.HTTPError as exc:
        exc.close()
        return Answer(status=exc.code, body=b"")
    except (OSError, http.client.HTTPException) as exc:
        return NoAnswer(reason=_describe(exc))
    return response


def _read(response: http.client.HTTPResponse) -> bytes | NoAnswer:
    # Boundary (declared in .shockharness.toml): one network read.
    try:
        body = response.read()
    except (OSError, http.client.HTTPException) as exc:
        return NoAnswer(reason=_describe(exc))
    return body


def _describe(exc: OSError | http.client.HTTPException) -> str:
    if isinstance(exc, urllib.error.URLError):
        return f"no answer: {exc.reason}"
    return f"no answer: {type(exc).__name__}: {exc}"
