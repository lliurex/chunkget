import pytest

from chunkget import downloader, manifest_builder
from chunkget.errors import ExitCode, ManifestInvalidError, SourceError

DATA_URL = "http://127.0.0.1:8000/image.iso"


@pytest.fixture
def manifest_file(tmp_path):
    """A manifest of a small file, written to disk. Returns (manifest, path)."""
    source = tmp_path / "image.iso"
    source.write_bytes(bytes(index % 251 for index in range(250)))
    manifest = manifest_builder.build_manifest(source, DATA_URL, chunk_size=100)
    path = tmp_path / "image.iso.chunkget.manifest"
    path.write_bytes(manifest.to_json().encode("utf-8"))
    return manifest, path


# --- Resolving the manifest: local path or URL (T43) ---


def test_local_path_returns_the_manifest(manifest_file):
    manifest, path = manifest_file
    assert downloader.resolve_manifest(str(path), 5) == manifest


def test_path_object_is_accepted(manifest_file):
    manifest, path = manifest_file
    assert downloader.resolve_manifest(path, 5) == manifest


def test_url_returns_the_same_manifest_as_the_path(manifest_file, http_server):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    from_url = downloader.resolve_manifest(url, 5)
    assert from_url == downloader.resolve_manifest(str(path), 5) == manifest


def test_url_makes_a_single_request(manifest_file, http_server):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    downloader.resolve_manifest(url, 5)
    assert [r.path for r in http_server.requests] == ["/m.manifest"]


def test_url_scheme_is_case_insensitive(manifest_file, http_server):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    assert downloader.resolve_manifest("HTTP" + url[4:], 5) == manifest


def test_url_with_404_is_a_source_error(http_server):
    with pytest.raises(SourceError) as excinfo:
        downloader.resolve_manifest(http_server.url("/missing"), 5)
    assert excinfo.value.exit_code == ExitCode.SOURCE_ERROR


def test_url_with_content_that_is_not_a_manifest(http_server):
    url = http_server.serve("/m.manifest", b"this is not a manifest")
    with pytest.raises(ManifestInvalidError) as excinfo:
        downloader.resolve_manifest(url, 5)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID


def test_url_with_a_json_that_is_not_a_valid_manifest(http_server):
    url = http_server.serve("/m.manifest", b'{"name": "x"}')
    with pytest.raises(ManifestInvalidError):
        downloader.resolve_manifest(url, 5)


def test_local_file_with_content_that_is_not_a_manifest(tmp_path):
    path = tmp_path / "m.manifest"
    path.write_bytes(b"garbage")
    with pytest.raises(ManifestInvalidError):
        downloader.resolve_manifest(path, 5)


def test_missing_local_file_is_a_source_error(tmp_path):
    with pytest.raises(SourceError):
        downloader.resolve_manifest(tmp_path / "missing", 5)


@pytest.mark.parametrize(
    "source",
    ["file:///etc/passwd", "ftp://example.com/m.manifest", "http://", "gopher://x/y"],
)
def test_urls_that_are_not_valid_http_urls_are_source_errors(source):
    with pytest.raises(SourceError):
        downloader.resolve_manifest(source, 5)


def test_path_with_a_colon_is_still_a_local_path(manifest_file, tmp_path):
    manifest, path = manifest_file
    odd = tmp_path / "a:b.manifest"
    odd.write_bytes(path.read_bytes())
    assert downloader.resolve_manifest(odd, 5) == manifest
