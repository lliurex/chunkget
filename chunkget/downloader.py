"""Orchestration of the ``download`` command."""

import enum
import os
import re

from chunkget import config, events, hashing, http, manifest, state, storage
from chunkget.errors import DestinationExistsError, StateInvalidError, filesystem_errors
from chunkget.i18n import _

# "scheme://": anything that looks like a URL is not a local path.
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def read_manifest(source, timeout):
    """Return ``(manifest, data)``: the validated manifest and, if it came
    from a URL, the bytes received (``None`` for a local file)."""
    text = str(source)
    if _URL_RE.match(text):
        http.validate_url(text)
        data = http.fetch_bytes(text, config.MAX_MANIFEST_BYTES, timeout)
        return manifest.load_manifest(data), data
    return manifest.load_manifest_file(source), None


def resolve_manifest(source, timeout=config.DEFAULT_TIMEOUT):
    """Return the validated manifest named by ``source``.

    ``source`` is a local path or an ``http(s)`` URL, told apart by its
    scheme. Any other URL scheme is a ``SourceError``. Nothing is written.
    """
    return read_manifest(source, timeout)[0]


def obtain_manifest(
    source,
    timeout=config.DEFAULT_TIMEOUT,
    manifest_file=None,
    overwrite_manifest=False,
    listener=None,
):
    """Resolve the manifest of a download, keeping a local copy of a remote one.

    A manifest read from a URL is validated, saved as a local file (see
    ``manifest.save_manifest``) and a ``ManifestSaved`` event is sent to
    ``listener``; the download goes on with the validated manifest in
    memory. A local manifest is used as it is and nothing is written.
    """
    loaded, data = read_manifest(source, timeout)
    if data is not None:
        path = manifest.save_manifest(data, manifest_file, overwrite_manifest)
        if listener is not None:
            listener(events.ManifestSaved(path=str(path)))
    return loaded


class Scenario(enum.Enum):
    """What to do with the destination and the state at the start (D14)."""

    NEW = "new"
    NEW_DISCARDING_STATE = "new_discarding_state"
    NEEDS_CONFIRMATION = "needs_confirmation"
    RESUME = "resume"
    INCONSISTENT = "inconsistent"


def decide_scenario(
    destination_size, state_exists, manifest_size, restart=False, overwrite=False
):
    """Decide how a download starts (table of D14). A pure function.

    ``destination_size`` is None if the destination does not exist.
    ``overwrite`` means the user already accepted replacing an existing
    destination; without it that case is ``NEEDS_CONFIRMATION``.
    """
    destination_exists = destination_size is not None
    if not destination_exists:
        return Scenario.NEW_DISCARDING_STATE if state_exists else Scenario.NEW
    if state_exists and not restart:
        if destination_size == manifest_size:
            return Scenario.RESUME
        return Scenario.INCONSISTENT
    # The destination exists and is going to be downloaded again.
    if not overwrite:
        return Scenario.NEEDS_CONFIRMATION
    return Scenario.NEW_DISCARDING_STATE if state_exists else Scenario.NEW


def _destination_size(destination):
    """Size of the destination, or None if it does not exist."""
    with filesystem_errors(destination):
        try:
            return os.path.getsize(destination)
        except FileNotFoundError:
            return None


def prepare_download(
    loaded, destination, state_dir, restart=False, overwrite=False
):
    """Prepare the destination and the state of a download (D14).

    Returns the ``State`` to work with. The caller holds the download lock
    and has already created ``state_dir``. Depending on the scenario:

    - new: the destination is created and a state with every chunk pending.
    - new_discarding_state: the same, replacing the stale state.
    - needs_confirmation: ``DestinationExistsError``, nothing is changed.
    - inconsistent: ``StateInvalidError``, nothing is changed.
    - resume: the saved state is loaded; the destination is left as it is.
    """
    key = state.state_key(loaded.global_hash, destination)
    state_exists = state.state_path(state_dir, key).exists()
    scenario = decide_scenario(
        _destination_size(destination),
        state_exists,
        loaded.size,
        restart=restart,
        overwrite=overwrite,
    )
    if scenario is Scenario.NEEDS_CONFIRMATION:
        raise DestinationExistsError(
            _("the destination {path} already exists").format(path=destination)
        )
    if scenario is Scenario.INCONSISTENT:
        raise StateInvalidError(
            _(
                "the destination {path} does not match its saved state: "
                "use --restart to download it again"
            ).format(path=destination)
        )
    if scenario is Scenario.RESUME:
        return state.load_state(state_dir, loaded, destination)
    # The destination is prepared first: with no space left no state is saved.
    storage.prepare_destination(destination, loaded.size)
    fresh = state.new_state(loaded, destination)
    state.save_state(fresh, state_dir)
    return fresh


class ChunkResult(enum.Enum):
    """Outcome of downloading one chunk."""

    CORRECT = "correct"
    BAD_HASH = "bad_hash"
    NETWORK_FAILURE = "network_failure"


def download_chunk(loaded, chunk, destination, timeout):
    """Download one chunk into its place in ``destination`` and verify it.

    A wrong hash or a transient network failure are results, not
    exceptions, so the caller can go on with the next chunk (RF9, D7).
    Fatal errors (``NetworkError``, ``ServerIncompatibleError``) are raised;
    an incompatible server is detected before any data is written.
    """
    algorithm, _digest = hashing.parse_hash(chunk.hash)
    try:
        with http.open_range(
            loaded.url, chunk.start, chunk.end, timeout, total=loaded.size
        ) as stream:
            found = storage.write_chunk(
                destination, chunk.start, stream, chunk.end - chunk.start, algorithm
            )
    except http.RetryableError:
        return ChunkResult.NETWORK_FAILURE
    if found != chunk.hash:
        return ChunkResult.BAD_HASH
    return ChunkResult.CORRECT
