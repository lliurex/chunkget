import hashlib

import pytest

from chunkget import hashing
from chunkget.errors import ManifestInvalidError, UsageError

ALGORITHMS = ["sha256", "sha384", "sha512", "sha3_256", "sha3_512"]


def test_supported_algorithms():
    assert list(hashing.SUPPORTED_ALGORITHMS) == ALGORITHMS


@pytest.mark.parametrize("name", ALGORITHMS)
def test_validate_algorithm_accepts_supported(name):
    assert hashing.validate_algorithm(name) == name


@pytest.mark.parametrize("name", ["md5", "sha1", "", "SHA256", "crc32"])
def test_validate_algorithm_rejects_others_listing_supported(name):
    with pytest.raises(UsageError) as excinfo:
        hashing.validate_algorithm(name)
    message = str(excinfo.value)
    for supported in ALGORITHMS:
        assert supported in message


@pytest.mark.parametrize("name", ALGORITHMS)
def test_format_and_parse_round_trip(name):
    hexdigest = hashlib.new(name, b"data").hexdigest()
    text = hashing.format_hash(name, hexdigest)
    assert text == name + ":" + hexdigest
    assert hashing.parse_hash(text) == (name, hexdigest)


@pytest.mark.parametrize("name", ALGORITHMS)
def test_hex_length_matches_algorithm(name):
    hexdigest = hashlib.new(name, b"").hexdigest()
    assert len(hexdigest) == hashing.hex_length(name)


def test_parse_hash_rejects_uppercase_hex():
    text = "sha256:" + hashlib.sha256(b"x").hexdigest().upper()
    with pytest.raises(ManifestInvalidError):
        hashing.parse_hash(text)


@pytest.mark.parametrize("name", ALGORITHMS)
def test_parse_hash_rejects_wrong_length(name):
    good = hashlib.new(name, b"x").hexdigest()
    for bad in (good[:-1], good + "0", ""):
        with pytest.raises(ManifestInvalidError):
            hashing.parse_hash(name + ":" + bad)


@pytest.mark.parametrize(
    "text",
    [
        "md5:" + hashlib.md5(b"x").hexdigest(),
        "sha1:" + hashlib.sha1(b"x").hexdigest(),
        "foo:" + "0" * 64,
        "0" * 64,
        ":" + "0" * 64,
        "sha256:" + "g" * 64,
        "",
    ],
)
def test_parse_hash_rejects_unknown_prefix_or_shape(text):
    with pytest.raises(ManifestInvalidError):
        hashing.parse_hash(text)


# --- Incremental hashing and file hashing (T12) ---

import io

from chunkget import config


class RecordingFile(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


@pytest.mark.parametrize("name", ALGORITHMS)
def test_incremental_hasher_matches_hashlib(name):
    hasher = hashing.Hasher(name)
    for part in (b"abc", b"", b"def" * 1000):
        hasher.update(part)
    assert hasher.hexdigest() == hashlib.new(
        name, b"abc" + b"def" * 1000
    ).hexdigest()


def test_hasher_rejects_unsupported_algorithm():
    with pytest.raises(UsageError):
        hashing.Hasher("md5")


@pytest.mark.parametrize("name", ALGORITHMS)
def test_hash_file_matches_hashlib_for_several_buffers(tmp_path, name):
    data = bytes(range(256)) * (3 * config.BUFFER_SIZE // 256) + b"tail"
    path = tmp_path / "data.bin"
    path.write_bytes(data)
    assert hashing.hash_file(path, name) == hashlib.new(name, data).hexdigest()


@pytest.mark.parametrize("name", ALGORITHMS)
def test_hash_file_of_empty_file(tmp_path, name):
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")
    assert hashing.hash_file(path, name) == hashlib.new(name, b"").hexdigest()


def test_hash_file_reads_at_most_one_buffer_per_call(monkeypatch, tmp_path):
    data = b"x" * (5 * 1024 * 1024)
    fake = RecordingFile(data)
    monkeypatch.setattr(hashing, "open", lambda *a, **k: fake, raising=False)
    result = hashing.hash_file(tmp_path / "ignored", "sha256")
    assert result == hashlib.sha256(data).hexdigest()
    assert fake.read_sizes
    assert all(0 < size <= 1024 * 1024 for size in fake.read_sizes)
