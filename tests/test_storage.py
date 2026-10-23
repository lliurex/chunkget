import collections
from pathlib import Path

import pytest

from chunkget import storage
from chunkget.errors import ExitCode, NoSpaceError

Usage = collections.namedtuple("Usage", "total used free")


@pytest.fixture
def free_space(monkeypatch):
    """Replace shutil.disk_usage; returns a dict with the free bytes and the calls."""
    state = {"free": 0, "directories": []}

    def fake_disk_usage(directory):
        state["directories"].append(directory)
        return Usage(total=10**12, used=0, free=state["free"])

    monkeypatch.setattr(storage.shutil, "disk_usage", fake_disk_usage)
    return state


def test_exact_free_space_is_enough(free_space, tmp_path):
    free_space["free"] = 1000
    storage.check_free_space(tmp_path, 1000)


def test_one_byte_less_raises_no_space_error(free_space, tmp_path):
    free_space["free"] = 999
    with pytest.raises(NoSpaceError) as excinfo:
        storage.check_free_space(tmp_path, 1000)
    assert excinfo.value.exit_code == ExitCode.NO_SPACE
    message = str(excinfo.value)
    assert "1000" in message and "999" in message


def test_nothing_needed_always_passes(free_space, tmp_path):
    free_space["free"] = 0
    storage.check_free_space(tmp_path, 0)


def test_free_space_is_measured_in_the_given_directory(free_space, tmp_path):
    free_space["free"] = 10
    storage.check_free_space(tmp_path, 10)
    assert free_space["directories"] == [tmp_path]


def test_new_destination_needs_the_whole_size(free_space, tmp_path):
    destination = tmp_path / "image.iso"
    assert storage.bytes_needed(destination, 1000) == 1000
    free_space["free"] = 1000
    storage.check_destination_space(destination, 1000)
    free_space["free"] = 999
    with pytest.raises(NoSpaceError):
        storage.check_destination_space(destination, 1000)
    assert free_space["directories"] == [tmp_path, tmp_path]


def test_existing_destination_needs_size_minus_current_size(free_space, tmp_path):
    destination = tmp_path / "image.iso"
    destination.write_bytes(b"x" * 600)
    assert storage.bytes_needed(destination, 1000) == 400
    free_space["free"] = 400
    storage.check_destination_space(destination, 1000)
    free_space["free"] = 399
    with pytest.raises(NoSpaceError):
        storage.check_destination_space(destination, 1000)


def test_existing_destination_larger_than_size_needs_nothing(free_space, tmp_path):
    destination = tmp_path / "image.iso"
    destination.write_bytes(b"x" * 1500)
    assert storage.bytes_needed(destination, 1000) == 0
    free_space["free"] = 0
    storage.check_destination_space(destination, 1000)


def test_empty_file_needs_no_space(free_space, tmp_path):
    free_space["free"] = 0
    storage.check_destination_space(tmp_path / "empty", 0)


def test_relative_destination_uses_the_current_directory(
    free_space, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    free_space["free"] = 5
    storage.check_destination_space("image.iso", 5)
    assert free_space["directories"] == [Path(".")]
