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
    manifest = load_manifest(dump(chunks_document(150, chunk_size)))
    assert manifest.chunk_size == chunk_size


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


# --- load_manifest: chunk list (T17) ---


def chunks_document(size, chunk_size):
    """A consistent document for ``size`` bytes cut in ``chunk_size`` pieces."""
    data = copy.deepcopy(valid_data())
    data["size"] = size
    data["chunk_size"] = chunk_size
    data["chunks"] = [
        {
            "id": index,
            "start": start,
            "end": min(start + chunk_size, size),
            "hash": HASH_A,
        }
        for index, start in enumerate(range(0, size, chunk_size))
    ]
    return data


def test_empty_file_without_chunks_is_accepted():
    manifest = load_manifest(dump(chunks_document(0, 100)))
    assert manifest.size == 0
    assert manifest.chunks == ()


@pytest.mark.parametrize(
    "size, chunk_size, count",
    [(50, 100, 1), (100, 100, 1), (150, 100, 2), (300, 100, 3), (301, 100, 4)],
)
def test_consistent_chunk_lists_are_accepted(size, chunk_size, count):
    manifest = load_manifest(dump(chunks_document(size, chunk_size)))
    assert len(manifest.chunks) == count
    assert manifest.chunks[-1].end == size


def broken(function, size=150, chunk_size=100):
    data = chunks_document(size, chunk_size)
    function(data)
    return dump(data)


INVALID_CHUNK_LISTS = {
    "negative size": broken(lambda d: d.update(size=-1, chunks=[])),
    "size zero with chunks": broken(lambda d: d.update(size=0)),
    "id not starting at zero": broken(
        lambda d: [c.update(id=c["id"] + 1) for c in d["chunks"]]
    ),
    "id skipped": broken(lambda d: d["chunks"][1].update(id=2)),
    "id repeated": broken(lambda d: d["chunks"][1].update(id=0)),
    "first chunk not at zero": broken(lambda d: d["chunks"][0].update(start=1)),
    "gap between chunks": broken(lambda d: d["chunks"][1].update(start=101)),
    "overlap between chunks": broken(lambda d: d["chunks"][1].update(start=99)),
    "last end before size": broken(lambda d: d["chunks"][1].update(end=149)),
    "last end after size": broken(lambda d: d["chunks"][1].update(end=151)),
    "chunk larger than chunk_size": broken(
        lambda d: (
            d["chunks"][0].update(end=101),
            d["chunks"][1].update(start=101),
        )
    ),
    "empty chunk": broken(
        lambda d: (
            d["chunks"][0].update(end=0),
            d["chunks"][1].update(start=0, end=150),
        )
    ),
    "too few chunks": broken(
        lambda d: d["chunks"].pop(), size=250
    ),
    "too many chunks": broken(
        lambda d: d["chunks"].append(
            {"id": 2, "start": 150, "end": 150, "hash": HASH_A}
        )
    ),
    "no chunks for non-empty file": broken(lambda d: d.update(chunks=[])),
}


@pytest.mark.parametrize(
    "document", INVALID_CHUNK_LISTS.values(), ids=INVALID_CHUNK_LISTS.keys()
)
def test_inconsistent_chunk_lists_are_rejected(document):
    with pytest.raises(ManifestInvalidError) as excinfo:
        load_manifest(document)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID


def test_chunk_count_limit_is_inclusive():
    from chunkget.config import MAX_CHUNKS

    assert len(load_manifest(dump(chunks_document(MAX_CHUNKS, 1))).chunks) == (
        MAX_CHUNKS
    )
    with pytest.raises(ManifestInvalidError) as excinfo:
        load_manifest(dump(chunks_document(MAX_CHUNKS + 1, 1)))
    assert str(MAX_CHUNKS) in str(excinfo.value)


# --- load_manifest_file (T18) ---

import os

from chunkget import config
from chunkget.errors import SourceError
from chunkget.manifest import load_manifest_file


def test_round_trip_through_file(tmp_path):
    path = tmp_path / "m.chunkget.manifest"
    path.write_bytes(make_manifest().to_json().encode("utf-8"))
    assert load_manifest_file(path) == make_manifest()


def test_missing_file_is_a_source_error(tmp_path):
    with pytest.raises(SourceError) as excinfo:
        load_manifest_file(tmp_path / "missing")
    assert excinfo.value.exit_code == ExitCode.SOURCE_ERROR


def test_directory_is_a_source_error(tmp_path):
    with pytest.raises(SourceError):
        load_manifest_file(tmp_path)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_file_is_a_source_error(tmp_path):
    path = tmp_path / "m"
    path.write_bytes(make_manifest().to_json().encode("utf-8"))
    path.chmod(0)
    with pytest.raises(SourceError):
        load_manifest_file(path)


def test_file_over_the_size_limit_is_invalid(tmp_path):
    path = tmp_path / "big"
    with open(path, "wb") as handle:
        handle.truncate(config.MAX_MANIFEST_BYTES + 1)
    with pytest.raises(ManifestInvalidError) as excinfo:
        load_manifest_file(path)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID
    assert str(config.MAX_MANIFEST_BYTES) in str(excinfo.value)


def test_invalid_content_in_file_is_invalid(tmp_path):
    path = tmp_path / "m"
    path.write_bytes(b"not json")
    with pytest.raises(ManifestInvalidError):
        load_manifest_file(path)
