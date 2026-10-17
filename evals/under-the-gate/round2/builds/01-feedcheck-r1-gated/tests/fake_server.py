"""A local HTTP server that serves scripted answers per path, for tests without network access."""

import json
import socket
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class Reply:
    status: int
    body: bytes


def json_reply(status: int, document: object) -> Reply:
    return Reply(status=status, body=json.dumps(document).encode("utf-8"))


class FakeFeedServer:
    """Serve routes: path -> list of replies, one per request; the last reply repeats."""

    def __init__(self) -> None:
        self.routes: dict[str, list[Reply]] = {}
        self.hits: Counter[str] = Counter()
        self.release = threading.Event()
        self.slow_paths: set[str] = set()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                server.hits[self.path] += 1
                if self.path in server.slow_paths:
                    server.release.wait()
                replies = server.routes[self.path]
                reply = replies[min(server.hits[self.path], len(replies)) - 1]
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            def log_message(self, format: str, *args: object) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FakeFeedServer":
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    def url(self, path: str) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}{path}"

    def total_hits(self) -> int:
        return sum(self.hits.values())


def unused_port_url(path: str) -> str:
    """A URL on a local port nothing listens on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}{path}"


def recording_sleep(waits: list[float]) -> Callable[[float], None]:
    return waits.append
