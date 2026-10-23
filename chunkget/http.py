"""HTTP client built on urllib (plan D5)."""

import urllib.parse
import urllib.request

from chunkget.errors import SourceError
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
