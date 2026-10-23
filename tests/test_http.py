import pytest

from chunkget import http
from chunkget.errors import ExitCode, SourceError


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/image.iso",
        "http://",
        "https:///image.iso",
        "http:///image.iso",
        "//example.com/image.iso",
        "example.com/image.iso",
        "",
        "javascript:alert(1)",
        "http://[::1/image.iso",
    ],
)
def test_invalid_urls_raise_source_error(url):
    with pytest.raises(SourceError) as excinfo:
        http.validate_url(url)
    assert excinfo.value.exit_code == ExitCode.SOURCE_ERROR


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/image.iso",
        "https://example.com/a/b.iso?x=1",
        "HTTP://Example.com/x",
    ],
)
def test_http_and_https_urls_are_accepted(url):
    assert http.validate_url(url) == url


def open_url(url):
    opener = http.build_opener()
    return opener.open(url, timeout=5)


@pytest.mark.parametrize(
    "location",
    ["file:///etc/passwd", "ftp://example.com/x", "gopher://example.com/x"],
)
def test_redirect_to_another_scheme_is_rejected(http_server, location):
    http_server.serve("/file.bin", b"data")
    http_server.redirect("/file.bin", location)
    with pytest.raises(SourceError):
        open_url(http_server.url("/file.bin"))
    # Only the original request was made: the redirect was not followed.
    assert len(http_server.requests) == 1


def test_redirect_to_http_url_is_followed(http_server):
    target = http_server.serve("/target.bin", b"payload")
    http_server.serve("/file.bin", b"")
    http_server.redirect("/file.bin", target)
    with open_url(http_server.url("/file.bin")) as response:
        assert response.read() == b"payload"


def test_relative_redirect_is_followed(http_server):
    http_server.serve("/target.bin", b"payload")
    http_server.serve("/file.bin", b"")
    http_server.redirect("/file.bin", "/target.bin")
    with open_url(http_server.url("/file.bin")) as response:
        assert response.read() == b"payload"


@pytest.mark.parametrize("scheme", ["file", "ftp"])
def test_opener_does_not_open_other_schemes_directly(scheme):
    with pytest.raises(SourceError):
        http.open_url(scheme + ":///etc/passwd", timeout=5)


# --- Classification of HTTP errors (T26) ---

import http.client as std_http_client
import socket
import ssl
import urllib.error

from chunkget.errors import SourceError as _SourceError
from chunkget.http import ErrorKind


def http_error(code):
    return urllib.error.HTTPError("http://x/", code, "msg", {}, None)


def test_error_kinds_map_to_exit_codes():
    assert ErrorKind.RETRYABLE.exit_code is None
    assert ErrorKind.FATAL.exit_code == ExitCode.NETWORK_ERROR == 6
    assert ErrorKind.INCOMPATIBLE.exit_code == ExitCode.SERVER_INCOMPATIBLE == 11
    assert ErrorKind.SOURCE.exit_code == ExitCode.SOURCE_ERROR == 3


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504, 599])
def test_retryable_statuses(status):
    assert http.classify_status(status) is ErrorKind.RETRYABLE


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 416])
def test_fatal_statuses(status):
    assert http.classify_status(status) is ErrorKind.FATAL


def test_200_instead_of_206_is_incompatible():
    assert http.classify_status(200) is ErrorKind.INCOMPATIBLE


def test_206_is_not_an_error():
    assert http.classify_status(206) is None


@pytest.mark.parametrize("status", [408, 429, 503])
def test_http_error_exceptions_use_the_status(status):
    assert http.classify_exception(http_error(status)) is ErrorKind.RETRYABLE


@pytest.mark.parametrize("status", [403, 404])
def test_fatal_http_error_exceptions(status):
    assert http.classify_exception(http_error(status)) is ErrorKind.FATAL


CERT_ERROR = ssl.SSLCertVerificationError(1, "certificate verify failed")

RETRYABLE_EXCEPTIONS = {
    "connection reset": ConnectionResetError(),
    "connection aborted": ConnectionAbortedError(),
    "connection refused": ConnectionRefusedError(),
    "broken pipe": BrokenPipeError(),
    "socket timeout": socket.timeout(),
    "timeout": TimeoutError(),
    "incomplete read": std_http_client.IncompleteRead(b"abc", 10),
    "remote disconnected": std_http_client.RemoteDisconnected("closed"),
    "bad status line": std_http_client.BadStatusLine("x"),
    "network unreachable": OSError(101, "Network is unreachable"),
    "wrapped reset": urllib.error.URLError(ConnectionResetError()),
    "wrapped timeout": urllib.error.URLError(socket.timeout("timed out")),
}


@pytest.mark.parametrize(
    "error", RETRYABLE_EXCEPTIONS.values(), ids=RETRYABLE_EXCEPTIONS.keys()
)
def test_network_failures_are_retryable(error):
    assert http.classify_exception(error) is ErrorKind.RETRYABLE


