"""Compute the chunk list and the global hash of a local file."""

import os

from chunkget import config, events, hashing
from chunkget.errors import SourceError
from chunkget.i18n import _
from chunkget.manifest import PROTOCOL_VERSION, Chunk, Manifest, validate


def compute_chunks(path, chunk_size, algorithm, listener=None):
    """Read ``path`` once and return ``(chunks, global_hash)``.

    Hashes are formatted as ``algorithm:hex``. A single pass updates the
    hash of the current chunk and the global hash at the same time. If
    ``listener`` is given it receives a ``ChunkDone`` event per chunk.
    """
    total = -(-os.path.getsize(path) // chunk_size)
    global_hasher = hashing.Hasher(algorithm)
    chunks = []
    with open(path, "rb") as handle:
        start = 0
        while True:
            chunk_hasher = hashing.Hasher(algorithm)
            length = 0
            while length < chunk_size:
                block = handle.read(min(config.BUFFER_SIZE, chunk_size - length))
                if not block:
                    break
                chunk_hasher.update(block)
                global_hasher.update(block)
                length += len(block)
            if length == 0:
                break
            chunks.append(
                Chunk(
                    id=len(chunks),
                    start=start,
                    end=start + length,
                    hash=hashing.format_hash(algorithm, chunk_hasher.hexdigest()),
                )
            )
            start += length
            if listener is not None:
                listener(
                    events.ChunkDone(
                        index=chunks[-1].id, total=total, bytes=length
                    )
                )
    return tuple(chunks), hashing.format_hash(algorithm, global_hasher.hexdigest())


def build_manifest(
    path, url, chunk_size=None, algorithm=None, listener=None
):
    """Build a validated ``Manifest`` for the local file ``path``."""
    if chunk_size is None:
        chunk_size = config.DEFAULT_CHUNK_SIZE
    if algorithm is None:
        algorithm = config.DEFAULT_ALGORITHM
    config.validate_chunk_size(chunk_size)
    hashing.validate_algorithm(algorithm)
    try:
        chunks, global_hash = compute_chunks(path, chunk_size, algorithm, listener)
    except OSError as error:
        raise SourceError(
            _("cannot read {path}: {reason}").format(
                path=path, reason=error.strerror or error
            )
        ) from None
    manifest = Manifest(
        protocol_version=PROTOCOL_VERSION,
        name=os.path.basename(path),
        url=url,
        size=chunks[-1].end if chunks else 0,
        chunk_size=chunk_size,
        global_hash=global_hash,
        chunks=chunks,
    )
    validate(manifest)
    return manifest
