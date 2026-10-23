"""The destination file: free space, preallocation and writing."""

import errno
import os
import shutil
from pathlib import Path

from chunkget.errors import NoSpaceError
from chunkget.i18n import _


def check_free_space(directory, needed):
    """Raise NoSpaceError if ``directory`` has fewer than ``needed`` free bytes."""
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
