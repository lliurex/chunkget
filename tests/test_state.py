import json
import os

import pytest

from chunkget import manifest_builder, state

URL = "http://127.0.0.1:8000/image.iso"


def make_manifest(tmp_path, size=250, chunk_size=100):
    source = tmp_path / "source.bin"
    source.write_bytes(bytes(index % 251 for index in range(size)))
    return manifest_builder.build_manifest(source, URL, chunk_size=chunk_size)


def test_constants_match_plan_section_5():
    assert state.STATE_VERSION == 1
    assert (state.PENDING, state.CORRECT, state.FAILED) == ("P", "C", "F")
    assert state.IN_PROGRESS == "in_progress"
    assert state.COMPLETED == "completed"
    assert state.GLOBAL_CHECK_FAILED == "global_check_failed"


def test_new_state_has_one_pending_character_per_chunk(tmp_path):
    manifest = make_manifest(tmp_path)
    assert len(manifest.chunks) == 3
    new = state.new_state(manifest, tmp_path / "image.iso")
    assert new.chunk_states == "PPP"
    assert new.status == "in_progress"
    assert new.state_version == 1


def test_new_state_is_tied_to_the_manifest_and_destination(tmp_path):
    manifest = make_manifest(tmp_path)
    destination = tmp_path / "image.iso"
    new = state.new_state(manifest, destination)
    assert new.manifest_id == manifest.global_hash
    assert new.destination == str(destination)


def test_destination_is_stored_as_an_absolute_path(tmp_path, monkeypatch):
    manifest = make_manifest(tmp_path)
    monkeypatch.chdir(tmp_path)
    new = state.new_state(manifest, "image.iso")
    assert new.destination == str(tmp_path / "image.iso")
    assert os.path.isabs(new.destination)


def test_new_state_of_an_empty_file_has_no_chunk_states(tmp_path):
    manifest = make_manifest(tmp_path, size=0)
    new = state.new_state(manifest, tmp_path / "image.iso")
    assert new.chunk_states == ""


def test_to_json_is_a_json_object_with_the_plan_keys(tmp_path):
    new = state.new_state(make_manifest(tmp_path), tmp_path / "image.iso")
    data = json.loads(new.to_json())
    assert list(data) == [
        "state_version",
        "manifest_id",
        "destination",
        "chunk_states",
        "status",
    ]
    assert data["chunk_states"] == "PPP"


def test_round_trip_keeps_the_data(tmp_path):
    new = state.new_state(make_manifest(tmp_path), tmp_path / "image.iso")
    new.chunk_states = "CFP"
    new.status = state.GLOBAL_CHECK_FAILED
    loaded = state.from_json(new.to_json().encode("utf-8"))
    assert loaded == new


def test_round_trip_with_non_ascii_destination(tmp_path):
    new = state.new_state(make_manifest(tmp_path), tmp_path / "ñandú.iso")
    assert state.from_json(new.to_json().encode("utf-8")) == new


# --- Validation (T37) ---

from chunkget.errors import ExitCode, StateInvalidError


def document(tmp_path, **changes):
    """JSON of a valid state for a 3-chunk manifest, with ``changes`` applied."""
    data = json.loads(
        state.new_state(make_manifest(tmp_path), tmp_path / "image.iso").to_json()
    )
    for key, value in changes.items():
        if value is MISSING:
            del data[key]
        else:
            data[key] = value
    return json.dumps(data).encode("utf-8")


MISSING = object()


def load(tmp_path, **changes):
    return state.from_json(document(tmp_path, **changes), make_manifest(tmp_path))


def test_a_valid_state_is_loaded(tmp_path):
    loaded = load(tmp_path)
    assert loaded.chunk_states == "PPP"


