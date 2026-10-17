"""A local HTTP server that serves fake feeds for the tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).isoformat()


class FakeFeedServer:
    """Serves canned responses by path and counts requests per path.

    Routes:
      /ok               200 with two items
      /empty            200 with an empty items list
      /fresh            200, newest item 1 hour old
      /stale            200, newest item 48 hours old
      /undated          200, items without 'published'
      /baddate          200, an item with an unparseable 'published'
      /flaky-N          503 for the first N requests, then like /ok
      /always-500       500 every time
      /404              404
      /not-json         200 with a non-JSON body
      /array            200 with a JSON array
      /no-items         200 with an object lacking 'items'
      /items-not-list   200 with 'items' as a string
      /slow             sleeps longer than any test timeout before answering
      /hangup           closes the connection without answering
    """

    SLOW_SECONDS = 2.0

    def __init__(self) -> None:
        self.hits: Counter[str] = Counter()
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # keep test output quiet
                pass

            def do_GET(self):
                with owner._lock:
                    owner.hits[self.path] += 1
                    count = owner.hits[self.path]
                owner._route(self, self.path, count)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def total_hits(self) -> int:
        return sum(self.hits.values())

    def url(self, path: str) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}{path}"

    def start(self) -> "FakeFeedServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    @staticmethod
    def _send(handler, status: int, body, content_type="application/json") -> None:
        if not isinstance(body, (bytes, str)):
            body = json.dumps(body)
        if isinstance(body, str):
            body = body.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _route(self, h, path: str, count: int) -> None:
        ok = {"items": [{"id": 1, "published": _iso(timedelta(hours=2))}, {"id": 2}]}
        if path == "/ok":
            self._send(h, 200, ok)
        elif path == "/empty":
            self._send(h, 200, {"items": []})
        elif path == "/fresh":
            self._send(h, 200, {"items": [
                {"published": _iso(timedelta(hours=30))},
                {"published": _iso(timedelta(hours=1))},
            ]})
        elif path == "/stale":
            self._send(h, 200, {"items": [
                {"published": _iso(timedelta(hours=48))},
                {"published": _iso(timedelta(hours=72))},
            ]})
        elif path == "/undated":
            self._send(h, 200, {"items": [{"id": 1}, {"id": 2}]})
        elif path == "/baddate":
            self._send(h, 200, {"items": [{"published": "last tuesday"}]})
        elif path.startswith("/flaky-"):
            failures = int(path.rsplit("-", 1)[1])
            if count <= failures:
                self._send(h, 503, {"error": "busy"})
            else:
                self._send(h, 200, ok)
        elif path == "/always-500":
            self._send(h, 500, {"error": "boom"})
        elif path == "/404":
            self._send(h, 404, {"error": "not found"})
        elif path == "/not-json":
            self._send(h, 200, "<html>hello</html>", content_type="text/html")
        elif path == "/array":
            self._send(h, 200, [1, 2, 3])
        elif path == "/no-items":
            self._send(h, 200, {"entries": []})
        elif path == "/items-not-list":
            self._send(h, 200, {"items": "nope"})
        elif path == "/slow":
            time.sleep(self.SLOW_SECONDS)
            try:
                self._send(h, 200, ok)
            except OSError:
                pass
        elif path == "/hangup":
            h.close_connection = True
            h.connection.shutdown(socket.SHUT_RDWR)
        else:
            self._send(h, 404, {"error": "unknown route"})


def closed_port_url() -> str:
    """A URL on localhost where nothing is listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}/feed"
