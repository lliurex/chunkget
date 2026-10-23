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
