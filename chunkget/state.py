"""The state file of a download (plan section 5)."""

import contextlib
import dataclasses
import hashlib
import json
import os
from pathlib import Path

from chunkget.errors import StateInvalidError, filesystem_errors
from chunkget.i18n import _

STATE_VERSION = 1

# States of a chunk, one character each in ``chunk_states``.
PENDING = "P"
CORRECT = "C"
FAILED = "F"

# Overall status of a download.
IN_PROGRESS = "in_progress"
COMPLETED = "completed"
GLOBAL_CHECK_FAILED = "global_check_failed"


@dataclasses.dataclass
class State:
    state_version: int
    manifest_id: str
    destination: str
    chunk_states: str
    status: str

    def to_json(self):
        return json.dumps(dataclasses.asdict(self), indent=2, ensure_ascii=False) + "\n"


def state_key(manifest_id, destination):
    """Name of the state of a manifest downloaded to ``destination``.

    The first 32 hexadecimal characters of
    ``sha256(manifest_id + "\\0" + absolute destination)``.
    """
    text = manifest_id + "\0" + os.path.abspath(destination)
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()[:32]


def new_state(manifest, destination):
    """State of a download that has not started: every chunk pending."""
    return State(
        state_version=STATE_VERSION,
        manifest_id=manifest.global_hash,
        destination=os.path.abspath(destination),
        chunk_states=PENDING * len(manifest.chunks),
        status=IN_PROGRESS,
    )


_FIELDS = (
    ("state_version", int),
    ("manifest_id", str),
    ("destination", str),
    ("chunk_states", str),
    ("status", str),
)
_CHUNK_STATES = (PENDING, CORRECT, FAILED)
_STATUSES = (IN_PROGRESS, COMPLETED, GLOBAL_CHECK_FAILED)


def from_json(data, manifest=None):
    """Load and validate a state from its JSON bytes.

    If ``manifest`` is given, the state must also belong to it and have one
    character per chunk. Raises ``StateInvalidError`` otherwise.
    """
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise StateInvalidError(
            _("invalid state file: it is not valid JSON ({error})").format(error=error)
        ) from None
    if not isinstance(document, dict) or set(document) != {k for k, _t in _FIELDS}:
        raise StateInvalidError(
            _("invalid state file: it must be an object with the keys {keys}").format(
                keys=", ".join(key for key, _t in _FIELDS)
            )
        )
    for key, expected_type in _FIELDS:
        value = document[key]
        # bool is a subclass of int but is never a valid number here.
        if not isinstance(value, expected_type) or isinstance(value, bool):
            raise StateInvalidError(
                _("invalid state file: key {key!r} has the wrong type").format(key=key)
            )
    loaded = State(**document)
    _validate(loaded, manifest)
    return loaded


def _validate(loaded, manifest):
    if loaded.state_version != STATE_VERSION:
        raise StateInvalidError(
            _(
                "unsupported state file version {version}: this program "
                "supports version {supported}"
            ).format(version=loaded.state_version, supported=STATE_VERSION)
        )
    if loaded.status not in _STATUSES:
        raise StateInvalidError(
            _("invalid state file: unknown status {status!r}").format(
                status=loaded.status
            )
        )
    if not os.path.isabs(loaded.destination):
        raise StateInvalidError(
            _("invalid state file: destination {path!r} is not an absolute path").format(
                path=loaded.destination
            )
        )
    if any(char not in _CHUNK_STATES for char in loaded.chunk_states):
        raise StateInvalidError(
            _("invalid state file: chunk states may only contain P, C or F")
        )
    if manifest is None:
        return
    if loaded.manifest_id != manifest.global_hash:
        raise StateInvalidError(_("invalid state file: it belongs to a different manifest"))
    if len(loaded.chunk_states) != len(manifest.chunks):
        raise StateInvalidError(
            _(
                "invalid state file: it has {found} chunk states but the "
                "manifest has {expected} chunks"
            ).format(found=len(loaded.chunk_states), expected=len(manifest.chunks))
        )


def state_path(directory, key):
    return Path(directory) / (key + ".json")


def save_state(state, directory):
    """Atomically write ``state`` in ``directory``.

    The data goes to ``<key>.json.tmp``, is synced, replaces the real file
    and the directory is synced too. A failure at any point leaves the
    previous state untouched and no temporary file behind.
    """
    path = state_path(directory, state_key(state.manifest_id, state.destination))
    temporary = path.with_name(path.name + ".tmp")
    try:
        with filesystem_errors(path):
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(state.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _sync_directory(directory)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def load_state(directory, manifest, destination):
    """Load and validate the state of ``manifest`` downloaded to ``destination``.

    Returns None if there is no state file.
    """
    key = state_key(manifest.global_hash, destination)
    path = state_path(directory, key)
    with filesystem_errors(path):
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except FileNotFoundError:
            return None
    return from_json(data, manifest)
