import json

from chunkget.manifest import PROTOCOL_VERSION, Chunk, Manifest

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
GLOBAL = "sha256:" + "c" * 64


def make_manifest(name="image.iso"):
    return Manifest(
        protocol_version=PROTOCOL_VERSION,
        name=name,
        url="http://127.0.0.1/image.iso",
        size=150,
        chunk_size=100,
        global_hash=GLOBAL,
        chunks=(
            Chunk(id=0, start=0, end=100, hash=HASH_A),
            Chunk(id=1, start=100, end=150, hash=HASH_B),
        ),
    )


def test_protocol_version_is_one():
    assert PROTOCOL_VERSION == 1


def test_to_json_is_valid_json_with_exact_keys_in_order():
    data = json.loads(make_manifest().to_json())
    assert list(data) == [
        "protocol_version",
        "name",
        "url",
        "size",
        "chunk_size",
        "global_hash",
        "chunks",
    ]
    assert data["protocol_version"] == 1
    assert data["size"] == 150
    assert data["global_hash"] == GLOBAL
    for index, chunk in enumerate(data["chunks"]):
        assert list(chunk) == ["id", "start", "end", "hash"]
        assert chunk["id"] == index
    assert data["chunks"][1] == {
        "id": 1,
        "start": 100,
        "end": 150,
        "hash": HASH_B,
    }


def test_to_json_is_human_readable():
    text = make_manifest().to_json()
    lines = text.splitlines()
    assert len(lines) > 10
    assert '  "name": "image.iso",' in lines


def test_to_json_keeps_utf8_characters():
    text = make_manifest(name="ñandú.iso").to_json()
    assert "ñandú.iso" in text
    assert "\\u" not in text


def test_empty_file_manifest_serialises_empty_chunk_list():
    manifest = Manifest(
        protocol_version=PROTOCOL_VERSION,
        name="empty",
        url="http://127.0.0.1/empty",
        size=0,
        chunk_size=100,
        global_hash=GLOBAL,
        chunks=(),
    )
    assert json.loads(manifest.to_json())["chunks"] == []


# --- load_manifest: structure and types (T14) ---

import copy

import pytest

from chunkget.errors import ExitCode, ManifestInvalidError
from chunkget.manifest import load_manifest


def valid_data():
    return json.loads(make_manifest().to_json())


def dump(data):
    return json.dumps(data).encode("utf-8")


def test_load_valid_manifest():
    manifest = load_manifest(make_manifest().to_json().encode("utf-8"))
    assert manifest == make_manifest()


def test_load_valid_empty_file_manifest():
    data = valid_data()
    data.update(size=0, chunks=[])
    manifest = load_manifest(dump(data))
    assert manifest.size == 0
    assert manifest.chunks == ()


def mutate(function):
    data = copy.deepcopy(valid_data())
    function(data)
    return dump(data)


INVALID_DOCUMENTS = {
    "not json": b"this is not json",
    "empty": b"",
    "truncated": b'{"protocol_version": 1, "name": ',
    "invalid utf-8": b"\xff\xfe{}",
    "list instead of object": b"[]",
    "null": b"null",
    "missing top-level key": mutate(lambda d: d.pop("url")),
    "missing chunks": mutate(lambda d: d.pop("chunks")),
    "extra top-level key": mutate(lambda d: d.update(extra=1)),
    "missing chunk key": mutate(lambda d: d["chunks"][0].pop("hash")),
    "extra chunk key": mutate(lambda d: d["chunks"][0].update(extra=1)),
    "protocol_version as string": mutate(
        lambda d: d.update(protocol_version="1")
    ),
    "protocol_version as bool": mutate(
        lambda d: d.update(protocol_version=True)
    ),
    "name as number": mutate(lambda d: d.update(name=5)),
    "url as null": mutate(lambda d: d.update(url=None)),
    "size as string": mutate(lambda d: d.update(size="150")),
    "size as float": mutate(lambda d: d.update(size=150.0)),
    "chunk_size as list": mutate(lambda d: d.update(chunk_size=[100])),
    "global_hash as number": mutate(lambda d: d.update(global_hash=1)),
    "chunks as object": mutate(lambda d: d.update(chunks={})),
    "chunk as string": mutate(lambda d: d["chunks"].__setitem__(0, "x")),
    "chunk id as string": mutate(lambda d: d["chunks"][0].update(id="0")),
    "chunk start as float": mutate(
        lambda d: d["chunks"][0].update(start=0.5)
    ),
    "chunk end as bool": mutate(lambda d: d["chunks"][0].update(end=False)),
    "chunk hash as number": mutate(lambda d: d["chunks"][0].update(hash=7)),
}