@pytest.mark.parametrize("chunk_states", ["PCF", "CCC", "FFF"])
@pytest.mark.parametrize(
    "status", [state.IN_PROGRESS, state.COMPLETED, state.GLOBAL_CHECK_FAILED]
)
def test_every_valid_chunk_state_and_status_is_accepted(
    tmp_path, chunk_states, status
):
    loaded = load(tmp_path, chunk_states=chunk_states, status=status)
    assert (loaded.chunk_states, loaded.status) == (chunk_states, status)


def assert_invalid(function):
    with pytest.raises(StateInvalidError) as excinfo:
        function()
    assert excinfo.value.exit_code == ExitCode.STATE_INVALID
    return str(excinfo.value)


@pytest.mark.parametrize(
    "data",
    [b"", b"not json", b'{"state_version": ', b"\xff\xfe{}", b"[]", b"null", b"3"],
    ids=["empty", "not json", "truncated", "bad utf-8", "list", "null", "number"],
)
def test_invalid_json_is_rejected(tmp_path, data):
    assert_invalid(lambda: state.from_json(data, make_manifest(tmp_path)))


def test_invalid_json_is_rejected_without_a_manifest():
    assert_invalid(lambda: state.from_json(b"not json"))


@pytest.mark.parametrize("key", ["state_version", "manifest_id", "destination",
                                 "chunk_states", "status"])
def test_missing_keys_are_rejected(tmp_path, key):
    assert_invalid(lambda: load(tmp_path, **{key: MISSING}))


def test_extra_keys_are_rejected(tmp_path):
    assert_invalid(lambda: load(tmp_path, extra=1))


@pytest.mark.parametrize(
    "changes",
    [
        {"state_version": "1"},
        {"state_version": True},
        {"state_version": 1.0},
        {"manifest_id": 5},
        {"destination": None},
        {"chunk_states": ["P", "P", "P"]},
        {"status": 1},
    ],
)
def test_wrong_types_are_rejected(tmp_path, changes):
    assert_invalid(lambda: load(tmp_path, **changes))


@pytest.mark.parametrize("version", [0, 2, 99, -1])
def test_unknown_version_is_rejected(tmp_path, version):
    message = assert_invalid(lambda: load(tmp_path, state_version=version))
    assert str(version) in message


@pytest.mark.parametrize("chunk_states", ["", "PP", "PPPP", "PPPPPP"])
def test_length_different_from_the_number_of_chunks_is_rejected(
    tmp_path, chunk_states
):
    message = assert_invalid(lambda: load(tmp_path, chunk_states=chunk_states))
    assert "3" in message


def test_length_is_not_checked_without_a_manifest(tmp_path):
    loaded = state.from_json(document(tmp_path, chunk_states="PP"))
    assert loaded.chunk_states == "PP"


@pytest.mark.parametrize("chunk_states", ["PXP", "pcf", "P P", "P\nP", "1PP", "PPé"])
def test_characters_outside_pcf_are_rejected(tmp_path, chunk_states):
    assert_invalid(lambda: load(tmp_path, chunk_states=chunk_states))


def test_characters_outside_pcf_are_rejected_without_a_manifest(tmp_path):
    assert_invalid(lambda: state.from_json(document(tmp_path, chunk_states="PXP")))


@pytest.mark.parametrize("status", ["", "done", "COMPLETED", "in-progress"])
def test_unknown_status_is_rejected(tmp_path, status):
    assert_invalid(lambda: load(tmp_path, status=status))


@pytest.mark.parametrize("destination", ["", "image.iso", "./image.iso"])
def test_destination_must_be_an_absolute_path(tmp_path, destination):
    assert_invalid(lambda: load(tmp_path, destination=destination))


def test_state_of_another_manifest_is_rejected(tmp_path):
    assert_invalid(lambda: load(tmp_path, manifest_id="sha256:" + "0" * 64))


# --- state_key (T38) ---

import hashlib
import re

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def test_state_key_is_32_lowercase_hex_characters(tmp_path):
    key = state.state_key(HASH_A, tmp_path / "image.iso")
    assert re.fullmatch(r"[0-9a-f]{32}", key)


