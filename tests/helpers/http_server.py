"""Local HTTP server with ``Range`` support for tests (127.0.0.1 only)."""

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = self.server.resources.get(self.path)
        if data is None:
            self.send_error(404)
            return
        match = _RANGE_RE.fullmatch(self.headers.get("Range", ""))
        if match is None:
            self._send(200, data, {"Accept-Ranges": "bytes"})
            return
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else len(data) - 1
        end = min(end, len(data) - 1)
        if start >= len(data) or start > end:
            self._send(416, b"", {"Content-Range": "bytes */%d" % len(data)})
            return
        content_range = "bytes %d-%d/%d" % (start, end, len(data))
        self._send(206, data[start : end + 1], {"Content-Range": content_range})

    def _send(self, status, body, headers):
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class HttpTestServer:
    """Serves in-memory resources on an ephemeral port of 127.0.0.1."""

    def __init__(self):
        self.resources = {}
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.resources = self.resources
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.01}
        )

    @property
    def port(self):
        return self._httpd.server_address[1]

    def url(self, path):
        return "http://127.0.0.1:%d%s" % (self.port, path)

    def serve(self, path, data):
        """Publish ``data`` at ``path`` and return its URL."""
        self.resources[path] = data
        return self.url(path)

    def start(self):
        self._thread.start()

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc_info):
        self.stop()
