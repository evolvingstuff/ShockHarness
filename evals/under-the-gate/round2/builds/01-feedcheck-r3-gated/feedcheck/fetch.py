"""One HTTP GET of a feed, as an answer or as the reason no answer came."""

import http.client
import urllib.error
import urllib.request
from dataclasses import dataclass

from feedcheck import http_status


@dataclass(frozen=True)
class Answer:
    status: int
    body: bytes


@dataclass(frozen=True)
class NoAnswer:
    reason: str


class _KeepErrorResponses(urllib.request.HTTPErrorProcessor):
    """Hand every non-redirect response back as a response instead of raising HTTPError."""

    def http_response(self, request, response):
        if http_status.is_redirect(response.status):
            return super().http_response(request, response)
        return response

    https_response = http_response


_OPENER = urllib.request.build_opener(_KeepErrorResponses)


def fetch_once(url: str, timeout_seconds: float) -> Answer | NoAnswer:
    """GET `url` once; a server that does not answer (in time) gives NoAnswer."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    # Boundary (declared in .shockharness.toml): one network call.
    try:
        response = _OPENER.open(request, timeout=timeout_seconds)
    except (OSError, http.client.HTTPException) as exc:
        return NoAnswer(reason=_describe(exc))
    with response:
        # Boundary (declared in .shockharness.toml): one network read.
        try:
            body = response.read()
        except (OSError, http.client.HTTPException) as exc:
            return NoAnswer(reason=_describe(exc))
    return Answer(status=response.status, body=body)


def _describe(exc: Exception) -> str:
    if isinstance(exc, urllib.error.URLError):
        return f"no answer: {exc.reason}"
    return f"no answer: {type(exc).__name__}: {exc}"
