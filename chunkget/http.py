"""HTTP client built on urllib (plan D5)."""

import enum
import http.client
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request

from chunkget.errors import ExitCode, ManifestInvalidError, SourceError
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


def open_url(url, timeout):
    """Open a validated http(s) URL and return the response."""
    return build_opener().open(validate_url(url), timeout=timeout)


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
    except urllib.error.HTTPError as error:
        raise SourceError(
            _("cannot fetch {url}: HTTP error {status}").format(
                url=url, status=error.code
            )
        ) from None
    except (OSError, http.client.HTTPException) as error:
        reason = getattr(error, "reason", None) or error
        raise SourceError(
            _("cannot fetch {url}: {reason}").format(url=url, reason=reason)
        ) from None
    if len(data) > max_bytes:
        raise _too_large(max_bytes)
    return data


def _too_large(max_bytes):
    return ManifestInvalidError(
        _("invalid manifest: it is larger than {maximum} bytes").format(
            maximum=max_bytes
        )
    )
