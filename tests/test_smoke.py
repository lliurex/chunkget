import chunkget


def test_package_has_version():
    assert isinstance(chunkget.__version__, str)
    assert chunkget.__version__
