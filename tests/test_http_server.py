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


# --- Injectable data faults (T23) ---

import http.client


def test_connection_cut_after_n_bytes_truncates_the_read(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.cut_connection_after("/file.bin", 100)
    with fetch(url, {"Range": "bytes=0-499"}) as response:
        assert response.headers["Content-Length"] == "500"
        with pytest.raises(http.client.IncompleteRead) as excinfo:
            response.read()
    assert excinfo.value.partial == DATA[:100]


def test_connection_cut_also_applies_without_range(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.cut_connection_after("/file.bin", 10)
    with fetch(url) as response:
        with pytest.raises(http.client.IncompleteRead) as excinfo:
            response.read()
    assert excinfo.value.partial == DATA[:10]


def test_cut_only_affects_the_configured_path(http_server):
    http_server.serve("/a.bin", DATA)
    other = http_server.serve("/b.bin", DATA)
    http_server.cut_connection_after("/a.bin", 10)
    with fetch(other) as response:
        assert response.read() == DATA


def flipped(data):
    return bytes(byte ^ 0xFF for byte in data)


def test_chosen_chunk_is_corrupted(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.corrupt_range("/file.bin", 256, 512)
    with fetch(url, {"Range": "bytes=256-511"}) as response:
        body = response.read()
    assert len(body) == 256
    assert body != DATA[256:512]
    assert body == flipped(DATA[256:512])


def test_other_chunks_are_not_corrupted(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.corrupt_range("/file.bin", 256, 512)
    with fetch(url, {"Range": "bytes=0-255"}) as response:
        assert response.read() == DATA[:256]
    with fetch(url, {"Range": "bytes=512-1023"}) as response:
        assert response.read() == DATA[512:]


def test_corruption_only_changes_the_overlap_with_the_request(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.corrupt_range("/file.bin", 256, 512)
    with fetch(url, {"Range": "bytes=200-299"}) as response:
        body = response.read()
    assert body[:56] == DATA[200:256]
    assert body[56:] == flipped(DATA[256:300])


# --- Request log (T23) ---


def test_request_log_records_range_headers_in_order(http_server):
    url = http_server.serve("/file.bin", DATA)
    for header in ("bytes=0-9", "bytes=10-19"):
        with fetch(url, {"Range": header}) as response:
            response.read()
    with fetch(url) as response:
        response.read()
    assert [(r.path, r.range) for r in http_server.requests] == [
        ("/file.bin", "bytes=0-9"),
        ("/file.bin", "bytes=10-19"),
        ("/file.bin", None),
    ]


def test_request_log_records_other_headers_and_missing_paths(http_server):
    with pytest.raises(urllib.error.HTTPError):
        fetch(http_server.url("/missing"), {"X-Test": "1"})
    (record,) = http_server.requests
    assert record.path == "/missing"
    assert record.headers["X-Test"] == "1"
