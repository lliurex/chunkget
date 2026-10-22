import dataclasses

import pytest

from chunkget import events

# event class -> (field names, sample values)
EVENTS = [
    (events.PassStarted, ("pending",), (7,)),
    (events.ChunkDone, ("index", "total", "bytes"), (11, 768, 1024)),
    (events.RetryStarted, ("attempt", "max_retries", "pending"), (2, 5, 7)),
    (events.GlobalCheckStarted, ("algorithm",), ("sha256",)),
    (events.Finished, ("destination",), ("/tmp/image.iso",)),
]


@pytest.mark.parametrize("cls, names, values", EVENTS)
def test_event_has_agreed_fields(cls, names, values):
    assert tuple(f.name for f in dataclasses.fields(cls)) == names
    event = cls(*values)
    assert tuple(getattr(event, n) for n in names) == values


@pytest.mark.parametrize("cls, names, values", EVENTS)
def test_event_is_immutable(cls, names, values):
    event = cls(*values)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(event, names[0], values[0])
