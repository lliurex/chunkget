"""Local HTTP server with ``Range`` support for tests (127.0.0.1 only)."""

import collections
import dataclasses
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


@dataclasses.dataclass(frozen=True)
class RequestRecord:
    """A request received by the server."""

    path: str
    headers: dict

    @property
    def range(self):
        return self.headers.get("Range")


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append(
            RequestRecord(self.path, dict(self.headers.items()))
        )
        hook = self.server.hooks.get(self.path)
        if hook is not None:
            hook(sum(1 for r in self.server.requests if r.path == self.path))
        delay = self.server.delays.get(self.path)
        if delay:
            time.sleep(delay)
        statuses = self.server.statuses.get(self.path)
        if statuses:
            self._send(statuses.popleft(), b"", {})
            return
        location = self.server.redirects.get(self.path)
        if location is not None:
            self._send(302, b"", {"Location": location})
            return
        data = self.server.resources.get(self.path)
        if data is None:
            self.send_error(404)
            return
        match = _RANGE_RE.fullmatch(self.headers.get("Range", ""))
        if self.path in self.server.ignored_ranges:
            self._send(200, data, {}, offset=0)
            return
        if match is None:
            self._send(200, data, {"Accept-Ranges": "bytes"}, offset=0)
            return
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else len(data) - 1
        end = min(end, len(data) - 1)
        if start >= len(data) or start > end:
            self._send(416, b"", {"Content-Range": "bytes */%d" % len(data)})
            return
        total = self.server.totals.get(self.path, len(data))
        content_range = "bytes %d-%d/%d" % (start, end, total)
        self._send(
            206,
            data[start : end + 1],
            {"Content-Range": content_range},
            offset=start,
        )

    def _send(self, status, body, headers, offset=0):
        """Send ``body``, which starts at ``offset`` in the resource."""
        body = self._corrupt(body, offset)
        cut_after = self._next_cut()
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        for name, value in headers.items():
            self.send_header(name, value)
        encoding = self.server.encodings.get(self.path)
        if encoding is not None:
            self.send_header("Content-Encoding", encoding)
        self.end_headers()
        # With a cut, Content-Length promises more than is written and the
        # connection is closed after the request (HTTP/1.0).
        self.wfile.write(body if cut_after is None else body[:cut_after])

    def _next_cut(self):
        """Bytes to send before cutting this response, or None for no cut."""
        cut = self.server.cuts.get(self.path)
        if cut is None:
            return None
        nbytes, remaining = cut
        if remaining is None:
            return nbytes
        if remaining <= 0:
            return None
        cut[1] -= 1
        return nbytes

    def _corrupt(self, body, offset):
        """Flip the bytes of ``body`` that fall in the corrupted range."""
        span = self.server.corruptions.get(self.path)
        if span is None:
            return body
        low = max(span[0], offset) - offset
        high = min(span[1], offset + len(body)) - offset
        if low >= high:
            return body
        middle = bytes(byte ^ 0xFF for byte in body[low:high])
        return body[:low] + middle + body[high:]

    def log_message(self, format, *args):
        pass


class HttpTestServer:
    """Serves in-memory resources on an ephemeral port of 127.0.0.1."""

    def __init__(self):
        self.resources = {}
        self.requests = []
        self.cuts = {}
        self.corruptions = {}
        self.ignored_ranges = set()
        self.totals = {}
        self.encodings = {}
        self.statuses = {}
        self.redirects = {}
        self.hooks = {}
        self.delays = {}
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.resources = self.resources
        self._httpd.requests = self.requests
        self._httpd.cuts = self.cuts
        self._httpd.corruptions = self.corruptions
        self._httpd.ignored_ranges = self.ignored_ranges
        self._httpd.totals = self.totals
        self._httpd.encodings = self.encodings
        self._httpd.statuses = self.statuses
        self._httpd.redirects = self.redirects
        self._httpd.hooks = self.hooks
        self._httpd.delays = self.delays
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

    def cut_connection_after(self, path, nbytes, times=None):
        """Close the connection after ``nbytes`` of the body of ``path``.

        Only the next ``times`` responses are cut; by default all of them.
        """
        self.cuts[path] = [nbytes, times]

    def corrupt_range(self, path, start, end):
        """Alter the bytes ``start``-``end`` (exclusive) of ``path`` when served."""
        self.corruptions[path] = (start, end)

    def ignore_range(self, path):
        """Answer ``Range`` requests for ``path`` with 200 and the whole body."""
        self.ignored_ranges.add(path)

    def report_total(self, path, total):
        """Use ``total`` as the size in the ``Content-Range`` of ``path``."""
        self.totals[path] = total

    def set_content_encoding(self, path, encoding):
        """Add ``Content-Encoding: <encoding>`` to the responses for ``path``."""
        self.encodings[path] = encoding

    def respond_with_statuses(self, path, statuses):
        """Answer the next requests for ``path`` with these status codes."""
        self.statuses[path] = collections.deque(statuses)

    def redirect(self, path, location):
        """Answer requests for ``path`` with a 302 to ``location``."""
        self.redirects[path] = location

    def on_request(self, path, callback):
        """Call ``callback(n)`` when the ``n``-th request for ``path`` arrives."""
        self.hooks[path] = callback

    def delay(self, path, seconds):
        """Wait ``seconds`` before answering each request for ``path``."""
        self.delays[path] = seconds

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
