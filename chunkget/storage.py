"""The destination file: free space, preallocation and writing."""

import contextlib
import errno
import os
import shutil
from pathlib import Path

from chunkget import config, hashing
from chunkget.errors import FilesystemError, NoSpaceError
from chunkget.i18n import _


@contextlib.contextmanager
def _filesystem_errors(path):
    """Turn an OSError (permissions, full disk...) into a FilesystemError."""
    try:
        yield
    except OSError as error:
        raise FilesystemError(
            _("filesystem error on {path}: {reason}").format(
                path=path, reason=error.strerror or error
            )
        ) from None


def check_free_space(directory, needed):
    """Raise NoSpaceError if ``directory`` has fewer than ``needed`` free bytes."""
    with _filesystem_errors(directory):
        free = shutil.disk_usage(directory).free
    if free < needed:
        raise NoSpaceError(
            _(
                "not enough free space in {directory}: {needed} bytes needed, "
                "{free} available"
            ).format(directory=directory, needed=needed, free=free)
        )


def bytes_needed(destination, size):
    """Extra bytes required to make ``destination`` ``size`` bytes long."""
    with _filesystem_errors(destination):
        try:
            current = os.path.getsize(destination)
        except FileNotFoundError:
            current = 0
    return max(size - current, 0)


def check_destination_space(destination, size):
    """Check there is room to create or extend ``destination`` to ``size`` bytes."""
    directory = Path(destination).parent
    check_free_space(directory, bytes_needed(destination, size))


# posix_fallocate failures that only mean "not supported here".
_FALLOCATE_UNSUPPORTED = (errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL)


def prepare_destination(path, size):
    """Create or resize ``path`` to exactly ``size`` bytes.

    Checks the free space first. Blocks are reserved with
    ``os.posix_fallocate``; where that is not supported the file is just
    truncated to size (sparse). Existing content below ``size`` is kept.
    """
    check_destination_space(path, size)
    with _filesystem_errors(path):
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            if size > 0 and hasattr(os, "posix_fallocate"):
                try:
                    os.posix_fallocate(fd, 0, size)
                except OSError as error:
                    if error.errno not in _FALLOCATE_UNSUPPORTED:
                        raise
            # Extends with zeros, or shrinks a larger file to the exact size.
            os.ftruncate(fd, size)
        finally:
            os.close(fd)


def write_chunk(path, start, stream, length, algorithm=config.DEFAULT_ALGORITHM):
    """Write up to ``length`` bytes of ``stream`` into ``path`` at ``start``.

    The destination must already exist at its final size. Data is written in
    blocks of ``config.BUFFER_SIZE`` while it is hashed, then flushed and
    synced to disk. Returns the hash of what was written as ``algorithm:hex``.
    If the stream ends early only what arrived is written and hashed, so the
    caller sees a hash mismatch.
    """
    hasher = hashing.Hasher(algorithm)
    with _filesystem_errors(path):
        handle = open(path, "r+b")
    try:
        with _filesystem_errors(path):
            handle.seek(start)
        remaining = length
        while remaining > 0:
            # Errors reading the stream are not filesystem errors.
            block = stream.read(min(config.BUFFER_SIZE, remaining))
            if not block:
                break
            with _filesystem_errors(path):
                handle.write(block)
            hasher.update(block)
            remaining -= len(block)
        with _filesystem_errors(path):
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        with _filesystem_errors(path):
            handle.close()
    return hashing.format_hash(algorithm, hasher.hexdigest())
