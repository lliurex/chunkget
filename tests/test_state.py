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