@pytest.mark.parametrize(
    "error",
    [CERT_ERROR, urllib.error.URLError(CERT_ERROR)],
    ids=["certificate", "wrapped certificate"],
)
def test_certificate_failures_are_fatal(error):
    assert http.classify_exception(error) is ErrorKind.FATAL


@pytest.mark.parametrize(
    "error",
    [
        socket.gaierror(-2, "Name or service not known"),
        urllib.error.URLError(socket.gaierror(-2, "Name or service not known")),
        _SourceError("bad url"),
    ],
    ids=["dns", "wrapped dns", "source error"],
)
def test_unreachable_source_is_a_source_error(error):
    assert http.classify_exception(error) is ErrorKind.SOURCE


def test_unknown_exceptions_are_fatal():
    assert http.classify_exception(ValueError("x")) is ErrorKind.FATAL


def classify_range(status=206, content_range="bytes 2-5/1024", total=1024,
                   encoding=None):
    return http.classify_range_response(status, content_range, total, encoding)


def test_correct_range_response_is_accepted():
    assert classify_range() is None
    assert classify_range(encoding="identity") is None


def test_range_response_with_other_total_is_incompatible():
    assert classify_range(content_range="bytes 2-5/2048") is ErrorKind.INCOMPATIBLE


@pytest.mark.parametrize(
    "content_range", [None, "", "bytes */1024", "garbage", "bytes 2-5/*"]
)
def test_range_response_without_usable_content_range_is_incompatible(content_range):
    assert classify_range(content_range=content_range) is ErrorKind.INCOMPATIBLE


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "GZIP"])
def test_content_encoding_is_incompatible(encoding):
    assert classify_range(encoding=encoding) is ErrorKind.INCOMPATIBLE


def test_200_range_response_is_incompatible():
    assert classify_range(status=200, content_range=None) is ErrorKind.INCOMPATIBLE


def test_error_statuses_are_classified_before_headers():
    assert classify_range(status=503, content_range=None) is ErrorKind.RETRYABLE
    assert classify_range(status=404, content_range=None) is ErrorKind.FATAL


# --- fetch_bytes (T27) ---

from chunkget.errors import ManifestInvalidError

LIMIT = 64 * 1024 * 1024


def test_fetch_bytes_returns_the_content(http_server):
    url = http_server.serve("/m.json", b'{"a": 1}')
    assert http.fetch_bytes(url, LIMIT, 5) == b'{"a": 1}'


def test_fetch_bytes_accepts_content_of_exactly_the_limit(http_server):
    url = http_server.serve("/m.json", b"x" * 100)
    assert http.fetch_bytes(url, 100, 5) == b"x" * 100


def test_fetch_bytes_rejects_content_over_the_limit(http_server):
    url = http_server.serve("/m.json", b"x" * 101)
    with pytest.raises(ManifestInvalidError) as excinfo:
        http.fetch_bytes(url, 100, 5)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID
    assert "100" in str(excinfo.value)


def test_fetch_bytes_does_not_read_a_huge_body_when_length_is_known(http_server):
    url = http_server.serve("/big", b"x" * 10_000)
    http_server.cut_connection_after("/big", 10)  # a read would fail
    with pytest.raises(ManifestInvalidError):
        http.fetch_bytes(url, 100, 5)


@pytest.mark.parametrize("status", [403, 404, 500, 503])
def test_fetch_bytes_http_errors_are_source_errors(http_server, status):
    http_server.respond_with_statuses("/m.json", [status])
    with pytest.raises(SourceError) as excinfo:
        http.fetch_bytes(http_server.url("/m.json"), LIMIT, 5)
    assert excinfo.value.exit_code == ExitCode.SOURCE_ERROR
    assert str(status) in str(excinfo.value)


def test_fetch_bytes_missing_resource_is_a_source_error(http_server):
    with pytest.raises(SourceError):
        http.fetch_bytes(http_server.url("/missing"), LIMIT, 5)


def test_fetch_bytes_timeout_is_a_source_error():
    import socket

    # Accepts connections in the kernel backlog but never answers.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        url = "http://127.0.0.1:%d/m.json" % silent.getsockname()[1]
        with pytest.raises(SourceError):
            http.fetch_bytes(url, LIMIT, 0.2)


def test_fetch_bytes_connection_refused_is_a_source_error():
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(SourceError):
        http.fetch_bytes("http://127.0.0.1:%d/m.json" % port, LIMIT, 5)


def test_fetch_bytes_truncated_body_is_a_source_error(http_server):
    url = http_server.serve("/m.json", b"x" * 1000)
    http_server.cut_connection_after("/m.json", 10)
    with pytest.raises(SourceError):
        http.fetch_bytes(url, LIMIT, 5)


def test_fetch_bytes_rejects_other_schemes():
    with pytest.raises(SourceError):
        http.fetch_bytes("file:///etc/passwd", LIMIT, 5)
