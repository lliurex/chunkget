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
