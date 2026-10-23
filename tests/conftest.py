import pytest

from tests.helpers.http_server import HttpTestServer


@pytest.fixture
def http_server():
    with HttpTestServer() as server:
        yield server
