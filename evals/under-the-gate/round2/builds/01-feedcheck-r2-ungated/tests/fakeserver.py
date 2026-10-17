"""A local HTTP server that serves scripted fake feeds for tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Response:
    def __init__(self, status=200, body=b"", delay=0.0, content_type="application/json"):
        self.status = status
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.delay = delay
        self.content_type = content_type


class FakeFeedServer:
    """Serves routes; each route is a list of responses, the last one repeating."""

    def __init__(self):
        self.routes: dict[str, list[Response]] = {}
        self.hits: dict[str, int] = defaultdict(int)
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                n = server.hits[self.path]
                server.hits[self.path] += 1
                responses = server.routes.get(self.path)
                if not responses:
                    resp = Response(404, b"not found", content_type="text/plain")
                else:
                    resp = responses[min(n, len(responses) - 1)]
                if resp.delay:
                    time.sleep(resp.delay)
                try:
                    self.send_response(resp.status)
                    self.send_header("Content-Type", resp.content_type)
                    self.send_header("Content-Length", str(len(resp.body)))
                    self.end_headers()
                    self.wfile.write(resp.body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}{path}"

    def add(self, path: str, *responses: Response) -> str:
        self.routes[path] = list(responses)
        return self.url(path)


def closed_port_url() -> str:
    """A URL on localhost where nothing is listening."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/feed"
