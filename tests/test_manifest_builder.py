import hashlib
import math

import pytest

from chunkget import config, manifest_builder

ALGORITHMS = ["sha256", "sha384", "sha512", "sha3_256", "sha3_512"]


def sample_data(size):
    return bytes((index * 7 + 3) % 251 for index in range(size))


def write(tmp_path, data):
    path = tmp_path / "source.bin"
    path.write_bytes(data)
    return path


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_chunk_hashes_and_global_hash_match_hashlib(tmp_path, algorithm):
    size, chunk_size = 2500, 1000
    data = sample_data(size)
    path = write(tmp_path, data)

    chunks, global_hash = manifest_builder.compute_chunks(
        path, chunk_size, algorithm
    )

    assert len(chunks) == math.ceil(size / chunk_size)
    for index, chunk in enumerate(chunks):
        start = index * chunk_size
        end = min(start + chunk_size, size)
        piece = data[start:end]
        assert (chunk.id, chunk.start, chunk.end) == (index, start, end)
        assert chunk.hash == algorithm + ":" + hashlib.new(algorithm, piece).hexdigest()
    assert global_hash == algorithm + ":" + hashlib.new(algorithm, data).hexdigest()


def test_chunks_are_not_aligned_with_the_read_buffer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BUFFER_SIZE", 300)
    data = sample_data(2500)
    path = write(tmp_path, data)

    chunks, global_hash = manifest_builder.compute_chunks(path, 1000, "sha256")

    assert [c.hash for c in chunks] == [
        "sha256:" + hashlib.sha256(data[i : i + 1000]).hexdigest()
        for i in range(0, 2500, 1000)
    ]
    assert global_hash == "sha256:" + hashlib.sha256(data).hexdigest()


def test_file_is_opened_and_read_only_once(tmp_path, monkeypatch):
    path = write(tmp_path, sample_data(2500))
    opened = []
    real_open = open

    def counting_open(*args, **kwargs):
        opened.append(args[0])
        return real_open(*args, **kwargs)

    monkeypatch.setattr(manifest_builder, "open", counting_open, raising=False)
    manifest_builder.compute_chunks(path, 1000, "sha256")
    assert len(opened) == 1


# --- Edge cases (T20) ---


def spans(chunks):
    return [(c.id, c.start, c.end) for c in chunks]


@pytest.mark.parametrize("algorithm", ALGORITHMS)
def test_empty_file_has_no_chunks_and_hash_of_empty_string(tmp_path, algorithm):
    path = write(tmp_path, b"")
    chunks, global_hash = manifest_builder.compute_chunks(path, 1000, algorithm)
    assert chunks == ()
    assert global_hash == algorithm + ":" + hashlib.new(algorithm, b"").hexdigest()


def test_file_smaller_than_chunk_has_one_chunk(tmp_path):
    data = sample_data(10)
    chunks, global_hash = manifest_builder.compute_chunks(
        write(tmp_path, data), 1000, "sha256"
    )
    assert spans(chunks) == [(0, 0, 10)]
    assert chunks[0].hash == global_hash == "sha256:" + hashlib.sha256(data).hexdigest()


def test_file_that_is_an_exact_multiple_has_no_empty_last_chunk(tmp_path):
    data = sample_data(3000)
    chunks, _ = manifest_builder.compute_chunks(
        write(tmp_path, data), 1000, "sha256"
    )
    assert spans(chunks) == [(0, 0, 1000), (1, 1000, 2000), (2, 2000, 3000)]
    assert chunks[2].hash == "sha256:" + hashlib.sha256(data[2000:]).hexdigest()


def test_last_chunk_is_shorter(tmp_path):
    data = sample_data(2001)
    chunks, _ = manifest_builder.compute_chunks(
        write(tmp_path, data), 1000, "sha256"
    )
    assert spans(chunks) == [(0, 0, 1000), (1, 1000, 2000), (2, 2000, 2001)]
    assert chunks[2].hash == "sha256:" + hashlib.sha256(data[2000:]).hexdigest()


def test_file_of_exactly_one_chunk(tmp_path):
    chunks, _ = manifest_builder.compute_chunks(
        write(tmp_path, sample_data(1000)), 1000, "sha256"
    )
    assert spans(chunks) == [(0, 0, 1000)]


# --- build_manifest (T21) ---

from chunkget import events
from chunkget.errors import ManifestInvalidError, UsageError
from chunkget.manifest import PROTOCOL_VERSION, Manifest, load_manifest

URL = "http://127.0.0.1:8000/source.bin"


def test_defaults_are_100_mib_and_sha256(tmp_path):
    data = sample_data(2500)
    manifest = manifest_builder.build_manifest(write(tmp_path, data), URL)
    assert isinstance(manifest, Manifest)
    assert manifest.chunk_size == 100 * 1024 * 1024
    assert manifest.global_hash == "sha256:" + hashlib.sha256(data).hexdigest()
    assert len(manifest.chunks) == 1


def test_manifest_fields(tmp_path):
    data = sample_data(2500)
    manifest = manifest_builder.build_manifest(
        write(tmp_path, data), URL, chunk_size=1000, algorithm="sha512"
    )
    assert manifest.protocol_version == PROTOCOL_VERSION
    assert manifest.name == "source.bin"
    assert manifest.url == URL
    assert manifest.size == 2500
    assert manifest.chunk_size == 1000
    assert manifest.global_hash.startswith("sha512:")
    assert len(manifest.chunks) == 3


def test_manifest_passes_validation(tmp_path):
    manifest = manifest_builder.build_manifest(
        write(tmp_path, sample_data(2500)), URL, chunk_size=1000
    )
    assert load_manifest(manifest.to_json().encode("utf-8")) == manifest


def test_empty_file_manifest_is_valid(tmp_path):
    manifest = manifest_builder.build_manifest(write(tmp_path, b""), URL)
    assert manifest.size == 0
    assert manifest.chunks == ()


def test_unsupported_algorithm_is_a_usage_error(tmp_path):
    with pytest.raises(UsageError):
        manifest_builder.build_manifest(
            write(tmp_path, b"x"), URL, algorithm="md5"
        )


def test_invalid_chunk_size_is_a_usage_error(tmp_path):
    with pytest.raises(UsageError):
        manifest_builder.build_manifest(write(tmp_path, b"x"), URL, chunk_size=0)


def test_invalid_url_is_rejected(tmp_path):
    with pytest.raises(ManifestInvalidError):
        manifest_builder.build_manifest(write(tmp_path, b"x"), "ftp://host/x")


def test_listener_receives_one_event_per_chunk(tmp_path):
    received = []
    manifest_builder.build_manifest(
        write(tmp_path, sample_data(2500)),
        URL,
        chunk_size=1000,
        listener=received.append,
    )
    assert received == [
        events.ChunkDone(index=0, total=3, bytes=1000),
        events.ChunkDone(index=1, total=3, bytes=1000),
        events.ChunkDone(index=2, total=3, bytes=500),
    ]
