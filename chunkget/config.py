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
MAX_CHUNK_SIZE = 1024 * MIB
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


def _validate_range(name, value, low, high):
    if not low <= value <= high:
        raise UsageError(
            "invalid {name} {value}: must be between {low} and {high}",
            name=name,
            value=value,
            low=low,
            high=high,
        )
    return value


def validate_chunk_size(value):
    """Check a chunk size in bytes (1 B to 1 GiB)."""
    return _validate_range("chunk size", value, 1, MAX_CHUNK_SIZE)


def validate_max_retries(value):
    return _validate_range("max retries", value, 0, 100)


def validate_timeout(value):
    """Check a network timeout in seconds."""
    return _validate_range("timeout", value, 1, 3600)
