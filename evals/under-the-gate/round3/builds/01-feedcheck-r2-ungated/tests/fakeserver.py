"""A local http.server that serves fake feeds for the tests."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeFeedServer:
    """Routes map a path to a list of responses, served in order (the last repeats).

    A response is a tuple (status, body) where body is bytes, str or a JSON-able
    object, or one of the special strings "drop" (close the connection without
    answering) or ("sleep", seconds, status, body).
    """

    def __init__(self):
        self.routes: dict[str, list] = {}
        self.hits: dict[str, int] = defaultdict(int)
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                server.hits[self.path] += 1
                responses = server.routes.get(self.path)
                if responses is None:
                    self._send(404, {"error": "not found"})
                    return
                n = server.hits[self.path]
                resp = responses[min(n, len(responses)) - 1]
                if resp == "drop":
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                if resp[0] == "sleep":
                    _, seconds, status, body = resp
                    time.sleep(seconds)
                    resp = (status, body)
                try:
                    self._send(*resp)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def _send(self, status, body):
                if isinstance(body, bytes):
                    data = body
                elif isinstance(body, str):
                    data = body.encode()
                else:
                    data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


def closed_port_url() -> str:
    """A URL on a local port with nothing listening."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}/feed"