def test_state_key_follows_the_formula_of_the_plan(tmp_path):
    destination = tmp_path / "image.iso"
    expected = hashlib.sha256(
        (HASH_A + "\0" + str(destination)).encode("utf-8")
    ).hexdigest()[:32]
    assert state.state_key(HASH_A, destination) == expected


def test_state_key_is_deterministic(tmp_path):
    destination = tmp_path / "image.iso"
    assert state.state_key(HASH_A, destination) == state.state_key(HASH_A, destination)


def test_state_key_changes_with_the_manifest(tmp_path):
    destination = tmp_path / "image.iso"
    assert state.state_key(HASH_A, destination) != state.state_key(HASH_B, destination)


def test_state_key_changes_with_the_destination(tmp_path):
    assert state.state_key(HASH_A, tmp_path / "a.iso") != state.state_key(
        HASH_A, tmp_path / "b.iso"
    )


def test_manifest_id_and_destination_are_not_interchangeable():
    assert state.state_key("ab", "/c") != state.state_key("a", "/bc")


def test_relative_destination_is_normalised_to_an_absolute_path(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    assert state.state_key(HASH_A, "image.iso") == state.state_key(
        HASH_A, tmp_path / "image.iso"
    )
    assert state.state_key(HASH_A, "./image.iso") == state.state_key(
        HASH_A, tmp_path / "image.iso"
    )


def test_equivalent_spellings_of_a_path_give_the_same_key(tmp_path):
    reference = state.state_key(HASH_A, tmp_path / "image.iso")
    assert state.state_key(HASH_A, str(tmp_path) + "//image.iso") == reference
    assert state.state_key(HASH_A, tmp_path / "sub" / ".." / "image.iso") == reference


def test_state_key_accepts_names_that_are_not_valid_utf8(tmp_path):
    key = state.state_key(HASH_A, os.fsdecode(os.fsencode(tmp_path) + b"/\xff.iso"))
    assert re.fullmatch(r"[0-9a-f]{32}", key)


def test_state_key_matches_the_destination_stored_in_a_new_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manifest = make_manifest(tmp_path)
    new = state.new_state(manifest, "image.iso")
    assert state.state_key(manifest.global_hash, "image.iso") == state.state_key(
        new.manifest_id, new.destination
    )


# --- Atomic save and load (T39) ---

import errno

from chunkget.errors import FilesystemError


@pytest.fixture
def saved(tmp_path):
    """A manifest, a destination, a state directory and a saved state."""
    manifest = make_manifest(tmp_path)
    destination = tmp_path / "image.iso"
    directory = tmp_path / "state"
    directory.mkdir()
    new = state.new_state(manifest, destination)
    state.save_state(new, directory)
    return manifest, destination, directory, new


def state_files(directory):
    return sorted(os.listdir(directory))


def test_save_and_load_round_trip(saved):
    manifest, destination, directory, new = saved
    new.chunk_states = "CFP"
    state.save_state(new, directory)
    loaded = state.load_state(directory, manifest, destination)
    assert loaded == new


def test_state_is_stored_in_a_file_named_after_the_key(saved):
    manifest, destination, directory, new = saved
    key = state.state_key(manifest.global_hash, destination)
    assert state_files(directory) == [key + ".json"]
    assert state.state_path(directory, key) == directory / (key + ".json")


def test_no_temporary_file_is_left_after_saving(saved):
    manifest, destination, directory, new = saved
    for chunk_states in ("CPP", "CCP", "CCC"):
        new.chunk_states = chunk_states
        state.save_state(new, directory)
    assert len(state_files(directory)) == 1
    assert not any(name.endswith(".tmp") for name in state_files(directory))


def test_load_returns_none_when_there_is_no_state(tmp_path):
    manifest = make_manifest(tmp_path)
    assert state.load_state(tmp_path, manifest, tmp_path / "image.iso") is None


def test_save_syncs_the_file_before_replacing_and_then_the_directory(
    saved, monkeypatch
):
    manifest, destination, directory, new = saved
    events = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        events.append("fsync")
        real_fsync(fd)

    def replace(source, target):
        events.append("replace")
        real_replace(source, target)

    monkeypatch.setattr(state.os, "fsync", fsync)
    monkeypatch.setattr(state.os, "replace", replace)
    new.chunk_states = "CPP"
    state.save_state(new, directory)
    assert events == ["fsync", "replace", "fsync"]


def test_if_replace_fails_the_previous_state_stays_intact(saved, monkeypatch):
    manifest, destination, directory, new = saved
    previous = state.load_state(directory, manifest, destination)

    def failing_replace(source, target):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(state.os, "replace", failing_replace)
    new.chunk_states = "CCC"
    with pytest.raises(FilesystemError) as excinfo:
        state.save_state(new, directory)
    assert excinfo.value.exit_code == ExitCode.FILESYSTEM_ERROR
    monkeypatch.undo()
    assert state.load_state(directory, manifest, destination) == previous
    assert not any(name.endswith(".tmp") for name in state_files(directory))


def test_if_writing_fails_the_previous_state_stays_intact(saved, monkeypatch):
    manifest, destination, directory, new = saved
    previous = state.load_state(directory, manifest, destination)

    def disk_full(fd):
        raise OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))

    monkeypatch.setattr(state.os, "fsync", disk_full)
    new.chunk_states = "CCC"
    with pytest.raises(FilesystemError) as excinfo:
        state.save_state(new, directory)
    assert "No space left on device" in str(excinfo.value)
    monkeypatch.undo()
    assert state.load_state(directory, manifest, destination) == previous
    assert len(state_files(directory)) == 1


