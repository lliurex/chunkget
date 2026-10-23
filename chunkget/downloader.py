"""Orchestration of the ``download`` command."""

import enum
import re

from chunkget import config, events, http, manifest

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
