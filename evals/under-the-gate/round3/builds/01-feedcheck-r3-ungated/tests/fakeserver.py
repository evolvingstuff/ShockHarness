"""A local http.server that serves scripted fake feeds for the tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Route:
    """A scripted response. `statuses` is consumed one per request; the last repeats."""

    def __init__(self, body=None, statuses=(200,), delay=0.0, raw=None, drop=False):
        self.body = body
        self.statuses = list(statuses)
        self.delay = delay
        self.raw = raw
        self.drop = drop


class FakeFeedServer:
    def __init__(self):
        self.routes: dict[str, Route] = {}
        self.hits: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with server._lock:
                    index = server.hits[self.path]
                    server.hits[self.path] += 1
                route = server.routes.get(self.path)
                if route is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if route.delay:
                    time.sleep(route.delay)
                if route.drop:
                    # Close the connection without sending a status line.
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                status = route.statuses[min(index, len(route.statuses) - 1)]
                if route.raw is not None:
                    payload = route.raw
                elif status == 200:
                    payload = json.dumps(route.body).encode("utf-8")
                else:
                    payload = b'{"error": "nope"}'
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client gave up (timeout test)

            def log_message(self, *args):
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    def url(self, path: str) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}{path}"

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)


def unused_port_url(path: str = "/feed") -> str:
    """A URL on a local port nothing is listening on (connection refused)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}{path}"
