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


# --- prepare_destination (T33) ---

import errno
import os


@pytest.mark.parametrize("size", [0, 1, 1000, 1024 * 1024 + 1])
def test_prepare_creates_a_file_of_the_exact_size(tmp_path, size):
    destination = tmp_path / "image.iso"
    storage.prepare_destination(destination, size)
    assert destination.stat().st_size == size


def test_new_file_contains_only_zeros(tmp_path):
    destination = tmp_path / "image.iso"
    storage.prepare_destination(destination, 5000)
    assert destination.read_bytes() == b"\0" * 5000


def test_prepare_extends_a_smaller_file_keeping_its_content(tmp_path):
    destination = tmp_path / "image.iso"
    destination.write_bytes(b"abc")
    storage.prepare_destination(destination, 10)
    assert destination.read_bytes() == b"abc" + b"\0" * 7


def test_prepare_shrinks_a_larger_file_to_the_exact_size(tmp_path):
    destination = tmp_path / "image.iso"
    destination.write_bytes(b"x" * 100)
    storage.prepare_destination(destination, 40)
    assert destination.read_bytes() == b"x" * 40


def test_prepare_with_size_zero_empties_an_existing_file(tmp_path):
    destination = tmp_path / "image.iso"
    destination.write_bytes(b"x" * 100)
    storage.prepare_destination(destination, 0)
    assert destination.stat().st_size == 0


def test_prepare_leaves_no_other_file(tmp_path):
    storage.prepare_destination(tmp_path / "image.iso", 100)
    assert os.listdir(tmp_path) == ["image.iso"]


def test_prepare_preallocates_with_posix_fallocate(tmp_path, monkeypatch):
    calls = []
    real = os.posix_fallocate

    def spy(fd, offset, length):
        calls.append((offset, length))
        return real(fd, offset, length)

    monkeypatch.setattr(storage.os, "posix_fallocate", spy)
    destination = tmp_path / "image.iso"
    storage.prepare_destination(destination, 4096)
    assert calls == [(0, 4096)]
    assert destination.stat().st_size == 4096


@pytest.mark.parametrize("code", [errno.EOPNOTSUPP, errno.ENOSYS, errno.EINVAL])
def test_prepare_falls_back_to_truncate_when_fallocate_is_unsupported(
    tmp_path, monkeypatch, code
):
    calls = []

    def unsupported(fd, offset, length):
        calls.append(length)
        raise OSError(code, os.strerror(code))

    monkeypatch.setattr(storage.os, "posix_fallocate", unsupported)
    destination = tmp_path / "image.iso"
    storage.prepare_destination(destination, 3000)
    assert calls == [3000]
    assert destination.stat().st_size == 3000
    assert destination.read_bytes() == b"\0" * 3000


def test_prepare_works_without_posix_fallocate(tmp_path, monkeypatch):
    monkeypatch.delattr(storage.os, "posix_fallocate")
    destination = tmp_path / "image.iso"
    storage.prepare_destination(destination, 3000)
    assert destination.stat().st_size == 3000


def test_other_fallocate_errors_are_not_hidden(tmp_path, monkeypatch):
    def failing(fd, offset, length):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(storage.os, "posix_fallocate", failing)
    with pytest.raises(OSError) as excinfo:
        storage.prepare_destination(tmp_path / "image.iso", 100)
    assert excinfo.value.errno == errno.EIO


def test_prepare_checks_free_space_before_creating_anything(free_space, tmp_path):
    free_space["free"] = 99
    destination = tmp_path / "image.iso"
    with pytest.raises(NoSpaceError):
        storage.prepare_destination(destination, 100)
    assert not destination.exists()


def test_prepare_counts_the_current_size_of_an_existing_file(free_space, tmp_path):
    destination = tmp_path / "image.iso"
    destination.write_bytes(b"x" * 60)
    free_space["free"] = 40
    storage.prepare_destination(destination, 100)
    assert destination.stat().st_size == 100
