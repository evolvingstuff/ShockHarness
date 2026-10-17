"""A local HTTP server that serves scripted fake feeds for the tests."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeFeedServer:
    """Serve routes registered with `route()`.

    Each route is a list of responses; successive requests walk the list and
    the last one repeats. A response is (status, body) or a callable taking the
    handler, for custom behaviour (slow answers, dropped connections...).
    """

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.hits: dict[str, int] = {}
        self._lock = threading.Lock()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                with server._lock:
                    n = server.hits.get(self.path, 0)
                    server.hits[self.path] = n + 1
                    responses = server.routes.get(self.path)
                if responses is None:
                    self._send(404, b"not found")
                    return
                response = responses[min(n, len(responses) - 1)]
                if callable(response):
                    response(self)
                    return
                status, body = response
                if not isinstance(body, (bytes, str)):
                    body = json.dumps(body)
                if isinstance(body, str):
                    body = body.encode()
                self._send(status, body)

            def _send(self, status, body, content_type="application/json"):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def route(self, path, *responses):
        self.routes[path] = list(responses)
        return self.url(path)

    def url(self, path):
        host, port = self.httpd.server_address
        return f"http://{host}:{port}{path}"


def slow(seconds, status=200, body=b'{"items": []}'):
    def respond(handler):
        time.sleep(seconds)
        try:
            handler._send(status, body)
        except OSError:
            pass
    return respond


def drop_connection(handler):
    handler.close_connection = True
    handler.connection.close()
