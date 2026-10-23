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