def test_save_into_a_missing_directory_is_a_filesystem_error(tmp_path):
    new = state.new_state(make_manifest(tmp_path), tmp_path / "image.iso")
    with pytest.raises(FilesystemError):
        state.save_state(new, tmp_path / "missing")


def test_load_validates_the_content(saved):
    manifest, destination, directory, new = saved
    (path,) = [directory / name for name in state_files(directory)]
    path.write_text(new.to_json().replace('"PPP"', '"PP"'))
    with pytest.raises(StateInvalidError):
        state.load_state(directory, manifest, destination)
    path.write_text("not json")
    with pytest.raises(StateInvalidError):
        state.load_state(directory, manifest, destination)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_state_is_a_filesystem_error(saved):
    manifest, destination, directory, new = saved
    (path,) = [directory / name for name in state_files(directory)]
    path.chmod(0)
    try:
        with pytest.raises(FilesystemError):
            state.load_state(directory, manifest, destination)
    finally:
        path.chmod(0o600)


# --- State directory (T40) ---

root_ignores_permissions = pytest.mark.skipif(
    os.geteuid() == 0, reason="root ignores file permissions"
)


def test_default_directory_is_created_under_xdg_state_home(tmp_path, monkeypatch):
    base = tmp_path / "xdg"
    monkeypatch.setenv("XDG_STATE_HOME", str(base))
    result = state.ensure_state_dir()
    assert result == base / "chunkget"
    assert result.is_dir()


def test_default_directory_without_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    result = state.ensure_state_dir()
    assert result == tmp_path / ".local" / "state" / "chunkget"
    assert result.is_dir()


