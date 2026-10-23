import urllib.error
import urllib.request

import pytest

from tests.helpers.http_server import HttpTestServer

DATA = bytes(range(256)) * 4  # 1024 bytes


def fetch(url, headers=None):
    # Bypass any proxy configured in the environment: tests use localhost only.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers=headers or {})
    return opener.open(request, timeout=5)


def test_range_request_returns_206_with_content_range(http_server):
    url = http_server.serve("/file.bin", DATA)
    with fetch(url, {"Range": "bytes=2-5"}) as response:
        assert response.status == 206
        assert response.read() == DATA[2:6]
        assert len(DATA[2:6]) == 4
        assert response.headers["Content-Range"] == "bytes 2-5/%d" % len(DATA)
        assert response.headers["Content-Length"] == "4"


def test_open_ended_range(http_server):
    url = http_server.serve("/file.bin", DATA)
    with fetch(url, {"Range": "bytes=1000-"}) as response:
        assert response.status == 206
        assert response.read() == DATA[1000:]
        assert response.headers["Content-Range"] == "bytes 1000-1023/1024"


def test_range_end_beyond_the_data_is_clamped(http_server):
    url = http_server.serve("/file.bin", DATA)
    with fetch(url, {"Range": "bytes=1020-5000"}) as response:
        assert response.status == 206
        assert response.read() == DATA[1020:]
        assert response.headers["Content-Range"] == "bytes 1020-1023/1024"


def test_request_without_range_returns_whole_resource(http_server):
    url = http_server.serve("/file.bin", DATA)
    with fetch(url) as response:
        assert response.status == 200
        assert response.read() == DATA
        assert response.headers["Accept-Ranges"] == "bytes"


def test_unsatisfiable_range_returns_416(http_server):
    url = http_server.serve("/file.bin", DATA)
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        fetch(url, {"Range": "bytes=5000-6000"})
    assert excinfo.value.code == 416
    assert excinfo.value.headers["Content-Range"] == "bytes */1024"


def test_unknown_path_returns_404(http_server):
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        fetch(http_server.url("/missing"))
    assert excinfo.value.code == 404


def test_server_listens_only_on_loopback(http_server):
    assert http_server.url("/x").startswith("http://127.0.0.1:")


def test_server_is_closed_after_stop():
    server = HttpTestServer()
    server.start()
    url = server.serve("/file.bin", DATA)
    with fetch(url) as response:
        assert response.read() == DATA
    server.stop()
    with pytest.raises(urllib.error.URLError):
        fetch(url)


def test_server_works_as_context_manager():
    with HttpTestServer() as server:
        url = server.serve("/file.bin", DATA)
        with fetch(url, {"Range": "bytes=0-0"}) as response:
            assert response.read() == DATA[:1]
    with pytest.raises(urllib.error.URLError):
        fetch(url)
