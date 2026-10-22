"""Compute the chunk list and the global hash of a local file."""

from chunkget import config, hashing
from chunkget.manifest import Chunk


def compute_chunks(path, chunk_size, algorithm):
    """Read ``path`` once and return ``(chunks, global_hash)``.

    Hashes are formatted as ``algorithm:hex``. A single pass updates the
    hash of the current chunk and the global hash at the same time.
    """
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
    return tuple(chunks), hashing.format_hash(algorithm, global_hasher.hexdigest())
