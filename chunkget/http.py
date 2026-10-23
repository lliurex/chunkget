"""HTTP client built on urllib (plan D5)."""

import enum
import http.client
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from chunkget import __version__, config
from chunkget.errors import (
    ChunkgetError,
    ExitCode,
    FilesystemError,
    ManifestInvalidError,
    NetworkError,
    ServerIncompatibleError,
    SourceError,
)
from chunkget.i18n import _

ALLOWED_SCHEMES = ("http", "https")


def validate_url(url):
    """Return ``url`` if it is an http(s) URL with a host, else raise SourceError."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        parts = host = None
    if parts is None or parts.scheme not in ALLOWED_SCHEMES or not host:
        raise SourceError(
            _(
                "invalid URL {url!r}: only http and https URLs with a host "
                "are allowed"
            ).format(url=url)
        )
    return url


class RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to valid http(s) URLs."""

    def http_error_302(self, req, fp, code, msg, headers):
        location = headers.get("location") or headers.get("uri")
        if location:
            validate_url(urllib.parse.urljoin(req.full_url, location))
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = (
        http_error_302
    )


def build_opener():
    """An opener that only speaks http(s) and restricts redirects."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler(),
        urllib.request.UnknownHandler(),
        urllib.request.HTTPHandler(),
        urllib.request.HTTPSHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        RestrictedRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener


def open_url(url, timeout, headers=None):
    """Open a validated http(s) URL and return the response."""
    request = urllib.request.Request(validate_url(url), headers=headers or {})
    return build_opener().open(request, timeout=timeout)


class ErrorKind(enum.Enum):
    """How the downloader reacts to a failed request (plan D5)."""

    RETRYABLE = None
    FATAL = ExitCode.NETWORK_ERROR
    INCOMPATIBLE = ExitCode.SERVER_INCOMPATIBLE
    SOURCE = ExitCode.SOURCE_ERROR

    @property
    def exit_code(self):
        """Exit code of the error, or None if the request can be retried."""
        return self.value


def classify_status(status):
    """Classify the status of a ranged request; None if it is the expected 206."""
    if status == 206:
        return None
    if status == 200:
        # The server ignored the Range header.
        return ErrorKind.INCOMPATIBLE
    if status in (408, 429) or 500 <= status <= 599:
        return ErrorKind.RETRYABLE
    return ErrorKind.FATAL


def classify_exception(error):
    """Classify an exception raised while talking to the server."""
    if isinstance(error, urllib.error.HTTPError):
        return classify_status(error.code) or ErrorKind.FATAL
    if isinstance(error, urllib.error.URLError) and isinstance(
        error.reason, BaseException
    ):
        return classify_exception(error.reason)
    if isinstance(error, SourceError | socket.gaierror):
        return ErrorKind.SOURCE
    if isinstance(error, ssl.SSLCertVerificationError):
        return ErrorKind.FATAL
    if isinstance(error, OSError | http.client.HTTPException):
        # Resets, timeouts, truncated reads, unreachable networks...
        return ErrorKind.RETRYABLE
    return ErrorKind.FATAL


_CONTENT_RANGE_RE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")


def classify_range_response(status, content_range, expected_total, content_encoding):
    """Classify the headers of a response to a ranged request.

    Returns None if the response is a usable 206 whose ``Content-Range``
    reports ``expected_total`` and which is not content-encoded.
    """
    kind = classify_status(status)
    if kind is not None:
        return kind
    match = _CONTENT_RANGE_RE.fullmatch(content_range or "")
    if match is None or int(match.group(3)) != expected_total:
        return ErrorKind.INCOMPATIBLE
    if content_encoding and content_encoding.strip().lower() != "identity":
        return ErrorKind.INCOMPATIBLE
    return None


class RetryableError(NetworkError):
    """A transient failure: the same request may succeed if repeated."""


_EXCEPTION_CLASSES = {
    ErrorKind.RETRYABLE: RetryableError,
    ErrorKind.FATAL: NetworkError,
    ErrorKind.INCOMPATIBLE: ServerIncompatibleError,
    ErrorKind.SOURCE: SourceError,
}


def _exception_for(kind, text):
    """Build the exception for an ``ErrorKind``.

    ``text`` must already be translated: every caller passes ``_("...")``.
    """
    return _EXCEPTION_CLASSES[kind](text)


class RangeStream:
    """The body of a ranged response, checked against the expected length."""

    def __init__(self, response, expected_length):
        self._response = response
        self._expected = expected_length
        self._received = 0

    def read(self, size=-1):
        try:
            data = self._response.read(size)
        except (OSError, http.client.HTTPException) as error:
            raise _exception_for(
                classify_exception(error),
                _("connection failed while receiving data: {reason}").format(
                    reason=error
                ),
            ) from None
        self._received += len(data)
        if self._received > self._expected:
            raise ServerIncompatibleError(
                _("the server sent more data than the {expected} bytes requested").format(
                    expected=self._expected
                )
            )
        # read(n) does not raise when the connection is cut: check at EOF.
        if (not data or size is None or size < 0) and self._received < self._expected:
            raise RetryableError(
                _("incomplete data: received {received} of {expected} bytes").format(
                    received=self._received, expected=self._expected
                )
            )
        return data

    def close(self):
        self._response.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def open_range(url, start, end, timeout, *, total):
    """Request the bytes ``start`` (inclusive) to ``end`` (exclusive) of ``url``.

    ``total`` is the size of the whole resource according to the manifest.
    Returns a stream of exactly ``end - start`` bytes. Errors are classified:
    ``ServerIncompatibleError`` if the server does not honour the range,
    ``RetryableError`` for transient failures and ``NetworkError`` for the rest.
    """
    try:
        response = open_url(
            url,
            timeout,
            headers={
                "Range": "bytes=%d-%d" % (start, end - 1),
                "Accept-Encoding": "identity",
                "User-Agent": "chunkget/" + __version__,
            },
        )
    except ChunkgetError:
        raise
    except urllib.error.HTTPError as error:
        raise _exception_for(
            classify_status(error.code) or ErrorKind.FATAL,
            _("HTTP error {status} while requesting {url}").format(
                status=error.code, url=url
            ),
        ) from None
    except (OSError, http.client.HTTPException) as error:
        reason = getattr(error, "reason", None) or error
        raise _exception_for(
            classify_exception(error),
            _("cannot connect to {url}: {reason}").format(url=url, reason=reason),
        ) from None
    try:
        _check_range_response(response, start, end, total)
    except BaseException:
        response.close()
        raise
    return RangeStream(response, end - start)


def _check_range_response(response, start, end, total):
    content_range = response.headers.get("Content-Range")
    encoding = response.headers.get("Content-Encoding")
    kind = classify_range_response(response.status, content_range, total, encoding)
    expected = "bytes %d-%d/%d" % (start, end - 1, total)
    if kind is None and content_range != expected:
        kind = ErrorKind.INCOMPATIBLE
    if kind is not None:
        raise _exception_for(
            kind,
            _(
                "unexpected response from the server: HTTP {status}, "
                "Content-Range {content_range!r} (expected {expected!r}), "
                "Content-Encoding {encoding!r}"
            ).format(
                status=response.status,
                content_range=content_range,
                expected=expected,
                encoding=encoding,
            ),
        )


def _source_error(url, error):
    """Translate a failure of a plain request into a ``SourceError``."""
    if isinstance(error, urllib.error.HTTPError):
        return SourceError(
            _("cannot fetch {url}: HTTP error {status}").format(
                url=url, status=error.code
            )
        )
    reason = getattr(error, "reason", None) or error
    return SourceError(
        _("cannot fetch {url}: {reason}").format(url=url, reason=reason)
    )


def fetch_bytes(url, max_bytes, timeout):
    """Read a small resource into memory.

    Network and HTTP failures are source errors; a resource larger than
    ``max_bytes`` is an invalid manifest.
    """
    try:
        with open_url(url, timeout) as response:
            length = response.headers.get("Content-Length")
            if length is not None and length.isdigit() and int(length) > max_bytes:
                raise _too_large(max_bytes)
            data = response.read(max_bytes + 1)
            # read(n) does not raise IncompleteRead when the body is cut.
            if length is not None and length.isdigit() and len(data) < int(length):
                raise http.client.IncompleteRead(data, int(length) - len(data))
    except (OSError, http.client.HTTPException) as error:
        raise _source_error(url, error) from None
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data


def simple_download(url, path, timeout):
    """GET ``url`` straight into ``path`` (no temporary file).

    Failures to reach the source are ``SourceError``; a body cut short is a
    ``RetryableError`` and the partial file stays where it is.
    """
    try:
        response = open_url(url, timeout)
    except (OSError, http.client.HTTPException) as error:
        raise _source_error(url, error) from None
    with response:
        length = response.headers.get("Content-Length")
        try:
            handle = open(path, "wb")
        except OSError as error:
            raise _write_error(path, error) from None
        written = 0
        with handle:
            while True:
                try:
                    block = response.read(config.BUFFER_SIZE)
                except (OSError, http.client.HTTPException) as error:
                    raise RetryableError(
                        _("connection failed while downloading {url}: {reason}").format(
                            url=url, reason=error
                        )
                    ) from None
                if not block:
                    break
                try:
                    handle.write(block)
                except OSError as error:
                    raise _write_error(path, error) from None
                written += len(block)
    if length is not None and length.isdigit() and written < int(length):
        raise RetryableError(
            _("incomplete download of {url}: received {received} of {expected} bytes").format(
                url=url, received=written, expected=int(length)
            )
        )


def _write_error(path, error):
    return FilesystemError(
        _("cannot write {path}: {reason}").format(
            path=path, reason=error.strerror or error
        )
    )


def _too_large(max_bytes):
    return ManifestInvalidError(
        _("invalid manifest: it is larger than {maximum} bytes").format(
            maximum=max_bytes
        )
    )
