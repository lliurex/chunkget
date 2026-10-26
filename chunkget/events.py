"""Progress events sent by the core to an optional listener."""

import dataclasses


@dataclasses.dataclass(frozen=True)
class PassStarted:
    """A pass over the pending chunks begins."""

    pending: int


@dataclasses.dataclass(frozen=True)
class ChunkDone:
    """A chunk finished; ``index`` is 0-based, ``bytes`` is the chunk length."""

    index: int
    total: int
    bytes: int


@dataclasses.dataclass(frozen=True)
class RetryStarted:
    """A retry pass begins (``attempt`` is 1-based)."""

    attempt: int
    max_retries: int
    pending: int


@dataclasses.dataclass(frozen=True)
class GlobalCheckStarted:
    """Verification of the whole file begins."""

    algorithm: str


@dataclasses.dataclass(frozen=True)
class Finished:
    """The download completed and the global hash was verified."""

    destination: str


@dataclasses.dataclass(frozen=True)
class ManifestSaved:
    """A manifest downloaded from a URL is available as a local file."""

    path: str


@dataclasses.dataclass(frozen=True)
class StaleStateDiscarded:
    """A saved state was dropped because its destination no longer exists."""

    destination: str


@dataclasses.dataclass(frozen=True)
class DownloadStarted:
    """The download is prepared; ``done_bytes`` are already verified (a resume)."""

    name: str
    size: int
    done_bytes: int
