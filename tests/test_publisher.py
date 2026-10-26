import hashlib

import pytest

from chunkget import events, manifest, publisher
from chunkget.errors import UsageError

URL = "http://127.0.0.1:8000/image.iso"
CONTENT = bytes(index % 251 for index in range(250))


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "image.iso"
    path.write_bytes(CONTENT)
    return path


# --- make-manifest from a local file: writing (T60) ---


def test_manifest_is_written_and_loads_with_the_right_hashes(source, tmp_path):
    output = tmp_path / "out.manifest"
    result = publisher.make_manifest(source, URL, output, chunk_size=100)
    assert result == output
    loaded = manifest.load_manifest_file(output)
    assert loaded.name == "image.iso"
    assert loaded.url == URL
    assert loaded.size == 250
    assert loaded.chunk_size == 100
    assert loaded.global_hash == "sha256:" + hashlib.sha256(CONTENT).hexdigest()
    assert [(c.start, c.end) for c in loaded.chunks] == [(0, 100), (100, 200), (200, 250)]
    for chunk in loaded.chunks:
        part = CONTENT[chunk.start : chunk.end]
        assert chunk.hash == "sha256:" + hashlib.sha256(part).hexdigest()


def test_default_output_is_in_the_current_directory(source, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    result = publisher.make_manifest(source, URL, chunk_size=100)
    assert str(result) == "image.iso.chunkget.manifest"
    assert (work / "image.iso.chunkget.manifest").exists()
    assert [p.name for p in work.iterdir()] == ["image.iso.chunkget.manifest"]


def test_defaults_are_used_for_chunk_size_and_algorithm(source, tmp_path):
    output = publisher.make_manifest(source, URL, tmp_path / "m")
    loaded = manifest.load_manifest_file(output)
    assert loaded.chunk_size == 100 * 1024 * 1024
    assert loaded.global_hash.startswith("sha256:")
    assert len(loaded.chunks) == 1


def test_algorithm_option_is_honoured(source, tmp_path):
    output = publisher.make_manifest(
        source, URL, tmp_path / "m", chunk_size=100, algorithm="sha3_256"
    )
    assert manifest.load_manifest_file(output).global_hash.startswith("sha3_256:")


def test_unsupported_algorithm_writes_nothing(source, tmp_path):
    output = tmp_path / "m"
    with pytest.raises(UsageError):
        publisher.make_manifest(source, URL, output, algorithm="md5")
    assert not output.exists()


def test_empty_file(tmp_path):
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    output = publisher.make_manifest(empty, URL, tmp_path / "m", chunk_size=100)
    loaded = manifest.load_manifest_file(output)
    assert (loaded.size, loaded.chunks) == (0, ())


def test_progress_events_reach_the_listener(source, tmp_path):
    received = []
    publisher.make_manifest(
        source, URL, tmp_path / "m", chunk_size=100, listener=received.append
    )
    assert [e.index for e in received if isinstance(e, events.ChunkDone)] == [0, 1, 2]


def test_manifest_is_written_only_at_the_end(source, tmp_path):
    output = tmp_path / "m"
    seen = []

    def listener(event):
        seen.append(output.exists())

    publisher.make_manifest(source, URL, output, chunk_size=100, listener=listener)
    assert seen and not any(seen)
    assert output.exists()


def test_invalid_url_is_rejected_and_nothing_is_written(source, tmp_path):
    from chunkget.errors import ManifestInvalidError

    output = tmp_path / "m"
    with pytest.raises(ManifestInvalidError):
        publisher.make_manifest(source, "ftp://example.com/x", output, chunk_size=100)
    assert not output.exists()


def test_existing_output_is_not_silently_replaced(source, tmp_path):
    from chunkget.errors import OutputExistsError

    output = tmp_path / "m"
    output.write_text("previous")
    with pytest.raises(OutputExistsError):
        publisher.make_manifest(source, URL, output, chunk_size=100)
    assert output.read_text() == "previous"


# --- Overwriting the output manifest (T61) ---

from chunkget.errors import ExitCode, InterruptedByUser, OutputExistsError


def test_without_overwrite_the_existing_file_does_not_change(source, tmp_path):
    output = tmp_path / "m"
    output.write_bytes(b"previous content")
    with pytest.raises(OutputExistsError) as excinfo:
        publisher.make_manifest(source, URL, output, chunk_size=100, overwrite=False)
    assert excinfo.value.exit_code == ExitCode.USER_DECLINED
    assert output.read_bytes() == b"previous content"


def test_overwrite_defaults_to_false(source, tmp_path):
    output = tmp_path / "m"
    output.write_bytes(b"previous content")
    with pytest.raises(OutputExistsError):
        publisher.make_manifest(source, URL, output, chunk_size=100)


def test_with_overwrite_the_file_is_replaced(source, tmp_path):
    output = tmp_path / "m"
    output.write_bytes(b"previous content " * 1000)  # longer than the manifest
    publisher.make_manifest(source, URL, output, chunk_size=100, overwrite=True)
    loaded = manifest.load_manifest_file(output)
    assert loaded.size == 250
    assert output.read_bytes() == loaded.to_json().encode("utf-8")


def test_with_overwrite_and_no_existing_file_it_is_just_written(source, tmp_path):
    output = tmp_path / "m"
    publisher.make_manifest(source, URL, output, chunk_size=100, overwrite=True)
    assert manifest.load_manifest_file(output).size == 250


def test_overwrite_with_the_same_content_is_harmless(source, tmp_path):
    output = tmp_path / "m"
    publisher.make_manifest(source, URL, output, chunk_size=100)
    first = output.read_bytes()
    publisher.make_manifest(source, URL, output, chunk_size=100, overwrite=True)
    assert output.read_bytes() == first


def test_failure_while_computing_leaves_the_previous_manifest_intact(source, tmp_path):
    output = tmp_path / "m"
    output.write_bytes(b"previous content")

    def fail_midway(event):
        if event.index == 1:
            raise InterruptedByUser("stop")

    with pytest.raises(InterruptedByUser):
        publisher.make_manifest(
            source, URL, output, chunk_size=100, overwrite=True, listener=fail_midway
        )
    assert output.read_bytes() == b"previous content"


def test_the_replaced_file_is_written_only_after_everything_is_computed(
    source, tmp_path
):
    output = tmp_path / "m"
    output.write_bytes(b"previous content")
    seen = []

    def listener(event):
        seen.append(output.read_bytes())

    publisher.make_manifest(
        source, URL, output, chunk_size=100, overwrite=True, listener=listener
    )
    assert seen == [b"previous content"] * 3
    assert output.read_bytes() != b"previous content"


# --- Errors of a local source (T62) ---

import os

from chunkget.errors import SourceError


def make(source, tmp_path, **kwargs):
    return publisher.make_manifest(source, URL, tmp_path / "out.manifest", **kwargs)


def assert_source_error(error, tmp_path):
    assert error.value.exit_code == ExitCode.SOURCE_ERROR
    assert str(error.value)
    assert list(tmp_path.glob("*.manifest")) == []


def test_missing_source_is_a_source_error(tmp_path):
    with pytest.raises(SourceError) as error:
        make(tmp_path / "missing.iso", tmp_path)
    assert_source_error(error, tmp_path)
    assert "missing.iso" in str(error.value)


def test_directory_as_source_is_a_source_error(tmp_path):
    directory = tmp_path / "a_directory"
    directory.mkdir()
    with pytest.raises(SourceError) as error:
        make(directory, tmp_path)
    assert_source_error(error, tmp_path)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_source_is_a_source_error(source, tmp_path):
    source.chmod(0)
    try:
        with pytest.raises(SourceError) as error:
            make(source, tmp_path)
    finally:
        source.chmod(0o644)
    assert_source_error(error, tmp_path)


def test_missing_source_does_not_touch_an_existing_output(tmp_path):
    output = tmp_path / "out.manifest"
    output.write_bytes(b"previous")
    with pytest.raises(SourceError):
        make(tmp_path / "missing.iso", tmp_path, overwrite=True)
    assert output.read_bytes() == b"previous"


def test_error_message_is_translatable(tmp_path):
    from chunkget import i18n

    class Shout:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return one.upper() if n == 1 else many.upper()

    previous = i18n.get_translation()
    i18n.set_translation(Shout())
    try:
        with pytest.raises(SourceError) as error:
            make(tmp_path / "missing.iso", tmp_path)
    finally:
        i18n.set_translation(previous)
    assert str(error.value).startswith("«T»cannot read")


# --- Remote source: download or use a local file (T63) ---

from chunkget.errors import DestinationExistsError


@pytest.fixture
def served(http_server):
    return http_server.serve("/remote.iso", CONTENT)


def from_url(url, tmp_path, **kwargs):
    options = dict(output=tmp_path / "out.manifest", chunk_size=100, timeout=5)
    options.update(kwargs)
    return publisher.make_manifest_from_url(url, **options)


def check_manifest(path, url, name):
    loaded = manifest.load_manifest_file(path)
    assert loaded.url == url
    assert loaded.name == name
    assert loaded.size == 250
    assert loaded.global_hash == "sha256:" + hashlib.sha256(CONTENT).hexdigest()
    for chunk in loaded.chunks:
        part = CONTENT[chunk.start : chunk.end]
        assert chunk.hash == "sha256:" + hashlib.sha256(part).hexdigest()


def test_download_then_manifest(served, tmp_path):
    target = tmp_path / "files" / "my_copy.iso"
    target.parent.mkdir()
    output = from_url(served, tmp_path, download_to=target)
    assert target.read_bytes() == CONTENT
    check_manifest(output, served, "my_copy.iso")


def test_url_of_the_manifest_is_the_origin_not_the_local_path(served, tmp_path):
    target = tmp_path / "copy.iso"
    output = from_url(served, tmp_path, download_to=target)
    assert manifest.load_manifest_file(output).url == served


def test_existing_local_file_is_used_without_downloading(served, http_server, tmp_path):
    local = tmp_path / "already_here.iso"
    local.write_bytes(CONTENT)
    output = from_url(served, tmp_path, local_file=local)
    check_manifest(output, served, "already_here.iso")
    assert http_server.requests == []


def test_local_file_that_does_not_match_the_server_is_still_hashed_as_is(
    served, tmp_path
):
    local = tmp_path / "other.iso"
    local.write_bytes(b"different")
    output = from_url(served, tmp_path, local_file=local)
    assert manifest.load_manifest_file(output).size == 9


def test_exactly_one_of_download_to_and_local_file_is_needed(served, tmp_path):
    with pytest.raises(ValueError):
        from_url(served, tmp_path)
    with pytest.raises(ValueError):
        from_url(
            served, tmp_path, download_to=tmp_path / "a", local_file=tmp_path / "b"
        )


def test_existing_download_target_needs_confirmation(served, http_server, tmp_path):
    target = tmp_path / "copy.iso"
    target.write_bytes(b"precious")
    with pytest.raises(DestinationExistsError) as excinfo:
        from_url(served, tmp_path, download_to=target)
    assert excinfo.value.exit_code == ExitCode.USER_DECLINED
    assert target.read_bytes() == b"precious"
    assert http_server.requests == []
    assert not (tmp_path / "out.manifest").exists()


def test_overwrite_download_replaces_the_target(served, tmp_path):
    target = tmp_path / "copy.iso"
    target.write_bytes(b"precious " * 100)
    output = from_url(served, tmp_path, download_to=target, overwrite_download=True)
    assert target.read_bytes() == CONTENT
    check_manifest(output, served, "copy.iso")


def test_interrupted_download_is_resumed_before_the_manifest(
    served, http_server, tmp_path
):
    http_server.cut_connection_after("/remote.iso", 40, times=1)
    target = tmp_path / "copy.iso"
    waits = []
    output = from_url(served, tmp_path, download_to=target, sleep=waits.append)
    assert waits == [2]
    check_manifest(output, served, "copy.iso")


def test_download_that_keeps_failing_writes_no_manifest(served, http_server, tmp_path):
    from chunkget.errors import NetworkError

    http_server.cut_connection_after("/remote.iso", 40)
    with pytest.raises(NetworkError):
        from_url(
            served,
            tmp_path,
            download_to=tmp_path / "copy.iso",
            max_retries=2,
            sleep=lambda seconds: None,
        )
    assert not (tmp_path / "out.manifest").exists()


def test_other_schemes_are_rejected(tmp_path):
    with pytest.raises(SourceError):
        from_url("file:///etc/passwd", tmp_path, download_to=tmp_path / "x")


def test_output_options_are_honoured(served, tmp_path):
    local = tmp_path / "f.iso"
    local.write_bytes(CONTENT)
    output = from_url(
        served, tmp_path, local_file=local, algorithm="sha3_256", chunk_size=50
    )
    loaded = manifest.load_manifest_file(output)
    assert loaded.global_hash.startswith("sha3_256:")
    assert len(loaded.chunks) == 5


def test_existing_output_manifest_is_protected(served, tmp_path):
    local = tmp_path / "f.iso"
    local.write_bytes(CONTENT)
    (tmp_path / "out.manifest").write_bytes(b"previous")
    with pytest.raises(OutputExistsError):
        from_url(served, tmp_path, local_file=local)
    from_url(served, tmp_path, local_file=local, overwrite=True)
    check_manifest(tmp_path / "out.manifest", served, "f.iso")


# --- Errors of a remote source (T64) ---

import socket


def assert_remote_source_error(error, tmp_path):
    assert error.value.exit_code == ExitCode.SOURCE_ERROR
    assert str(error.value)
    assert list(tmp_path.glob("*.manifest")) == []


def test_404_is_a_source_error(http_server, tmp_path):
    target = tmp_path / "copy.iso"
    with pytest.raises(SourceError) as error:
        from_url(http_server.url("/missing"), tmp_path, download_to=target)
    assert_remote_source_error(error, tmp_path)
    assert not target.exists()


def test_host_that_does_not_resolve_is_a_source_error(monkeypatch, tmp_path):
    def no_such_host(*args, **kwargs):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_such_host)
    with pytest.raises(SourceError) as error:
        from_url("http://no-such-host.example/file.iso", tmp_path,
                 download_to=tmp_path / "copy.iso")
    assert_remote_source_error(error, tmp_path)