def test_explicit_directory_is_used_and_created(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    explicit = tmp_path / "a" / "b" / "states"
    result = state.ensure_state_dir(explicit)
    assert result == explicit
    assert explicit.is_dir()
    # The default location is not touched.
    assert not (tmp_path / "xdg").exists()


def test_existing_directory_is_accepted_and_kept(tmp_path):
    directory = tmp_path / "states"
    directory.mkdir()
    (directory / "other.json").write_text("{}")
    assert state.ensure_state_dir(directory) == directory
    assert state.ensure_state_dir(directory) == directory
    assert os.listdir(directory) == ["other.json"]


def test_created_directory_is_private(tmp_path):
    directory = state.ensure_state_dir(tmp_path / "states")
    assert directory.stat().st_mode & 0o777 == 0o700


@root_ignores_permissions
def test_unwritable_existing_directory_is_a_filesystem_error(tmp_path):
    directory = tmp_path / "states"
    directory.mkdir()
    directory.chmod(0o500)
    try:
        with pytest.raises(FilesystemError) as excinfo:
            state.ensure_state_dir(directory)
    finally:
        directory.chmod(0o700)
    assert excinfo.value.exit_code == ExitCode.FILESYSTEM_ERROR
    assert str(directory) in str(excinfo.value)


@root_ignores_permissions
def test_directory_that_cannot_be_created_is_a_filesystem_error(tmp_path):
    parent = tmp_path / "readonly"
    parent.mkdir()
    parent.chmod(0o500)
    try:
        with pytest.raises(FilesystemError) as excinfo:
            state.ensure_state_dir(parent / "states")
    finally:
        parent.chmod(0o700)
    assert excinfo.value.exit_code == ExitCode.FILESYSTEM_ERROR


def test_a_file_in_place_of_the_directory_is_a_filesystem_error(tmp_path):
    path = tmp_path / "states"
    path.write_text("not a directory")
    with pytest.raises(FilesystemError):
        state.ensure_state_dir(path)


def test_the_directory_can_be_used_to_save_and_load_a_state(tmp_path):
    manifest = make_manifest(tmp_path)
    destination = tmp_path / "image.iso"
    directory = state.ensure_state_dir(tmp_path / "states")
    new = state.new_state(manifest, destination)
    state.save_state(new, directory)
    assert state.load_state(directory, manifest, destination) == new


# --- Download lock (T41) ---

import subprocess
import sys

from chunkget.errors import AlreadyRunningError

KEY = "0123456789abcdef0123456789abcdef"


def test_lock_creates_an_empty_lock_file_named_after_the_key(tmp_path):
    with state.lock_download(tmp_path, KEY):
        path = tmp_path / (KEY + ".lock")
        assert path == state.lock_path(tmp_path, KEY)
        assert path.is_file()
        assert path.stat().st_size == 0


def test_second_lock_for_the_same_key_fails(tmp_path):
    with state.lock_download(tmp_path, KEY):
        with pytest.raises(AlreadyRunningError) as excinfo:
            with state.lock_download(tmp_path, KEY):
                pytest.fail("the second lock must not be acquired")
    assert excinfo.value.exit_code == ExitCode.ALREADY_RUNNING


def test_lock_can_be_acquired_again_after_releasing(tmp_path):
    with state.lock_download(tmp_path, KEY):
        pass
    with state.lock_download(tmp_path, KEY):
        pass


def test_failed_attempt_does_not_release_the_first_lock(tmp_path):
    with state.lock_download(tmp_path, KEY):
        for _attempt in range(2):
            with pytest.raises(AlreadyRunningError):
                with state.lock_download(tmp_path, KEY):
                    pass


def test_lock_is_released_when_the_body_raises(tmp_path):
    with pytest.raises(RuntimeError):
        with state.lock_download(tmp_path, KEY):
            raise RuntimeError("boom")
    with state.lock_download(tmp_path, KEY):
        pass


def test_different_keys_do_not_conflict(tmp_path):
    with state.lock_download(tmp_path, KEY):
        with state.lock_download(tmp_path, "f" * 32):
            pass


def test_lock_file_is_kept_after_releasing(tmp_path):
    with state.lock_download(tmp_path, KEY):
        pass
    assert os.listdir(tmp_path) == [KEY + ".lock"]
    assert (tmp_path / (KEY + ".lock")).stat().st_size == 0


def test_lock_in_a_missing_directory_is_a_filesystem_error(tmp_path):
    with pytest.raises(FilesystemError):
        with state.lock_download(tmp_path / "missing", KEY):
            pass


def test_lock_is_held_across_processes(tmp_path):
    path = tmp_path / (KEY + ".lock")
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import fcntl, sys\n"
            "handle = open(sys.argv[1], 'a')\n"
            "fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
            "print('locked', flush=True)\n"
            "sys.stdin.read()\n",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(AlreadyRunningError):
            with state.lock_download(tmp_path, KEY):
                pass
    finally:
        holder.stdin.close()
        holder.wait(timeout=10)
    with state.lock_download(tmp_path, KEY):
        pass


def test_lock_error_message_is_translatable(tmp_path):
    import gettext

    from chunkget import i18n

    class Prefix(gettext.NullTranslations):
        def gettext(self, message):
            return "T: " + message

    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        with state.lock_download(tmp_path, KEY):
            with pytest.raises(AlreadyRunningError) as excinfo:
                with state.lock_download(tmp_path, KEY):
                    pass
    finally:
        i18n.set_translation(previous)
    assert str(excinfo.value).startswith("T: ")


# --- set_chunk_state (T42) ---


def test_set_chunk_state_is_saved_immediately(saved):
    manifest, destination, directory, new = saved
    state.set_chunk_state(new, 1, state.CORRECT, directory)
    state.set_chunk_state(new, 2, state.FAILED, directory)
    assert new.chunk_states == "PCF"
    # Read it back from disk, not from memory.
    on_disk = state.load_state(directory, manifest, destination)
    assert on_disk.chunk_states == "PCF"
    assert on_disk == new


def test_each_change_reaches_the_disk_before_the_next_one(saved):
    manifest, destination, directory, new = saved
    seen = []
    for index in range(3):
        state.set_chunk_state(new, index, state.CORRECT, directory)
        seen.append(
            state.load_state(directory, manifest, destination).chunk_states
        )
    assert seen == ["CPP", "CCP", "CCC"]


def test_a_chunk_can_change_state_again(saved):
    manifest, destination, directory, new = saved
    state.set_chunk_state(new, 0, state.FAILED, directory)
    state.set_chunk_state(new, 0, state.CORRECT, directory)
    state.set_chunk_state(new, 0, state.CORRECT, directory)
    assert state.load_state(directory, manifest, destination).chunk_states == "CPP"


@pytest.mark.parametrize("chunk_id", [-1, 3, 4, 100])
def test_chunk_id_out_of_range_is_an_error(saved, chunk_id):
    manifest, destination, directory, new = saved
    with pytest.raises(IndexError):
        state.set_chunk_state(new, chunk_id, state.CORRECT, directory)
    assert new.chunk_states == "PPP"
    assert state.load_state(directory, manifest, destination).chunk_states == "PPP"


@pytest.mark.parametrize("char", ["X", "c", "PC", "", " "])
def test_invalid_state_character_is_an_error(saved, char):
    manifest, destination, directory, new = saved
    with pytest.raises(ValueError):
        state.set_chunk_state(new, 0, char, directory)
    assert new.chunk_states == "PPP"


def test_state_in_memory_is_unchanged_if_saving_fails(saved, monkeypatch):
    manifest, destination, directory, new = saved

    def failing_replace(source, target):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(state.os, "replace", failing_replace)
    with pytest.raises(FilesystemError):
        state.set_chunk_state(new, 1, state.CORRECT, directory)
    assert new.chunk_states == "PPP"
    monkeypatch.undo()
    assert state.load_state(directory, manifest, destination).chunk_states == "PPP"


def test_chunk_state_of_an_empty_file_has_no_valid_id(tmp_path):
    manifest = make_manifest(tmp_path, size=0)
    directory = state.ensure_state_dir(tmp_path / "states")
    new = state.new_state(manifest, tmp_path / "image.iso")
    with pytest.raises(IndexError):
        state.set_chunk_state(new, 0, state.CORRECT, directory)
