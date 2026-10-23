"""Default values (plan section 2) and option parsing."""

import os
import re
from pathlib import Path

from chunkget.errors import UsageError
from chunkget.i18n import _

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
RETRY_DELAY_BASE = 2  # seconds
RETRY_DELAY_MAX = 60  # seconds
MAX_CONSECUTIVE_NETWORK_FAILURES = 3

_SIZE_SUFFIXES = {"K": KIB, "M": MIB, "G": 1024 * MIB}
_SIZE_RE = re.compile(r"([0-9]+)([KMG])?", re.ASCII)


def parse_size(text):
    """Convert "4096", "4K", "100M" or "1G" (powers of 1024) to bytes."""
    match = _SIZE_RE.fullmatch(text)
    if match is None:
        raise UsageError(
            _(
                "invalid size {value!r}: expected a non-negative integer with an "
                "optional suffix K, M or G (powers of 1024), e.g. 4096, 4K, 100M, 1G"
            ).format(
                value=text,
            )
        )
    number, suffix = match.groups()
    return int(number) * _SIZE_SUFFIXES.get(suffix, 1)


def _validate_range(name, value, low, high):
    if not low <= value <= high:
        raise UsageError(
            _(
                "invalid {name} {value}: must be between {low} and {high}"
            ).format(
                name=name,
                value=value,
                low=low,
                high=high,
            )
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


def default_state_dir():
    """``$XDG_STATE_HOME/chunkget`` or ``~/.local/state/chunkget``."""
    base = os.environ.get("XDG_STATE_HOME", "")
    # The XDG spec says relative values must be ignored.
    if not base or not os.path.isabs(base):
        base = os.path.join(Path.home(), ".local", "state")
    return Path(base) / "chunkget"


def default_manifest_path(name):
    """Default output manifest: ``./<name>.chunkget.manifest``."""
    return Path(name + ".chunkget.manifest")


def default_destination(name):
    """Default download destination: ``./<name>``."""
    return Path(name)


def retry_delay(attempt):
    """Seconds to wait before retry number ``attempt`` (1-based): 2, 4, 8... up to 60."""
    return min(RETRY_DELAY_BASE * 2 ** (attempt - 1), RETRY_DELAY_MAX)
