"""The state file of a download (plan section 5)."""

import dataclasses
import json
import os

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


def new_state(manifest, destination):
    """State of a download that has not started: every chunk pending."""
    return State(
        state_version=STATE_VERSION,
        manifest_id=manifest.global_hash,
        destination=os.path.abspath(destination),
        chunk_states=PENDING * len(manifest.chunks),
        status=IN_PROGRESS,
    )


def from_json(data):
    """Load a state from its JSON bytes."""
    return State(**json.loads(data.decode("utf-8")))
