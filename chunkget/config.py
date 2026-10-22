"""Default values (plan section 2) and option parsing."""

import re

from chunkget.errors import UsageError

KIB = 1024
MIB = 1024 * KIB

DEFAULT_CHUNK_SIZE = 100 * MIB
DEFAULT_ALGORITHM = "sha256"
DEFAULT_MAX_RETRIES = 5
DEFAULT_TIMEOUT = 30  # seconds
BUFFER_SIZE = 1 * MIB
MAX_MANIFEST_BYTES = 64 * MIB
MAX_CHUNKS = 250_000
MAX_CONSECUTIVE_NETWORK_FAILURES = 3

_SIZE_SUFFIXES = {"K": KIB, "M": MIB, "G": 1024 * MIB}
_SIZE_RE = re.compile(r"([0-9]+)([KMG])?", re.ASCII)


def parse_size(text):
    """Convert "4096", "4K", "100M" or "1G" (powers of 1024) to bytes."""
    match = _SIZE_RE.fullmatch(text)
    if match is None:
        raise UsageError(
            "invalid size {value!r}: expected a non-negative integer with an "
            "optional suffix K, M or G (powers of 1024), e.g. 4096, 4K, 100M, 1G",
            value=text,
        )
    number, suffix = match.groups()
    return int(number) * _SIZE_SUFFIXES.get(suffix, 1)
