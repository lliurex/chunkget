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


# --- Injectable status and header faults (T24) ---


def test_server_can_ignore_range(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.ignore_range("/file.bin")
    with fetch(url, {"Range": "bytes=2-5"}) as response:
        assert response.status == 200
        assert response.headers["Content-Range"] is None
        assert response.read() == DATA


def test_server_can_report_a_different_total(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.report_total("/file.bin", 999)
    with fetch(url, {"Range": "bytes=2-5"}) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 2-5/999"
        assert response.read() == DATA[2:6]


def test_server_can_add_content_encoding(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.set_content_encoding("/file.bin", "gzip")
    with fetch(url, {"Range": "bytes=2-5"}) as response:
        assert response.status == 206
        assert response.headers["Content-Encoding"] == "gzip"


def test_other_paths_are_not_affected_by_faults(http_server):
    http_server.serve("/a.bin", DATA)
    other = http_server.serve("/b.bin", DATA)
    http_server.ignore_range("/a.bin")
    http_server.report_total("/a.bin", 1)
    http_server.set_content_encoding("/a.bin", "gzip")
    with fetch(other, {"Range": "bytes=2-5"}) as response:
        assert response.status == 206
        assert response.headers["Content-Range"] == "bytes 2-5/1024"
        assert response.headers["Content-Encoding"] is None


def test_status_sequence_is_consumed_one_per_request(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.respond_with_statuses("/file.bin", [404, 429, 503])
    codes = []
    for _ in range(3):
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            fetch(url, {"Range": "bytes=0-9"})
        codes.append(excinfo.value.code)
    assert codes == [404, 429, 503]
    with fetch(url, {"Range": "bytes=0-9"}) as response:
        assert response.status == 206
        assert response.read() == DATA[:10]
    assert len(http_server.requests) == 4


def test_status_sequence_applies_to_paths_without_resource(http_server):
    http_server.respond_with_statuses("/nothing", [503])
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        fetch(http_server.url("/nothing"))
    assert excinfo.value.code == 503


def test_server_can_redirect_to_another_scheme(http_server):
    http_server.serve("/file.bin", DATA)
    http_server.redirect("/file.bin", "file:///etc/passwd")
    connection = http.client.HTTPConnection("127.0.0.1", http_server.port)
    try:
        connection.request("GET", "/file.bin")
        response = connection.getresponse()
        assert response.status == 302
        assert response.getheader("Location") == "file:///etc/passwd"
    finally:
        connection.close()


def test_redirect_to_http_url_is_followed_by_urllib(http_server):
    target = http_server.serve("/target.bin", DATA)
    http_server.serve("/file.bin", b"")
    http_server.redirect("/file.bin", target)
    with fetch(http_server.url("/file.bin")) as response:
        assert response.read() == DATA


def test_cut_can_be_limited_to_the_first_requests(http_server):
    url = http_server.serve("/file.bin", DATA)
    http_server.cut_connection_after("/file.bin", 10, times=2)
    for _attempt in range(2):
        with fetch(url) as response:
            with pytest.raises(http.client.IncompleteRead):
                response.read()
    with fetch(url) as response:
        assert response.read() == DATA


def test_on_request_hook_and_delay(http_server):
    import time
    import urllib.request

    url = http_server.serve("/f", b"data")
    seen = []
    http_server.on_request("/f", seen.append)
    http_server.delay("/f", 0.2)
    started = time.monotonic()
    urllib.request.urlopen(url, timeout=5).read()
    urllib.request.urlopen(url, timeout=5).read()
    assert seen == [1, 2]
    assert time.monotonic() - started >= 0.4
