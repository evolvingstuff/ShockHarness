"""A local HTTP server that serves fake feeds for the tests."""

import json
import threading
from collections import Counter
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeFeeds:
    """Routes map a path to a list of (status, body bytes, delay seconds) answers, one per request;
    the last answer repeats. Requests per path are counted in `hits`."""

    def __init__(self):
        self.routes = {}
        self.hits = Counter()
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with fake._lock:
                    count = fake.hits[self.path]
                    fake.hits[self.path] += 1
                    if self.path in fake.routes:
                        answers = fake.routes[self.path]
                    else:
                        answers = [(404, b"not found", 0)]
                    status, body, delay = answers[min(count, len(answers) - 1)]
                if delay:
                    time.sleep(delay)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc_info):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def url(self, path):
        host, port = self.server.server_address
        return f"http://{host}:{port}{path}"

    def serve(self, path, *answers):
        self.routes[path] = list(answers)

    def serve_json(self, path, document, status=200):
        self.serve(path, (status, json.dumps(document).encode(), 0))
