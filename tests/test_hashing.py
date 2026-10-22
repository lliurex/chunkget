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
