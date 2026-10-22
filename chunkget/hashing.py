"""Supported hash algorithms and the ``algorithm:hex`` format."""

import hashlib
import re

from chunkget import config
from chunkget.errors import ManifestInvalidError, UsageError
from chunkget.i18n import _

SUPPORTED_ALGORITHMS = ("sha256", "sha384", "sha512", "sha3_256", "sha3_512")

_HEX_RE = re.compile(r"[0-9a-f]*", re.ASCII)


def validate_algorithm(name):
    """Return ``name`` if supported, else raise UsageError listing valid ones."""
    if name not in SUPPORTED_ALGORITHMS:
        raise UsageError(
            _(
                "unsupported hash algorithm {name!r}: use one of {supported}"
            ).format(
                name=name,
                supported=", ".join(SUPPORTED_ALGORITHMS),
            )
        )
    return name


def hex_length(name):
    """Number of hexadecimal digits of a digest of ``name``."""
    return hashlib.new(validate_algorithm(name)).digest_size * 2


def format_hash(algorithm, hexdigest):
    return algorithm + ":" + hexdigest


def parse_hash(text):
    """Split ``algorithm:hex`` into ``(algorithm, hex)`` or raise ManifestInvalidError."""
    algorithm, separator, hexdigest = text.partition(":")
    if not separator or algorithm not in SUPPORTED_ALGORITHMS:
        raise ManifestInvalidError(
            _(
                "invalid hash {value!r}: expected <algorithm>:<hex> with algorithm "
                "one of {supported}"
            ).format(
                value=text,
                supported=", ".join(SUPPORTED_ALGORITHMS),
            )
        )
    if len(hexdigest) != hex_length(algorithm) or not _HEX_RE.fullmatch(hexdigest):
        raise ManifestInvalidError(
            _(
                "invalid {algorithm} hash {value!r}: expected {length} lowercase "
                "hexadecimal digits"
            ).format(
                algorithm=algorithm,
                value=hexdigest,
                length=hex_length(algorithm),
            )
        )
    return algorithm, hexdigest


class Hasher:
    """Incremental hasher for one of the supported algorithms."""

    def __init__(self, algorithm):
        self.algorithm = validate_algorithm(algorithm)
        self._hash = hashlib.new(algorithm)

    def update(self, data):
        self._hash.update(data)

    def hexdigest(self):
        return self._hash.hexdigest()


def hash_file(path, algorithm):
    """Return the hex digest of a file, reading it in buffer-sized blocks."""
    hasher = Hasher(algorithm)
    with open(path, "rb") as handle:
        while True:
            block = handle.read(config.BUFFER_SIZE)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()
