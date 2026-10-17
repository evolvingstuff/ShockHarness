"""A local HTTP server that serves scripted feed answers to the tests."""

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class Reply:
    status: HTTPStatus
    body: bytes


def json_reply(status: HTTPStatus, document: object) -> Reply:
    return Reply(status=status, body=json.dumps(document).encode("utf-8"))


class FakeFeedServer:
    """Serves ``routes[path]`` replies in order; the last reply repeats.

    A path listed in ``hanging`` never answers until the server stops.
    """

    def __init__(self, routes: dict[str, Sequence[Reply]], hanging: frozenset[str]) -> None:
        self.requests: dict[str, int] = {path: 0 for path in [*routes, *hanging]}
        self._routes = routes
        self._hanging = hanging
        self._release = threading.Event()
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_class())
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="fake-feeds")

    def url(self, path: str) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}{path}"

    def __enter__(self) -> "FakeFeedServer":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._release.set()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def _next_reply(self, path: str) -> Reply | None:
        with self._lock:
            served = self.requests[path]
            self.requests[path] = served + 1
        if path in self._hanging:
            self._release.wait()
            return None
        replies = self._routes[path]
        return replies[min(served, len(replies) - 1)]

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                reply = fake._next_reply(self.path)
                if reply is None:
                    return
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            def log_message(self, format: str, *args: object) -> None:
                """Keep test output quiet."""

        return Handler
