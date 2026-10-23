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


# --- open_range: successful request (T28) ---

import chunkget

RANGE_DATA = bytes(range(256)) * 4


def test_open_range_delivers_the_requested_bytes(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    with http.open_range(url, 100, 200, 5, total=1024) as stream:
        assert stream.read() == RANGE_DATA[100:200]


def test_open_range_can_be_read_in_blocks(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    with http.open_range(url, 0, 1024, 5, total=1024) as stream:
        blocks = []
        while True:
            block = stream.read(100)
            if not block:
                break
            blocks.append(block)
    assert b"".join(blocks) == RANGE_DATA
    assert max(len(block) for block in blocks) <= 100


def test_open_range_sends_the_expected_headers(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    with http.open_range(url, 100, 200, 5, total=1024) as stream:
        stream.read()
    (record,) = http_server.requests
    assert record.path == "/file.bin"
    assert record.headers["Range"] == "bytes=100-199"
    assert record.headers["Accept-Encoding"] == "identity"
    assert record.headers["User-Agent"] == "chunkget/" + chunkget.__version__
    # Only the connection headers added by http.client come on top.
    extra = set(record.headers) - {"Range", "Accept-Encoding", "User-Agent"}
    assert extra <= {"Host", "Connection"}


def test_open_range_first_byte_only(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    with http.open_range(url, 0, 1, 5, total=1024) as stream:
        assert stream.read() == RANGE_DATA[:1]
    assert http_server.requests[0].headers["Range"] == "bytes=0-0"


def test_open_range_rejects_invalid_urls():
    with pytest.raises(SourceError):
        http.open_range("file:///etc/passwd", 0, 10, 5, total=1024)


# --- open_range: validation and errors (T29) ---

from chunkget.errors import NetworkError, ServerIncompatibleError
from chunkget.http import RetryableError


def read_range(url, start=0, end=100, total=1024, timeout=5):
    with http.open_range(url, start, end, timeout, total=total) as stream:
        return stream.read()


def test_open_range_accepts_a_correct_response(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    assert read_range(url, 10, 110) == RANGE_DATA[10:110]


def test_200_response_is_incompatible(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.ignore_range("/file.bin")
    with pytest.raises(ServerIncompatibleError) as excinfo:
        read_range(url)
    assert excinfo.value.exit_code == ExitCode.SERVER_INCOMPATIBLE


def test_different_total_is_incompatible(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.report_total("/file.bin", 2048)
    with pytest.raises(ServerIncompatibleError):
        read_range(url)


def test_wrong_expected_total_is_incompatible(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    with pytest.raises(ServerIncompatibleError):
        read_range(url, total=999)


def test_content_encoding_is_incompatible(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.set_content_encoding("/file.bin", "gzip")
    with pytest.raises(ServerIncompatibleError):
        read_range(url)


def test_404_is_a_fatal_network_error(http_server):
    url = http_server.url("/missing")
    with pytest.raises(NetworkError) as excinfo:
        read_range(url)
    assert not isinstance(excinfo.value, RetryableError)
    assert excinfo.value.exit_code == ExitCode.NETWORK_ERROR


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_statuses_raise_a_retryable_error(http_server, status):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.respond_with_statuses("/file.bin", [status])
    with pytest.raises(RetryableError):
        read_range(url)


def test_cut_in_the_middle_of_the_body_is_retryable(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.cut_connection_after("/file.bin", 40)
    with pytest.raises(RetryableError):
        read_range(url)


def test_cut_is_detected_when_reading_in_blocks(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.cut_connection_after("/file.bin", 40)
    received = b""
    with http.open_range(url, 0, 100, 5, total=1024) as stream:
        with pytest.raises(RetryableError):
            while True:
                block = stream.read(30)
                if not block:
                    break
                received += block
    assert received == RANGE_DATA[:40]


def test_empty_body_is_retryable(http_server):
    url = http_server.serve("/file.bin", RANGE_DATA)
    http_server.cut_connection_after("/file.bin", 0)
    with pytest.raises(RetryableError):
        read_range(url)


def test_connection_refused_is_retryable():
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(RetryableError):
        read_range("http://127.0.0.1:%d/x" % port)


def test_timeout_is_retryable():
    import socket

    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        url = "http://127.0.0.1:%d/x" % silent.getsockname()[1]
        with pytest.raises(RetryableError):
            read_range(url, timeout=0.2)


def test_retryable_error_is_a_network_error():
    assert issubclass(RetryableError, NetworkError)


# --- simple_download (T30) ---

import os

from chunkget import config
from chunkget.errors import FilesystemError


def big_data(size):
    return bytes((index * 31 + 7) % 251 for index in range(size))


def test_simple_download_writes_the_file(http_server, tmp_path):
    data = big_data(2 * config.BUFFER_SIZE + 12345)
    url = http_server.serve("/image.iso", data)
    destination = tmp_path / "image.iso"
    http.simple_download(url, destination, 5)
    assert destination.read_bytes() == data


def test_simple_download_of_an_empty_resource(http_server, tmp_path):
    url = http_server.serve("/empty", b"")
    destination = tmp_path / "empty"
    http.simple_download(url, destination, 5)
    assert destination.read_bytes() == b""


def test_simple_download_replaces_an_existing_file(http_server, tmp_path):
    url = http_server.serve("/f", b"new")
    destination = tmp_path / "f"
    destination.write_bytes(b"old content that is longer")
    http.simple_download(url, destination, 5)
    assert destination.read_bytes() == b"new"


class ListingResponse:
    """Wraps a response and records the directory contents on every read."""

    def __init__(self, response, directory, listings):
        self._response = response
        self.headers = response.headers
        self._directory = directory
        self._listings = listings

    def read(self, size=-1):
        self._listings.append(sorted(os.listdir(self._directory)))
        return self._response.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._response.close()


def test_only_the_destination_file_exists_while_downloading(
    http_server, tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "BUFFER_SIZE", 1000)
    data = big_data(5500)
    url = http_server.serve("/image.iso", data)
    listings = []
    real_open_url = http.open_url
    monkeypatch.setattr(
        http,
        "open_url",
        lambda *args, **kwargs: ListingResponse(
            real_open_url(*args, **kwargs), tmp_path, listings
        ),
    )
    http.simple_download(url, tmp_path / "image.iso", 5)
    assert len(listings) >= 5
    assert all(listing == ["image.iso"] for listing in listings)
    assert sorted(os.listdir(tmp_path)) == ["image.iso"]
    assert (tmp_path / "image.iso").read_bytes() == data


def test_simple_download_reads_in_buffer_sized_blocks(
    http_server, tmp_path, monkeypatch
):
    monkeypatch.setattr(config, "BUFFER_SIZE", 1000)
    url = http_server.serve("/f", big_data(5500))
    sizes = []
    real_open_url = http.open_url

    class Recording(ListingResponse):
        def read(self, size=-1):
            sizes.append(size)
            return self._response.read(size)

    monkeypatch.setattr(
        http,
        "open_url",
        lambda *a, **k: Recording(real_open_url(*a, **k), tmp_path, []),
    )
    http.simple_download(url, tmp_path / "f", 5)
    assert sizes and all(size == 1000 for size in sizes)


def test_http_error_is_a_source_error_and_creates_no_file(http_server, tmp_path):
    destination = tmp_path / "missing"
    with pytest.raises(SourceError):
        http.simple_download(http_server.url("/missing"), destination, 5)
    assert os.listdir(tmp_path) == []


def test_http_error_keeps_an_existing_file(http_server, tmp_path):
    destination = tmp_path / "keep"
    destination.write_bytes(b"precious")
    with pytest.raises(SourceError):
        http.simple_download(http_server.url("/missing"), destination, 5)
    assert destination.read_bytes() == b"precious"


def test_simple_download_rejects_other_schemes(tmp_path):
    with pytest.raises(SourceError):
        http.simple_download("file:///etc/passwd", tmp_path / "x", 5)
    assert os.listdir(tmp_path) == []


def test_cut_connection_leaves_the_partial_file(http_server, tmp_path):
    url = http_server.serve("/f", big_data(5000))
    http_server.cut_connection_after("/f", 1500)
    destination = tmp_path / "f"
    with pytest.raises(NetworkError):
        http.simple_download(url, destination, 5, max_retries=0)
    # The partial content stays, so that the download can be resumed.
    assert destination.read_bytes() == big_data(5000)[:1500]


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unwritable_destination_is_a_filesystem_error(http_server, tmp_path):
    url = http_server.serve("/f", b"data")
    directory = tmp_path / "readonly"
    directory.mkdir()
    directory.chmod(0o500)
    try:
        with pytest.raises(FilesystemError) as excinfo:
            http.simple_download(url, directory / "f", 5)
        assert excinfo.value.exit_code == ExitCode.FILESYSTEM_ERROR
    finally:
        directory.chmod(0o700)


# --- simple_download: resume (T31) ---

import inspect


def ranges_requested(server):
    return [record.range for record in server.requests]


def test_resume_defaults_follow_the_plan():
    parameters = inspect.signature(http.simple_download).parameters
    assert parameters["max_retries"].default == config.DEFAULT_MAX_RETRIES


def test_download_resumes_after_a_cut(http_server, tmp_path):
    data = big_data(5000)
    url = http_server.serve("/f", data)
    http_server.cut_connection_after("/f", 1500, times=1)
    waits = []
    destination = tmp_path / "f"
    http.simple_download(url, destination, 5, sleep=waits.append)
    assert destination.read_bytes() == data
    assert ranges_requested(http_server) == [None, "bytes=1500-"]
    assert waits == [2]
    assert os.listdir(tmp_path) == ["f"]


def test_download_resumes_after_several_cuts(http_server, tmp_path):
    data = big_data(5000)
    url = http_server.serve("/f", data)
    http_server.cut_connection_after("/f", 1000, times=3)
    waits = []
    destination = tmp_path / "f"
    http.simple_download(url, destination, 5, sleep=waits.append)
    assert destination.read_bytes() == data
    assert ranges_requested(http_server) == [
        None,
        "bytes=1000-",
        "bytes=2000-",
        "bytes=3000-",
    ]
    assert waits == [2, 4, 8]


def test_download_resumes_after_a_cut_with_nothing_received(http_server, tmp_path):
    data = big_data(3000)
    url = http_server.serve("/f", data)
    http_server.cut_connection_after("/f", 0, times=1)
    destination = tmp_path / "f"
    http.simple_download(url, destination, 5, sleep=lambda seconds: None)
    assert destination.read_bytes() == data
    # Nothing was written, so the retry is a plain request again.
    assert ranges_requested(http_server) == [None, None]


def test_download_gives_up_after_max_retries(http_server, tmp_path):
    url = http_server.serve("/f", big_data(10))
    http_server.cut_connection_after("/f", 1)
    waits = []
    with pytest.raises(NetworkError) as excinfo:
        http.simple_download(
            url, tmp_path / "f", 5, max_retries=3, sleep=waits.append
        )
    assert excinfo.value.exit_code == ExitCode.NETWORK_ERROR
    assert len(http_server.requests) == 4  # the first attempt plus 3 retries
    assert waits == [2, 4, 8]
    assert (tmp_path / "f").read_bytes() == big_data(10)[:4]


def test_default_retries_wait_without_real_time(http_server, tmp_path):
    url = http_server.serve("/f", big_data(100))
    http_server.cut_connection_after("/f", 1)
    waits = []
    with pytest.raises(NetworkError):
        http.simple_download(url, tmp_path / "f", 5, sleep=waits.append)
    assert waits == [2, 4, 8, 16, 32]
    assert len(http_server.requests) == 6


def test_no_retries_when_max_retries_is_zero(http_server, tmp_path):
    url = http_server.serve("/f", big_data(100))
    http_server.cut_connection_after("/f", 10)
    waits = []
    with pytest.raises(NetworkError):
        http.simple_download(
            url, tmp_path / "f", 5, max_retries=0, sleep=waits.append
        )
    assert waits == []
    assert len(http_server.requests) == 1


def test_resume_against_a_server_without_ranges_is_incompatible(
    http_server, tmp_path
):
    url = http_server.serve("/f", big_data(5000))
    http_server.cut_connection_after("/f", 1500, times=1)
    http_server.ignore_range("/f")
    with pytest.raises(ServerIncompatibleError):
        http.simple_download(url, tmp_path / "f", 5, sleep=lambda seconds: None)
    assert (tmp_path / "f").read_bytes() == big_data(5000)[:1500]


def test_resume_with_a_different_total_is_incompatible(http_server, tmp_path):
    url = http_server.serve("/f", big_data(5000))
    http_server.cut_connection_after("/f", 1500, times=1)
    http_server.report_total("/f", 9999)
    with pytest.raises(ServerIncompatibleError):
        http.simple_download(url, tmp_path / "f", 5, sleep=lambda seconds: None)


def test_resume_with_content_encoding_is_incompatible(http_server, tmp_path):
    url = http_server.serve("/f", big_data(5000))
    http_server.cut_connection_after("/f", 1500, times=1)
    http_server.set_content_encoding("/f", "gzip")
    with pytest.raises(ServerIncompatibleError):
        http.simple_download(url, tmp_path / "f", 5, sleep=lambda seconds: None)


def test_errors_of_the_first_request_are_not_retried(http_server, tmp_path):
    waits = []
    with pytest.raises(SourceError):
        http.simple_download(
            http_server.url("/missing"), tmp_path / "f", 5, sleep=waits.append
        )
    assert waits == []
    assert len(http_server.requests) == 1