def test_connection_refused_is_a_source_error(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with pytest.raises(SourceError) as error:
        from_url("http://127.0.0.1:%d/file.iso" % port, tmp_path,
                 download_to=tmp_path / "copy.iso")
    assert_remote_source_error(error, tmp_path)


def test_timeout_is_a_source_error(tmp_path):
    # Accepts connections in the kernel backlog but never answers.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        url = "http://127.0.0.1:%d/file.iso" % silent.getsockname()[1]
        with pytest.raises(SourceError) as error:
            from_url(url, tmp_path, download_to=tmp_path / "copy.iso", timeout=0.2)
    assert_remote_source_error(error, tmp_path)


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "http:///x"])
def test_scheme_not_allowed_or_missing_host_is_a_source_error(url, tmp_path):
    with pytest.raises(SourceError) as error:
        from_url(url, tmp_path, download_to=tmp_path / "copy.iso")
    assert_remote_source_error(error, tmp_path)
    assert not (tmp_path / "copy.iso").exists()


def test_redirect_to_another_scheme_is_a_source_error(http_server, tmp_path):
    http_server.redirect("/r.iso", "file:///etc/passwd")
    with pytest.raises(SourceError) as error:
        from_url(http_server.url("/r.iso"), tmp_path, download_to=tmp_path / "c.iso")
    assert_remote_source_error(error, tmp_path)


def test_errors_with_a_local_file_option_do_not_apply_to_the_url(
    http_server, tmp_path
):
    # With a local copy the URL is only recorded, never contacted.
    local = tmp_path / "f.iso"
    local.write_bytes(CONTENT)
    output = from_url(http_server.url("/missing"), tmp_path, local_file=local)
    assert manifest.load_manifest_file(output).url == http_server.url("/missing")


def test_missing_local_file_with_a_remote_source_is_a_source_error(
    http_server, tmp_path
):
    with pytest.raises(SourceError) as error:
        from_url(http_server.url("/x"), tmp_path, local_file=tmp_path / "missing.iso")
    assert_remote_source_error(error, tmp_path)
