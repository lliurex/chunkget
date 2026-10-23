"""Process exit codes and the exception hierarchy."""

import contextlib
import enum

from chunkget.i18n import _


class ExitCode(enum.IntEnum):
    OK = 0
    UNEXPECTED = 1
    USAGE = 2
    SOURCE_ERROR = 3
    USER_DECLINED = 4
    MANIFEST_INVALID = 5
    NETWORK_ERROR = 6
    RETRIES_EXHAUSTED = 7
    GLOBAL_HASH_MISMATCH = 8
    NO_SPACE = 9
    FILESYSTEM_ERROR = 10
    SERVER_INCOMPATIBLE = 11
    ALREADY_RUNNING = 12
    STATE_INVALID = 13
    INTERRUPTED = 130
    TERMINATED = 143


class ChunkgetError(Exception):
    """Base class for expected errors.

    The message must be passed already translated: mark the literal with
    ``_()`` at the call site and interpolate with ``str.format`` after it.
    """

    exit_code = ExitCode.UNEXPECTED


class UsageError(ChunkgetError):
    exit_code = ExitCode.USAGE


class SourceError(ChunkgetError):
    exit_code = ExitCode.SOURCE_ERROR


class UserDeclinedError(ChunkgetError):
    exit_code = ExitCode.USER_DECLINED


class OutputExistsError(UserDeclinedError):
    """The output manifest already exists and overwriting was not allowed."""


class DestinationExistsError(UserDeclinedError):
    """The destination already exists and overwriting was not allowed."""


class ManifestInvalidError(ChunkgetError):
    exit_code = ExitCode.MANIFEST_INVALID


class NetworkError(ChunkgetError):
    exit_code = ExitCode.NETWORK_ERROR


class RetriesExhaustedError(ChunkgetError):
    exit_code = ExitCode.RETRIES_EXHAUSTED


class GlobalHashMismatchError(ChunkgetError):
    exit_code = ExitCode.GLOBAL_HASH_MISMATCH


class NoSpaceError(ChunkgetError):
    exit_code = ExitCode.NO_SPACE


class FilesystemError(ChunkgetError):
    exit_code = ExitCode.FILESYSTEM_ERROR


class ServerIncompatibleError(ChunkgetError):
    exit_code = ExitCode.SERVER_INCOMPATIBLE


class AlreadyRunningError(ChunkgetError):
    exit_code = ExitCode.ALREADY_RUNNING


class StateInvalidError(ChunkgetError):
    exit_code = ExitCode.STATE_INVALID


class InterruptedByUser(ChunkgetError):
    """Raised on SIGINT (130) or SIGTERM (143)."""

    exit_code = ExitCode.INTERRUPTED

    def __init__(self, message, exit_code=None):
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


@contextlib.contextmanager
def filesystem_errors(path):
    """Turn an OSError (permissions, full disk...) into a FilesystemError."""
    try:
        yield
    except OSError as error:
        raise FilesystemError(
            _("filesystem error on {path}: {reason}").format(
                path=path, reason=error.strerror or error
            )
        ) from None