@pytest.mark.parametrize(
    "document", INVALID_DOCUMENTS.values(), ids=INVALID_DOCUMENTS.keys()
)
def test_load_rejects_invalid_structure_or_types(document):
    with pytest.raises(ManifestInvalidError) as excinfo:
        load_manifest(document)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID


# --- load_manifest: version, name and URL (T15) ---


def load_with(**changes):
    data = copy.deepcopy(valid_data())
    data.update(changes)
    return load_manifest(dump(data))


def message_for(**changes):
    with pytest.raises(ManifestInvalidError) as excinfo:
        load_with(**changes)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID
    return str(excinfo.value)


def test_newer_and_older_versions_have_different_messages():
    newer = message_for(protocol_version=PROTOCOL_VERSION + 1)
    older = message_for(protocol_version=PROTOCOL_VERSION - 1)
    assert "unsupported" in newer
    assert "obsolete" in older
    assert newer != older


@pytest.mark.parametrize(
    "name",
    [
        "",
        ".",
        "..",
        "a/b",
        "/etc/passwd",
        "../x",
        "a\\b",
        "a\0b",
        "x" * 256,
        "ñ" * 128,  # 256 bytes in UTF-8
        "\ud800",  # not encodable in UTF-8
    ],
)
def test_invalid_names_are_rejected(name):
    message_for(name=name)


@pytest.mark.parametrize("name", ["a", "...", "x" * 255, "ñ" * 127 + "a", "a b.iso"])
def test_valid_names_are_accepted(name):
    assert load_with(name=name).name == name


@pytest.mark.parametrize(
    "url",
    [
        "",
        "image.iso",
        "ftp://example.com/image.iso",
        "file:///etc/passwd",
        "http://",
        "https:///path",
        "http:///image.iso",
        "//example.com/image.iso",
        "http://[::1/image.iso",
        "javascript:alert(1)",
    ],
)
def test_invalid_urls_are_rejected(url):
    message_for(url=url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/image.iso",
        "https://example.com:8443/a/b.iso?x=1",
        "HTTP://Example.com/x",
    ],
)
def test_valid_urls_are_accepted(url):
    assert load_with(url=url).url == url


# --- load_manifest: chunk_size and hashes (T16) ---

GIB = 1024 ** 3


def load_with_chunk_hashes(*hashes, global_hash=GLOBAL):
    data = copy.deepcopy(valid_data())
    data["global_hash"] = global_hash
    for chunk, value in zip(data["chunks"], hashes):
        chunk["hash"] = value
    return load_manifest(dump(data))


@pytest.mark.parametrize("chunk_size", [0, -1, GIB + 1])
def test_chunk_size_out_of_range_is_rejected(chunk_size):
    message = message_for(chunk_size=chunk_size)
    assert str(GIB) in message


@pytest.mark.parametrize("chunk_size", [1, 100, GIB])
def test_chunk_size_limits_are_accepted(chunk_size):
    assert load_with(chunk_size=chunk_size).chunk_size == chunk_size


def sha(name, text=b"x"):
    return name + ":" + hashlib.new(name, text).hexdigest()


import hashlib


@pytest.mark.parametrize("name", ["sha256", "sha384", "sha512", "sha3_256", "sha3_512"])
def test_consistent_algorithm_is_accepted(name):
    manifest = load_with_chunk_hashes(
        sha(name, b"a"), sha(name, b"b"), global_hash=sha(name)
    )
    assert manifest.global_hash == sha(name)


def test_mixed_algorithms_are_rejected():
    with pytest.raises(ManifestInvalidError):
        load_with_chunk_hashes(
            sha("sha512"), sha("sha512"), global_hash=sha("sha256")
        )


def test_mixed_algorithms_between_chunks_are_rejected():
    with pytest.raises(ManifestInvalidError):
        load_with_chunk_hashes(sha("sha256"), sha("sha512"))


@pytest.mark.parametrize("algorithm", ["md5", "sha1", "crc32"])
def test_unsupported_algorithm_is_rejected(algorithm):
    value = algorithm + ":" + "0" * 32
    with pytest.raises(ManifestInvalidError):
        load_with_chunk_hashes(value, value, global_hash=value)


@pytest.mark.parametrize(
    "bad",
    [
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 65,
        "sha256:",
        "sha256:" + "A" * 64,
        "sha256:" + "g" * 64,
        "a" * 64,
    ],
)
def test_malformed_hex_is_rejected_in_any_hash_field(bad):
    with pytest.raises(ManifestInvalidError):
        load_with_chunk_hashes(bad, HASH_B)
    with pytest.raises(ManifestInvalidError):
        load_with_chunk_hashes(HASH_A, bad)
    with pytest.raises(ManifestInvalidError):
        load_with_chunk_hashes(HASH_A, HASH_B, global_hash=bad)
