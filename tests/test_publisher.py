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
