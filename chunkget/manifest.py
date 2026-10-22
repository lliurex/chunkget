"""Manifest model and serialisation (plan section 4)."""

import dataclasses
import json
import urllib.parse
from typing import Tuple

from chunkget import config, hashing
from chunkget.errors import ManifestInvalidError

PROTOCOL_VERSION = 1
MAX_NAME_BYTES = 255


@dataclasses.dataclass(frozen=True)
class Chunk:
    """A chunk; ``start`` is inclusive, ``end`` exclusive."""

    id: int
    start: int
    end: int
    hash: str


@dataclasses.dataclass(frozen=True)
class Manifest:
    protocol_version: int
    name: str
    url: str
    size: int
    chunk_size: int
    global_hash: str
    chunks: Tuple[Chunk, ...]

    def to_json(self):
        """Serialise with the key order of the plan, indented and in UTF-8."""
        data = {
            "protocol_version": self.protocol_version,
            "name": self.name,
            "url": self.url,
            "size": self.size,
            "chunk_size": self.chunk_size,
            "global_hash": self.global_hash,
            "chunks": [
                {
                    "id": chunk.id,
                    "start": chunk.start,
                    "end": chunk.end,
                    "hash": chunk.hash,
                }
                for chunk in self.chunks
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


_TOP_LEVEL_TYPES = (
    ("protocol_version", int),
    ("name", str),
    ("url", str),
    ("size", int),
    ("chunk_size", int),
    ("global_hash", str),
    ("chunks", list),
)

_CHUNK_TYPES = (("id", int), ("start", int), ("end", int), ("hash", str))


def _check_object(value, fields, what):
    """Require a dict with exactly ``fields`` and values of the given types."""
    if not isinstance(value, dict):
        raise ManifestInvalidError(
            "invalid manifest: {what} must be a JSON object", what=what
        )
    expected = [key for key, _ in fields]
    if set(value) != set(expected):
        missing = [key for key in expected if key not in value]
        extra = sorted(set(value) - set(expected))
        raise ManifestInvalidError(
            "invalid manifest: {what} has missing keys {missing} and "
            "unexpected keys {extra}",
            what=what,
            missing=missing,
            extra=extra,
        )
    for key, expected_type in fields:
        item = value[key]
        # bool is a subclass of int but is never a valid number here.
        if not isinstance(item, expected_type) or isinstance(item, bool):
            raise ManifestInvalidError(
                "invalid manifest: key {key!r} of {what} has the wrong type",
                key=key,
                what=what,
            )


def _check_version(version):
    if version > PROTOCOL_VERSION:
        raise ManifestInvalidError(
            "unsupported manifest version {version}: this program supports "
            "version {supported}",
            version=version,
            supported=PROTOCOL_VERSION,
        )
    if version < PROTOCOL_VERSION:
        raise ManifestInvalidError(
            "obsolete manifest version {version}: this program supports "
            "version {supported}",
            version=version,
            supported=PROTOCOL_VERSION,
        )


def _check_name(name):
    """The name must be a plain file name, so it cannot escape the directory."""
    try:
        too_long = len(name.encode("utf-8")) > MAX_NAME_BYTES
    except UnicodeEncodeError:
        too_long = False
        valid_text = False
    else:
        valid_text = True
    if (
        not valid_text
        or too_long
        or name in ("", ".", "..")
        or any(char in name for char in "/\\\0")
    ):
        raise ManifestInvalidError(
            "invalid manifest: {name!r} is not a valid file name", name=name
        )


def _check_url(url):
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError:
        host = None
        parts = None
    if parts is None or parts.scheme not in ("http", "https") or not host:
        raise ManifestInvalidError(
            "invalid manifest: {url!r} is not a valid http or https URL",
            url=url,
        )


def _check_chunk_size(chunk_size):
    if not 1 <= chunk_size <= config.MAX_CHUNK_SIZE:
        raise ManifestInvalidError(
            "invalid manifest: chunk size {value} must be between 1 and "
            "{maximum}",
            value=chunk_size,
            maximum=config.MAX_CHUNK_SIZE,
        )


def _check_hashes(document):
    """All hashes must be well formed and use the algorithm of global_hash."""
    algorithm, _ = hashing.parse_hash(document["global_hash"])
    for chunk in document["chunks"]:
        chunk_algorithm, _ = hashing.parse_hash(chunk["hash"])
        if chunk_algorithm != algorithm:
            raise ManifestInvalidError(
                "invalid manifest: chunk {id} uses {found} but the global "
                "hash uses {expected}",
                id=chunk["id"],
                found=chunk_algorithm,
                expected=algorithm,
            )


def _check_chunks(document):
    """Chunks must be consecutive, contiguous and cover exactly ``size``."""
    size = document["size"]
    chunk_size = document["chunk_size"]
    chunks = document["chunks"]
    if size < 0:
        raise ManifestInvalidError(
            "invalid manifest: size {size} must not be negative", size=size
        )
    if len(chunks) > config.MAX_CHUNKS:
        raise ManifestInvalidError(
            "invalid manifest: it has {count} chunks, the maximum is {maximum}",
            count=len(chunks),
            maximum=config.MAX_CHUNKS,
        )
    expected_count = -(-size // chunk_size)
    if len(chunks) != expected_count:
        raise ManifestInvalidError(
            "invalid manifest: {size} bytes in chunks of up to {chunk_size} "
            "need {expected} chunks but it has {count}",
            size=size,
            chunk_size=chunk_size,
            expected=expected_count,
            count=len(chunks),
        )
    position = 0
    for index, chunk in enumerate(chunks):
        if chunk["id"] != index:
            raise ManifestInvalidError(
                "invalid manifest: chunk at position {index} has id {id}",
                index=index,
                id=chunk["id"],
            )
        if chunk["start"] != position:
            raise ManifestInvalidError(
                "invalid manifest: chunk {index} starts at {start} but "
                "{expected} was expected (gap or overlap)",
                index=index,
                start=chunk["start"],
                expected=position,
            )
        length = chunk["end"] - chunk["start"]
        is_last = index == len(chunks) - 1
        if length > chunk_size or length < 1 or (
            not is_last and length != chunk_size
        ):
            raise ManifestInvalidError(
                "invalid manifest: chunk {index} has an invalid length "
                "{length}",
                index=index,
                length=length,
            )
        position = chunk["end"]
    if position != size:
        raise ManifestInvalidError(
            "invalid manifest: chunks end at {end} but the size is {size}",
            end=position,
            size=size,
        )


def load_manifest(data):
    """Parse manifest bytes, checking the structure and types of the fields."""
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ManifestInvalidError(
            "invalid manifest: it is not valid JSON ({error})", error=error
        ) from None
    _check_object(document, _TOP_LEVEL_TYPES, "the manifest")
    for position, chunk in enumerate(document["chunks"]):
        _check_object(
            chunk, _CHUNK_TYPES, "chunk at position {}".format(position)
        )
    _check_version(document["protocol_version"])
    _check_name(document["name"])
    _check_url(document["url"])
    _check_chunk_size(document["chunk_size"])
    _check_hashes(document)
    _check_chunks(document)
    return Manifest(
        protocol_version=document["protocol_version"],
        name=document["name"],
        url=document["url"],
        size=document["size"],
        chunk_size=document["chunk_size"],
        global_hash=document["global_hash"],
        chunks=tuple(Chunk(**chunk) for chunk in document["chunks"]),
    )
