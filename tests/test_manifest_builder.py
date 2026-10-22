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
