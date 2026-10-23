"""The destination file: free space, preallocation and writing."""

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
