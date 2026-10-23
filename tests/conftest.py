import pytest

from tests.helpers.http_server import HttpTestServer


@pytest.fixture
def http_server():
    with HttpTestServer() as server:
        yield server


@pytest.fixture(autouse=True)
def no_proxy_environment(monkeypatch):
    """Tests talk to 127.0.0.1 directly, whatever the environment says."""
    for name in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        monkeypatch.delenv(name, raising=False)
