from pathlib import Path

import pytest

from chunkget import downloader, manifest_builder
from chunkget.errors import ExitCode, ManifestInvalidError, SourceError

DATA_URL = "http://127.0.0.1:8000/image.iso"


@pytest.fixture
def manifest_file(tmp_path):
    """A manifest of a small file, written to disk. Returns (manifest, path)."""
    source = tmp_path / "image.iso"
    source.write_bytes(bytes(index % 251 for index in range(250)))
    manifest = manifest_builder.build_manifest(source, DATA_URL, chunk_size=100)
    path = tmp_path / "image.iso.chunkget.manifest"
    path.write_bytes(manifest.to_json().encode("utf-8"))
    return manifest, path


# --- Resolving the manifest: local path or URL (T43) ---


def test_local_path_returns_the_manifest(manifest_file):
    manifest, path = manifest_file
    assert downloader.resolve_manifest(str(path), 5) == manifest


def test_path_object_is_accepted(manifest_file):
    manifest, path = manifest_file
    assert downloader.resolve_manifest(path, 5) == manifest


def test_url_returns_the_same_manifest_as_the_path(manifest_file, http_server):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    from_url = downloader.resolve_manifest(url, 5)
    assert from_url == downloader.resolve_manifest(str(path), 5) == manifest


def test_url_makes_a_single_request(manifest_file, http_server):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    downloader.resolve_manifest(url, 5)
    assert [r.path for r in http_server.requests] == ["/m.manifest"]


def test_url_scheme_is_case_insensitive(manifest_file, http_server):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    assert downloader.resolve_manifest("HTTP" + url[4:], 5) == manifest


def test_url_with_404_is_a_source_error(http_server):
    with pytest.raises(SourceError) as excinfo:
        downloader.resolve_manifest(http_server.url("/missing"), 5)
    assert excinfo.value.exit_code == ExitCode.SOURCE_ERROR


def test_url_with_content_that_is_not_a_manifest(http_server):
    url = http_server.serve("/m.manifest", b"this is not a manifest")
    with pytest.raises(ManifestInvalidError) as excinfo:
        downloader.resolve_manifest(url, 5)
    assert excinfo.value.exit_code == ExitCode.MANIFEST_INVALID


def test_url_with_a_json_that_is_not_a_valid_manifest(http_server):
    url = http_server.serve("/m.manifest", b'{"name": "x"}')
    with pytest.raises(ManifestInvalidError):
        downloader.resolve_manifest(url, 5)


def test_local_file_with_content_that_is_not_a_manifest(tmp_path):
    path = tmp_path / "m.manifest"
    path.write_bytes(b"garbage")
    with pytest.raises(ManifestInvalidError):
        downloader.resolve_manifest(path, 5)


def test_missing_local_file_is_a_source_error(tmp_path):
    with pytest.raises(SourceError):
        downloader.resolve_manifest(tmp_path / "missing", 5)


@pytest.mark.parametrize(
    "source",
    ["file:///etc/passwd", "ftp://example.com/m.manifest", "http://", "gopher://x/y"],
)
def test_urls_that_are_not_valid_http_urls_are_source_errors(source):
    with pytest.raises(SourceError):
        downloader.resolve_manifest(source, 5)


def test_path_with_a_colon_is_still_a_local_path(manifest_file, tmp_path):
    manifest, path = manifest_file
    odd = tmp_path / "a:b.manifest"
    odd.write_bytes(path.read_bytes())
    assert downloader.resolve_manifest(odd, 5) == manifest


# --- Saving the manifest in the download flow (T45) ---

import os

from chunkget import events
from chunkget.errors import FilesystemError, OutputExistsError

DEFAULT_NAME = "image.iso.chunkget.manifest"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """An empty current directory, apart from where the manifest file lives."""
    directory = tmp_path / "work"
    directory.mkdir()
    monkeypatch.chdir(directory)
    return directory


def obtain(source, listener=None, **kwargs):
    events_received = []
    manifest = downloader.obtain_manifest(
        source, 5, listener=listener or events_received.append, **kwargs
    )
    return manifest, events_received


def test_url_manifest_is_saved_and_the_download_continues_with_it(
    manifest_file, http_server, workdir
):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    result, received = obtain(url)
    assert result == manifest
    saved = workdir / DEFAULT_NAME
    assert saved.read_bytes() == path.read_bytes()
    assert [r.path for r in http_server.requests] == ["/m.manifest"]
    assert received == [events.ManifestSaved(path=DEFAULT_NAME)]


def test_manifest_file_selects_where_it_is_saved(
    manifest_file, http_server, workdir, tmp_path
):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    target = tmp_path / "elsewhere.manifest"
    _, received = obtain(url, manifest_file=target)
    assert target.read_bytes() == path.read_bytes()
    assert os.listdir(workdir) == []
    assert received == [events.ManifestSaved(path=str(target))]


def test_local_manifest_writes_nothing(manifest_file, workdir):
    manifest, path = manifest_file
    result, received = obtain(str(path))
    assert result == manifest
    assert os.listdir(workdir) == []
    assert received == []


def test_local_manifest_ignores_manifest_file(manifest_file, workdir, tmp_path):
    manifest, path = manifest_file
    target = tmp_path / "never.manifest"
    obtain(str(path), manifest_file=target)
    assert not target.exists()
    assert os.listdir(workdir) == []


def test_same_url_again_is_not_an_error(manifest_file, http_server, workdir):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    obtain(url)
    saved = workdir / DEFAULT_NAME
    os.utime(saved, (1_000_000, 1_000_000))
    result, received = obtain(url)
    assert result == manifest
    assert saved.stat().st_mtime == 1_000_000
    # The path is reported even though nothing was rewritten.
    assert received == [events.ManifestSaved(path=DEFAULT_NAME)]


def test_different_local_file_at_the_default_path_is_refused(
    manifest_file, http_server, workdir
):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    saved = workdir / DEFAULT_NAME
    saved.write_bytes(b"another manifest")
    with pytest.raises(OutputExistsError) as excinfo:
        obtain(url)
    assert excinfo.value.exit_code == ExitCode.USER_DECLINED
    assert saved.read_bytes() == b"another manifest"


def test_overwrite_manifest_replaces_the_different_file(
    manifest_file, http_server, workdir
):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    saved = workdir / DEFAULT_NAME
    saved.write_bytes(b"another manifest")
    result, _ = obtain(url, overwrite_manifest=True)
    assert result == manifest
    assert saved.read_bytes() == path.read_bytes()


def test_invalid_manifest_from_url_saves_nothing(http_server, workdir):
    url = http_server.serve("/m.manifest", b"not a manifest")
    received = []
    with pytest.raises(ManifestInvalidError):
        obtain(url, listener=received.append)
    assert os.listdir(workdir) == []
    assert received == []


def test_failed_fetch_saves_nothing(http_server, workdir):
    with pytest.raises(SourceError):
        obtain(http_server.url("/missing"))
    assert os.listdir(workdir) == []


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unwritable_location_is_a_filesystem_error(
    manifest_file, http_server, workdir
):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    workdir.chmod(0o500)
    try:
        with pytest.raises(FilesystemError):
            obtain(url)
    finally:
        workdir.chmod(0o700)


def test_listener_is_optional(manifest_file, http_server, workdir):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    assert downloader.obtain_manifest(url, 5) == manifest
    assert (workdir / DEFAULT_NAME).is_file()


def test_resolve_manifest_still_writes_nothing(manifest_file, http_server, workdir):
    manifest, path = manifest_file
    url = http_server.serve("/m.manifest", path.read_bytes())
    assert downloader.resolve_manifest(url, 5) == manifest
    assert os.listdir(workdir) == []


# --- Destination / state scenario (T46) ---

import itertools

from chunkget.downloader import Scenario, decide_scenario

SIZE = 1000
ABSENT, MATCHING, WRONG = None, SIZE, SIZE + 1


def test_scenario_names():
    assert {scenario.value for scenario in Scenario} == {
        "new",
        "new_discarding_state",
        "needs_confirmation",
        "resume",
        "inconsistent",
    }


def decide(destination_size, state_exists, restart=False, overwrite=False):
    return decide_scenario(
        destination_size, state_exists, SIZE, restart=restart, overwrite=overwrite
    )


@pytest.mark.parametrize(
    "destination_size, state_exists, expected",
    [
        # The five rows of the table of D14.
        (ABSENT, False, Scenario.NEW),
        (ABSENT, True, Scenario.NEW_DISCARDING_STATE),
        (MATCHING, False, Scenario.NEEDS_CONFIRMATION),
        (WRONG, True, Scenario.INCONSISTENT),
        (MATCHING, True, Scenario.RESUME),
    ],
)
def test_rows_of_the_table_of_d14(destination_size, state_exists, expected):
    assert decide(destination_size, state_exists) is expected


def test_existing_destination_of_any_size_without_state_needs_confirmation():
    for size in (0, 1, SIZE - 1, SIZE, SIZE + 1):
        assert decide(size, False) is Scenario.NEEDS_CONFIRMATION


def test_overwrite_accepts_an_existing_destination_without_state():
    assert decide(MATCHING, False, overwrite=True) is Scenario.NEW
    assert decide(WRONG, False, overwrite=True) is Scenario.NEW


def test_overwrite_does_not_hide_an_inconsistent_state():
    assert decide(WRONG, True, overwrite=True) is Scenario.INCONSISTENT


def test_overwrite_does_not_change_a_resume():
    assert decide(MATCHING, True, overwrite=True) is Scenario.RESUME


@pytest.mark.parametrize(
    "destination_size, state_exists, overwrite, expected",
    [
        (ABSENT, False, False, Scenario.NEW),
        (ABSENT, False, True, Scenario.NEW),
        (ABSENT, True, False, Scenario.NEW_DISCARDING_STATE),
        (ABSENT, True, True, Scenario.NEW_DISCARDING_STATE),
        (MATCHING, False, False, Scenario.NEEDS_CONFIRMATION),
        (WRONG, False, False, Scenario.NEEDS_CONFIRMATION),
        (MATCHING, False, True, Scenario.NEW),
        (WRONG, False, True, Scenario.NEW),
        (MATCHING, True, False, Scenario.NEEDS_CONFIRMATION),
        (WRONG, True, False, Scenario.NEEDS_CONFIRMATION),
        (MATCHING, True, True, Scenario.NEW_DISCARDING_STATE),
        (WRONG, True, True, Scenario.NEW_DISCARDING_STATE),
    ],
)
def test_effect_of_restart(destination_size, state_exists, overwrite, expected):
    assert decide(
        destination_size, state_exists, restart=True, overwrite=overwrite
    ) is expected


def test_restart_resolves_what_would_have_been_inconsistent():
    assert decide(WRONG, True) is Scenario.INCONSISTENT
    assert decide(WRONG, True, restart=True, overwrite=True) is (
        Scenario.NEW_DISCARDING_STATE
    )


def test_restart_never_resumes():
    for destination_size, state_exists, overwrite in itertools.product(
        (ABSENT, MATCHING, WRONG), (False, True), (False, True)
    ):
        assert decide(
            destination_size, state_exists, restart=True, overwrite=overwrite
        ) is not Scenario.RESUME


def test_empty_manifest_and_empty_destination_resume():
    assert decide_scenario(0, True, 0) is Scenario.RESUME
    assert decide_scenario(1, True, 0) is Scenario.INCONSISTENT
    assert decide_scenario(0, True, 5) is Scenario.INCONSISTENT


def test_decision_depends_only_on_its_arguments():
    arguments = (MATCHING, True, SIZE)
    assert decide_scenario(*arguments) is decide_scenario(*arguments)


# --- Applying the scenario (T47) ---

from chunkget import state as state_module
from chunkget.errors import DestinationExistsError, StateInvalidError


@pytest.fixture
def setup(manifest_file, tmp_path):
    """(manifest, destination, state_dir) with nothing created yet."""
    manifest, _path = manifest_file
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return manifest, tmp_path / "out" / "image.iso", state_dir


def prepare(setup, **kwargs):
    manifest, destination, state_dir = setup
    destination.parent.mkdir(exist_ok=True)
    return downloader.prepare_download(manifest, destination, state_dir, **kwargs)


def saved_state(setup):
    manifest, destination, state_dir = setup
    return state_module.load_state(state_dir, manifest, destination)


def test_new_creates_destination_and_state(setup):
    manifest, destination, _dir = setup
    result = prepare(setup)
    assert destination.stat().st_size == manifest.size
    assert destination.read_bytes() == bytes(manifest.size)
    assert result.chunk_states == "PPP"
    assert result.status == state_module.IN_PROGRESS
    assert saved_state(setup) == result


def test_new_discarding_state_replaces_the_old_state(setup):
    manifest, destination, state_dir = setup
    old = state_module.new_state(manifest, destination)
    old.chunk_states = "CCF"
    state_module.save_state(old, state_dir)
    result = prepare(setup)
    assert destination.stat().st_size == manifest.size
    assert result.chunk_states == "PPP"
    assert saved_state(setup).chunk_states == "PPP"


def test_discarded_state_may_be_corrupt(setup):
    manifest, destination, state_dir = setup
    key = state_module.state_key(manifest.global_hash, destination)
    state_module.state_path(state_dir, key).write_text("not json")
    assert prepare(setup).chunk_states == "PPP"
    assert saved_state(setup).chunk_states == "PPP"


def test_needs_confirmation_raises_and_changes_nothing(setup):
    manifest, destination, state_dir = setup
    destination.parent.mkdir()
    destination.write_bytes(b"precious")
    with pytest.raises(DestinationExistsError) as excinfo:
        prepare(setup)
    assert excinfo.value.exit_code == ExitCode.USER_DECLINED
    assert destination.read_bytes() == b"precious"
    assert list(state_dir.iterdir()) == []


def test_overwrite_accepts_an_existing_destination(setup):
    manifest, destination, _dir = setup
    destination.parent.mkdir()
    destination.write_bytes(b"old content")
    result = prepare(setup, overwrite=True)
    assert destination.stat().st_size == manifest.size
    assert result.chunk_states == "PPP"
    assert saved_state(setup) == result


def test_inconsistent_raises_and_changes_nothing(setup):
    manifest, destination, state_dir = setup
    destination.parent.mkdir()
    destination.write_bytes(b"short")
    existing = state_module.new_state(manifest, destination)
    state_module.save_state(existing, state_dir)
    with pytest.raises(StateInvalidError) as excinfo:
        prepare(setup)
    assert excinfo.value.exit_code == ExitCode.STATE_INVALID
    assert destination.read_bytes() == b"short"
    assert saved_state(setup) == existing


def test_resume_loads_the_state_and_keeps_the_destination(setup):
    manifest, destination, state_dir = setup
    prepare(setup)
    destination.write_bytes(b"x" * manifest.size)
    done = saved_state(setup)
    state_module.set_chunk_state(done, 0, state_module.CORRECT, state_dir)
    result = prepare(setup)
    assert result.chunk_states == "CPP"
    assert destination.read_bytes() == b"x" * manifest.size


def test_resume_with_a_corrupt_state_is_a_state_error(setup):
    manifest, destination, state_dir = setup
    prepare(setup)
    key = state_module.state_key(manifest.global_hash, destination)
    state_module.state_path(state_dir, key).write_text("not json")
    with pytest.raises(StateInvalidError):
        prepare(setup)


def test_restart_discards_the_state_of_an_existing_destination(setup):
    manifest, destination, state_dir = setup
    prepare(setup)
    done = saved_state(setup)
    state_module.set_chunk_state(done, 0, state_module.CORRECT, state_dir)
    with pytest.raises(DestinationExistsError):
        prepare(setup, restart=True)
    assert saved_state(setup).chunk_states == "CPP"
    assert prepare(setup, restart=True, overwrite=True).chunk_states == "PPP"
    assert saved_state(setup).chunk_states == "PPP"


def test_restart_resizes_a_destination_of_the_wrong_size(setup):
    manifest, destination, _dir = setup
    prepare(setup)
    destination.write_bytes(b"short")
    prepare(setup, restart=True, overwrite=True)
    assert destination.stat().st_size == manifest.size


def test_empty_manifest_creates_an_empty_destination(tmp_path):
    source = tmp_path / "empty"
    source.write_bytes(b"")
    manifest = manifest_builder.build_manifest(source, DATA_URL, chunk_size=100)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    destination = tmp_path / "empty.out"
    result = downloader.prepare_download(manifest, destination, state_dir)
    assert destination.read_bytes() == b""
    assert result.chunk_states == ""


def test_no_space_creates_no_state(setup, monkeypatch):
    from chunkget.errors import NoSpaceError

    def no_space(*args):
        raise NoSpaceError("full")

    monkeypatch.setattr("chunkget.storage.check_destination_space", no_space)
    manifest, destination, state_dir = setup
    with pytest.raises(NoSpaceError):
        prepare(setup)
    assert not destination.exists()
    assert list(state_dir.iterdir()) == []


# --- Downloading one chunk (T48) ---

import dataclasses

from chunkget.errors import NetworkError, ServerIncompatibleError
from chunkget.downloader import ChunkResult

CONTENT = bytes(index % 251 for index in range(250))


@pytest.fixture
def chunk_setup(tmp_path, http_server):
    """(manifest, destination, server) for a 250-byte file in chunks of 100."""
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    manifest = manifest_builder.build_manifest(source, url, chunk_size=100)
    destination = tmp_path / "out.iso"
    destination.write_bytes(bytes(len(CONTENT)))
    return manifest, destination, http_server


def fetch_chunk(chunk_setup, index):
    manifest, destination, _server = chunk_setup
    return downloader.download_chunk(manifest, manifest.chunks[index], destination, 5)


def test_correct_data_is_written_in_place(chunk_setup):
    manifest, destination, _server = chunk_setup
    assert fetch_chunk(chunk_setup, 1) is ChunkResult.CORRECT
    data = destination.read_bytes()
    assert data[100:200] == CONTENT[100:200]
    assert data[:100] == bytes(100) and data[200:] == bytes(50)


def test_last_shorter_chunk_is_correct(chunk_setup):
    manifest, destination, _server = chunk_setup
    assert fetch_chunk(chunk_setup, 2) is ChunkResult.CORRECT
    assert destination.read_bytes()[200:] == CONTENT[200:]


def test_requests_exactly_the_range_of_the_chunk(chunk_setup):
    fetch_chunk(chunk_setup, 1)
    assert [r.range for r in chunk_setup[2].requests] == ["bytes=100-199"]


def test_corrupt_bytes_are_a_bad_hash_not_an_exception(chunk_setup):
    manifest, _destination, server = chunk_setup
    server.corrupt_range("/image.iso", 100, 110)
    assert fetch_chunk(chunk_setup, 1) is ChunkResult.BAD_HASH
    assert fetch_chunk(chunk_setup, 0) is ChunkResult.CORRECT


def test_cut_connection_is_a_network_failure(chunk_setup):
    chunk_setup[2].cut_connection_after("/image.iso", 40)
    assert fetch_chunk(chunk_setup, 1) is ChunkResult.NETWORK_FAILURE


def test_retryable_status_is_a_network_failure(chunk_setup):
    chunk_setup[2].respond_with_statuses("/image.iso", [503])
    assert fetch_chunk(chunk_setup, 0) is ChunkResult.NETWORK_FAILURE


def test_fatal_http_error_is_raised(chunk_setup):
    chunk_setup[2].respond_with_statuses("/image.iso", [404])
    with pytest.raises(NetworkError):
        fetch_chunk(chunk_setup, 0)


def test_incompatible_server_is_raised_and_nothing_is_written(chunk_setup):
    manifest, destination, server = chunk_setup
    server.ignore_range("/image.iso")
    with pytest.raises(ServerIncompatibleError):
        fetch_chunk(chunk_setup, 1)
    assert destination.read_bytes() == bytes(len(CONTENT))


def test_hash_algorithm_comes_from_the_manifest(tmp_path, http_server):
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    manifest = manifest_builder.build_manifest(
        source, url, chunk_size=100, algorithm="sha3_256"
    )
    destination = tmp_path / "out.iso"
    destination.write_bytes(bytes(len(CONTENT)))
    result = downloader.download_chunk(manifest, manifest.chunks[0], destination, 5)
    assert result is ChunkResult.CORRECT


# --- One pass over the chunks (T49) ---


@pytest.fixture
def pass_setup(tmp_path, http_server):
    """Five chunks of 50 bytes: (manifest, destination, state, state_dir, server)."""
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    manifest = manifest_builder.build_manifest(source, url, chunk_size=50)
    destination = tmp_path / "out.iso"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    current = downloader.prepare_download(manifest, destination, state_dir)
    return manifest, destination, current, state_dir, http_server


def run_pass(pass_setup, listener=None):
    manifest, destination, current, state_dir, _server = pass_setup
    return downloader.run_pass(
        manifest, destination, current, state_dir, 5, listener=listener
    )


def disk_states(pass_setup):
    manifest, destination, _current, state_dir, _server = pass_setup
    return state_module.load_state(state_dir, manifest, destination).chunk_states


def test_pass_downloads_every_pending_chunk(pass_setup):
    manifest, destination, current, _dir, _server = pass_setup
    assert run_pass(pass_setup) is False
    assert current.chunk_states == "CCCCC"
    assert disk_states(pass_setup) == "CCCCC"
    assert destination.read_bytes() == CONTENT


def test_pass_skips_correct_chunks(pass_setup):
    manifest, destination, current, state_dir, server = pass_setup
    state_module.set_chunk_state(current, 0, state_module.CORRECT, state_dir)
    state_module.set_chunk_state(current, 3, state_module.CORRECT, state_dir)
    run_pass(pass_setup)
    assert [r.range for r in server.requests] == [
        "bytes=50-99",
        "bytes=100-149",
        "bytes=200-249",
    ]


def test_corrupt_chunk_is_failed_and_the_next_ones_go_on(pass_setup):
    server = pass_setup[4]
    server.corrupt_range("/image.iso", 50, 60)
    assert run_pass(pass_setup) is False
    assert disk_states(pass_setup) == "CFCCC"
    assert len(server.requests) == 5


def test_state_on_disk_is_updated_after_each_chunk(pass_setup):
    pass_setup[4].corrupt_range("/image.iso", 50, 60)
    seen = []

    def listener(event):
        if isinstance(event, events.ChunkDone):
            seen.append(disk_states(pass_setup))

    run_pass(pass_setup, listener)
    # Chunk 1 failed, so no event for it: events follow chunks 0, 2, 3 and 4.
    assert seen == ["CPPPP", "CFCPP", "CFCCP", "CFCCC"]


def test_events_report_the_pass_and_each_correct_chunk(pass_setup):
    received = []
    run_pass(pass_setup, received.append)
    assert received[0] == events.PassStarted(pending=5)
    assert received[1:] == [
        events.ChunkDone(index=i, total=5, bytes=50) for i in range(5)
    ]


def test_network_down_ends_the_pass_after_three_failures(pass_setup):
    server = pass_setup[4]
    server.cut_connection_after("/image.iso", 10)
    assert run_pass(pass_setup) is True
    assert len(server.requests) == 3
    assert disk_states(pass_setup) == "FFFPP"


def test_a_correct_chunk_resets_the_failure_count(pass_setup):
    server = pass_setup[4]
    # Chunks 0, 1 fail; chunk 2 works; chunks 3, 4 fail: never 3 in a row.
    server.cut_connection_after("/image.iso", 10, times=2)
    assert run_pass(pass_setup) is False
    assert disk_states(pass_setup) == "FFCCC"


def test_failed_chunks_are_tried_again_by_the_next_pass(pass_setup):
    server = pass_setup[4]
    server.cut_connection_after("/image.iso", 10, times=1)
    run_pass(pass_setup)
    assert disk_states(pass_setup) == "FCCCC"
    assert run_pass(pass_setup) is False
    assert disk_states(pass_setup) == "CCCCC"
    assert pass_setup[1].read_bytes() == CONTENT


def test_fatal_error_stops_the_pass_and_keeps_the_state(pass_setup):
    server = pass_setup[4]
    server.respond_with_statuses("/image.iso", [404])
    with pytest.raises(NetworkError):
        run_pass(pass_setup)
    assert disk_states(pass_setup) == "PPPPP"


def test_interruption_from_the_listener_keeps_finished_chunks(pass_setup):
    from chunkget.errors import InterruptedByUser

    def listener(event):
        if isinstance(event, events.ChunkDone) and event.index == 1:
            raise InterruptedByUser("stop")

    with pytest.raises(InterruptedByUser):
        run_pass(pass_setup, listener)
    assert disk_states(pass_setup) == "CCPPP"


# --- Retry passes (T50) ---

from chunkget.errors import RetriesExhaustedError


def run_passes(pass_setup, max_retries=5, listener=None):
    manifest, destination, current, state_dir, _server = pass_setup
    sleeps = []
    downloader.run_passes(
        manifest,
        destination,
        current,
        state_dir,
        5,
        max_retries,
        sleep=sleeps.append,
        listener=listener,
    )
    return sleeps


def test_no_retry_and_no_wait_when_the_first_pass_succeeds(pass_setup):
    assert run_passes(pass_setup) == []
    assert disk_states(pass_setup) == "CCCCC"


def test_chunk_that_fails_once_is_fixed_by_a_retry_pass(pass_setup):
    pass_setup[4].cut_connection_after("/image.iso", 10, times=1)
    assert run_passes(pass_setup) == [2]
    assert disk_states(pass_setup) == "CCCCC"
    assert pass_setup[1].read_bytes() == CONTENT


def test_waits_double_up_to_the_limit(pass_setup):
    pass_setup[4].corrupt_range("/image.iso", 50, 60)
    sleeps = []
    with pytest.raises(RetriesExhaustedError):
        downloader.run_passes(
            *pass_setup[:4], 5, 8, sleep=sleeps.append
        )
    assert sleeps == [2, 4, 8, 16, 32, 60, 60, 60]


def test_always_corrupt_chunk_gets_one_pass_plus_five_retries(pass_setup):
    server = pass_setup[4]
    server.corrupt_range("/image.iso", 50, 60)
    sleeps = []
    with pytest.raises(RetriesExhaustedError) as excinfo:
        downloader.run_passes(*pass_setup[:4], 5, 5, sleep=sleeps.append)
    assert excinfo.value.exit_code == ExitCode.RETRIES_EXHAUSTED
    assert sleeps == [2, 4, 8, 16, 32]
    chunk_1 = [r for r in server.requests if r.range == "bytes=50-99"]
    assert len(chunk_1) == 6
    assert "1" in str(excinfo.value)
    assert disk_states(pass_setup) == "CFCCC"


def test_message_has_the_number_of_failed_chunks(pass_setup):
    server = pass_setup[4]
    server.corrupt_range("/image.iso", 0, 250)
    with pytest.raises(RetriesExhaustedError) as excinfo:
        downloader.run_passes(*pass_setup[:4], 5, 1, sleep=lambda s: None)
    assert "5 chunks" in str(excinfo.value)


def test_max_retries_zero_means_a_single_pass(pass_setup):
    server = pass_setup[4]
    server.corrupt_range("/image.iso", 50, 60)
    sleeps = []
    with pytest.raises(RetriesExhaustedError):
        downloader.run_passes(*pass_setup[:4], 5, 0, sleep=sleeps.append)
    assert sleeps == []
    assert len(server.requests) == 5


def test_retry_events_announce_each_retry_pass(pass_setup):
    pass_setup[4].corrupt_range("/image.iso", 50, 60)
    received = []
    with pytest.raises(RetriesExhaustedError):
        downloader.run_passes(
            *pass_setup[:4], 5, 2, sleep=lambda s: None, listener=received.append
        )
    assert [e for e in received if isinstance(e, events.RetryStarted)] == [
        events.RetryStarted(attempt=1, max_retries=2, pending=1),
        events.RetryStarted(attempt=2, max_retries=2, pending=1),
    ]


def test_passes_cut_short_by_the_network_are_retried(pass_setup):
    # Three failures end the first pass; the retry pass finishes the job.
    pass_setup[4].cut_connection_after("/image.iso", 10, times=3)
    assert run_passes(pass_setup) == [2]
    assert disk_states(pass_setup) == "CCCCC"


def test_default_sleep_is_time_sleep(pass_setup, monkeypatch):
    pass_setup[4].cut_connection_after("/image.iso", 10, times=1)
    waits = []
    monkeypatch.setattr("time.sleep", waits.append)
    downloader.run_passes(*pass_setup[:4], 5, 5)
    assert waits == [2]


# --- Global hash validation (T51) ---

from chunkget.errors import GlobalHashMismatchError


def complete_download(pass_setup):
    manifest, destination, current, state_dir, _server = pass_setup
    downloader.run_passes(manifest, destination, current, state_dir, 5, 0)


def verify(pass_setup, loaded=None, listener=None):
    manifest, destination, current, state_dir, _server = pass_setup
    downloader.verify_global_hash(
        loaded or manifest, destination, current, state_dir, listener=listener
    )


def disk_status(pass_setup):
    manifest, destination, _current, state_dir, _server = pass_setup
    return state_module.load_state(state_dir, manifest, destination).status


def test_matching_hash_completes_the_state(pass_setup):
    complete_download(pass_setup)
    assert disk_status(pass_setup) == state_module.IN_PROGRESS
    verify(pass_setup)
    assert pass_setup[2].status == state_module.COMPLETED
    assert disk_status(pass_setup) == state_module.COMPLETED


def test_wrong_global_hash_fails_and_keeps_everything(pass_setup):
    manifest, destination, current, _dir, _server = pass_setup
    complete_download(pass_setup)
    bad = dataclasses.replace(manifest, global_hash="sha256:" + "0" * 64)
    # The state belongs to the manifest id, so the altered manifest is only
    # used for the comparison.
    with pytest.raises(GlobalHashMismatchError) as excinfo:
        verify(pass_setup, bad)
    assert excinfo.value.exit_code == ExitCode.GLOBAL_HASH_MISMATCH
    assert current.status == state_module.GLOBAL_CHECK_FAILED
    assert current.chunk_states == "CCCCC"
    assert destination.read_bytes() == CONTENT


def test_failed_status_is_saved_to_disk(pass_setup):
    manifest, destination, current, state_dir, _server = pass_setup
    complete_download(pass_setup)
    bad = dataclasses.replace(manifest, global_hash="sha256:" + "0" * 64)
    with pytest.raises(GlobalHashMismatchError):
        verify(pass_setup, bad)
    key = state_module.state_key(current.manifest_id, destination)
    saved = state_module.from_json(
        state_module.state_path(state_dir, key).read_bytes()
    )
    assert saved.status == state_module.GLOBAL_CHECK_FAILED


def test_global_check_events(pass_setup):
    complete_download(pass_setup)
    received = []
    verify(pass_setup, listener=received.append)
    assert received == [
        events.GlobalCheckStarted(algorithm="sha256"),
        events.Finished(destination=str(pass_setup[1])),
    ]


def test_no_finished_event_when_the_check_fails(pass_setup):
    complete_download(pass_setup)
    bad = dataclasses.replace(pass_setup[0], global_hash="sha256:" + "0" * 64)
    received = []
    with pytest.raises(GlobalHashMismatchError):
        verify(pass_setup, bad, received.append)
    assert [type(e) for e in received] == [events.GlobalCheckStarted]


def test_corrupted_file_with_correct_chunk_states_is_detected(pass_setup):
    complete_download(pass_setup)
    with open(pass_setup[1], "r+b") as handle:
        handle.write(b"\xff")
    with pytest.raises(GlobalHashMismatchError):
        verify(pass_setup)


def test_uses_the_algorithm_of_the_manifest(tmp_path, http_server):
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    manifest = manifest_builder.build_manifest(
        source, url, chunk_size=50, algorithm="sha3_512"
    )
    destination = tmp_path / "out.iso"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    current = downloader.prepare_download(manifest, destination, state_dir)
    downloader.run_passes(manifest, destination, current, state_dir, 5, 0)
    downloader.verify_global_hash(manifest, destination, current, state_dir)
    assert current.status == state_module.COMPLETED


def test_empty_file_is_verified_without_chunks(tmp_path):
    source = tmp_path / "empty"
    source.write_bytes(b"")
    manifest = manifest_builder.build_manifest(source, DATA_URL, chunk_size=100)
    destination = tmp_path / "empty.out"
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    current = downloader.prepare_download(manifest, destination, state_dir)
    downloader.verify_global_hash(manifest, destination, current, state_dir)
    assert current.status == state_module.COMPLETED


def test_chunks_not_correct_is_a_programming_error(pass_setup):
    with pytest.raises(ValueError):
        verify(pass_setup)


# --- The whole download and resuming it (T52) ---

from chunkget.errors import InterruptedByUser


@pytest.fixture
def full_setup(tmp_path, http_server):
    """(manifest path, destination, state_dir, server): 5 chunks of 50 bytes."""
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    manifest = manifest_builder.build_manifest(source, url, chunk_size=50)
    manifest_path = tmp_path / "image.iso.chunkget.manifest"
    manifest_path.write_bytes(manifest.to_json().encode("utf-8"))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return manifest_path, tmp_path / "out.iso", state_dir, http_server


def download(full_setup, **kwargs):
    manifest_path, destination, state_dir, _server = full_setup
    options = dict(timeout=5, max_retries=0, sleep=lambda seconds: None)
    options.update(kwargs)
    return downloader.download(manifest_path, destination, state_dir, **options)


def chunk_requests(server):
    return [r.range for r in server.requests if r.path == "/image.iso"]


def test_download_from_scratch(full_setup):
    result = download(full_setup)
    assert result == full_setup[1]
    assert full_setup[1].read_bytes() == CONTENT
    assert len(chunk_requests(full_setup[3])) == 5


def test_download_leaves_the_state_completed(full_setup):
    download(full_setup)
    [state_file] = [p for p in full_setup[2].iterdir() if p.suffix == ".json"]
    assert state_module.from_json(state_file.read_bytes()).status == "completed"


def test_resume_after_an_interruption_requests_only_the_pending_chunks(full_setup):
    server = full_setup[3]

    def interrupt(event):
        if isinstance(event, events.ChunkDone) and event.index == 1:
            raise InterruptedByUser("stop")

    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt)
    server.requests.clear()
    download(full_setup)
    assert chunk_requests(server) == ["bytes=100-149", "bytes=150-199", "bytes=200-249"]
    assert full_setup[1].read_bytes() == CONTENT


def test_resume_after_the_server_cut_the_connection(full_setup):
    server = full_setup[3]

    def cut_after_two_chunks(event):
        if isinstance(event, events.ChunkDone) and event.index == 1:
            server.cut_connection_after("/image.iso", 10)

    with pytest.raises(RetriesExhaustedError):
        download(full_setup, listener=cut_after_two_chunks)
    assert full_setup[1].read_bytes()[:100] == CONTENT[:100]
    server.cuts.clear()
    server.requests.clear()
    download(full_setup)
    assert chunk_requests(server) == ["bytes=100-149", "bytes=150-199", "bytes=200-249"]
    assert full_setup[1].read_bytes() == CONTENT


def test_resume_keeps_the_chunks_already_correct(full_setup):
    server = full_setup[3]

    def interrupt(event):
        if isinstance(event, events.ChunkDone) and event.index == 1:
            raise InterruptedByUser("stop")

    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt)
    # Serve other bytes: the finished chunks must not be asked for again.
    server.resources["/image.iso"] = bytes(250)
    with pytest.raises(RetriesExhaustedError):
        download(full_setup)
    assert full_setup[1].read_bytes()[:100] == CONTENT[:100]


def test_download_takes_the_manifest_from_a_url(full_setup, tmp_path, monkeypatch):
    manifest_path, destination, state_dir, server = full_setup
    url = server.serve("/m.manifest", manifest_path.read_bytes())
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    downloader.download(
        url, destination, state_dir, timeout=5, max_retries=0
    )
    assert destination.read_bytes() == CONTENT
    assert (work / "image.iso.chunkget.manifest").exists()


def test_destination_defaults_to_the_name_in_the_manifest(full_setup, tmp_path, monkeypatch):
    manifest_path, _destination, state_dir, _server = full_setup
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    result = downloader.download(manifest_path, None, state_dir, timeout=5, max_retries=0)
    assert result == Path("image.iso")
    assert (work / "image.iso").read_bytes() == CONTENT


def test_download_holds_the_lock(full_setup):
    manifest_path, destination, state_dir, _server = full_setup
    manifest = downloader.resolve_manifest(manifest_path)
    key = state_module.state_key(manifest.global_hash, destination)
    from chunkget.errors import AlreadyRunningError

    with state_module.lock_download(state_dir, key):
        with pytest.raises(AlreadyRunningError):
            download(full_setup)
    assert not destination.exists()


def test_download_creates_the_state_dir(full_setup, tmp_path):
    manifest_path, destination, _dir, _server = full_setup
    new_dir = tmp_path / "does" / "not" / "exist"
    downloader.download(manifest_path, destination, new_dir, timeout=5, max_retries=0)
    assert new_dir.is_dir()


# --- A download that is already complete (T53) ---


def test_repeating_a_finished_download_requests_no_chunks(full_setup):
    server = full_setup[3]
    download(full_setup)
    server.requests.clear()
    received = []
    result = download(full_setup, listener=received.append)
    assert result == full_setup[1]
    assert chunk_requests(server) == []
    assert full_setup[1].read_bytes() == CONTENT
    assert events.GlobalCheckStarted(algorithm="sha256") in received
    assert not any(isinstance(e, events.ChunkDone) for e in received)


def test_repeating_a_finished_download_keeps_it_completed(full_setup):
    download(full_setup)
    download(full_setup)
    [state_file] = [p for p in full_setup[2].iterdir() if p.suffix == ".json"]
    assert state_module.from_json(state_file.read_bytes()).status == "completed"


def test_finished_download_is_verified_again_not_trusted(full_setup):
    download(full_setup)
    with open(full_setup[1], "r+b") as handle:
        handle.write(b"\xff")
    with pytest.raises(GlobalHashMismatchError):
        download(full_setup)
    [state_file] = [p for p in full_setup[2].iterdir() if p.suffix == ".json"]
    assert (
        state_module.from_json(state_file.read_bytes()).status == "global_check_failed"
    )


def test_download_with_a_failed_global_check_is_verified_again(full_setup):
    download(full_setup)
    with open(full_setup[1], "r+b") as handle:
        handle.write(b"\xff")
    with pytest.raises(GlobalHashMismatchError):
        download(full_setup)
    with open(full_setup[1], "r+b") as handle:
        handle.write(CONTENT[:1])
    download(full_setup)
    [state_file] = [p for p in full_setup[2].iterdir() if p.suffix == ".json"]
    assert state_module.from_json(state_file.read_bytes()).status == "completed"


# --- Incompatible server: abort before writing data (T54) ---


def assert_nothing_was_written(full_setup, server):
    manifest_path, destination, state_dir, _server = full_setup
    assert destination.read_bytes() == bytes(len(CONTENT))
    [state_file] = [p for p in state_dir.iterdir() if p.suffix == ".json"]
    assert state_module.from_json(state_file.read_bytes()).chunk_states == "PPPPP"
    assert len(chunk_requests(server)) == 1


def test_server_that_ignores_range_aborts_with_code_11(full_setup):
    server = full_setup[3]
    server.ignore_range("/image.iso")
    with pytest.raises(ServerIncompatibleError) as excinfo:
        download(full_setup, max_retries=5)
    assert excinfo.value.exit_code == ExitCode.SERVER_INCOMPATIBLE
    assert_nothing_was_written(full_setup, server)


def test_server_with_a_different_total_aborts_with_code_11(full_setup):
    server = full_setup[3]
    server.report_total("/image.iso", len(CONTENT) + 1)
    with pytest.raises(ServerIncompatibleError) as excinfo:
        download(full_setup, max_retries=5)
    assert excinfo.value.exit_code == ExitCode.SERVER_INCOMPATIBLE
    assert_nothing_was_written(full_setup, server)


def test_server_with_content_encoding_aborts_with_code_11(full_setup):
    server = full_setup[3]
    server.set_content_encoding("/image.iso", "gzip")
    with pytest.raises(ServerIncompatibleError):
        download(full_setup, max_retries=5)
    assert_nothing_was_written(full_setup, server)


def test_incompatible_server_is_not_retried_or_waited_for(full_setup):
    full_setup[3].ignore_range("/image.iso")
    sleeps = []
    with pytest.raises(ServerIncompatibleError):
        download(full_setup, max_retries=5, sleep=sleeps.append)
    assert sleeps == []


# --- Interruption by the user (T55) ---


def interrupt_after(index):
    def listener(event):
        if isinstance(event, events.ChunkDone) and event.index == index:
            raise InterruptedByUser("stop")

    return listener


def saved_chunk_states(full_setup):
    [state_file] = [p for p in full_setup[2].iterdir() if p.suffix == ".json"]
    return state_module.from_json(state_file.read_bytes()).chunk_states


def test_interruption_leaves_the_finished_chunks_correct(full_setup):
    with pytest.raises(InterruptedByUser) as excinfo:
        download(full_setup, listener=interrupt_after(2))
    assert excinfo.value.exit_code == ExitCode.INTERRUPTED
    assert saved_chunk_states(full_setup) == "CCCPP"


def test_rerun_after_the_interruption_asks_only_for_chunk_3_onwards(full_setup):
    server = full_setup[3]
    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt_after(2))
    server.requests.clear()
    download(full_setup)
    assert chunk_requests(server) == ["bytes=150-199", "bytes=200-249"]
    assert full_setup[1].read_bytes() == CONTENT
    assert saved_chunk_states(full_setup) == "CCCCC"


def test_interruption_in_the_middle_of_a_chunk_keeps_its_state(full_setup, monkeypatch):
    real_write_chunk = downloader.storage.write_chunk
    calls = []

    def interrupted(path, start, stream, length, algorithm):
        calls.append(start)
        if len(calls) == 3:
            stream.read(10)  # some data of the third chunk arrives
            raise InterruptedByUser("stop")
        return real_write_chunk(path, start, stream, length, algorithm)

    monkeypatch.setattr(downloader.storage, "write_chunk", interrupted)
    with pytest.raises(InterruptedByUser):
        download(full_setup)
    assert saved_chunk_states(full_setup) == "CCPPP"
    monkeypatch.undo()
    full_setup[3].requests.clear()
    download(full_setup)
    assert chunk_requests(full_setup[3]) == [
        "bytes=100-149",
        "bytes=150-199",
        "bytes=200-249",
    ]
    assert full_setup[1].read_bytes() == CONTENT


def test_interruption_releases_the_lock_and_leaves_no_temporary_file(full_setup):
    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt_after(1))
    names = sorted(p.suffix for p in full_setup[2].iterdir())
    assert names == [".json", ".lock"]
    download(full_setup)  # the lock can be taken again


def test_interruption_is_not_retried(full_setup):
    sleeps = []
    with pytest.raises(InterruptedByUser):
        download(
            full_setup, max_retries=5, sleep=sleeps.append, listener=interrupt_after(0)
        )
    assert sleeps == []


# --- Network cut in the middle of a chunk (T56) ---


@pytest.fixture
def cut_in_chunk_1(full_setup):
    """Arms a single cut in the middle of chunk 1, once chunk 0 is done."""
    server = full_setup[3]

    def listener(event):
        if isinstance(event, events.ChunkDone) and event.index == 0:
            server.cut_connection_after("/image.iso", 20, times=1)

    return listener


def test_chunk_cut_in_the_middle_is_failed_and_the_others_go_on(
    full_setup, cut_in_chunk_1
):
    states_at_retry = []

    def listener(event):
        cut_in_chunk_1(event)
        if isinstance(event, events.RetryStarted):
            states_at_retry.append(saved_chunk_states(full_setup))

    download(full_setup, max_retries=1, listener=listener)
    assert states_at_retry == ["CFCCC"]


def test_retry_pass_downloads_the_cut_chunk_and_the_file_is_identical(
    full_setup, cut_in_chunk_1
):
    sleeps = []
    download(full_setup, max_retries=5, sleep=sleeps.append, listener=cut_in_chunk_1)
    assert sleeps == [2]
    assert full_setup[1].read_bytes() == CONTENT
    assert saved_chunk_states(full_setup) == "CCCCC"
    assert chunk_requests(full_setup[3]) == [
        "bytes=0-49",
        "bytes=50-99",  # cut
        "bytes=100-149",
        "bytes=150-199",
        "bytes=200-249",
        "bytes=50-99",  # retry pass
    ]


def test_without_retries_the_cut_chunk_is_reported_as_incomplete(
    full_setup, cut_in_chunk_1
):
    with pytest.raises(RetriesExhaustedError) as excinfo:
        download(full_setup, max_retries=0, listener=cut_in_chunk_1)
    assert "1 chunks" in str(excinfo.value)
    assert saved_chunk_states(full_setup) == "CFCCC"
    assert full_setup[1].read_bytes()[100:] == CONTENT[100:]
    # Running again fixes only that chunk.
    full_setup[3].requests.clear()
    download(full_setup)
    assert chunk_requests(full_setup[3]) == ["bytes=50-99"]
    assert full_setup[1].read_bytes() == CONTENT


# --- Empty files and files smaller than a chunk (T57) ---


def manifest_for(tmp_path, http_server, data, chunk_size):
    """Write the manifest of ``data`` served by the test server."""
    source = tmp_path / "source.bin"
    source.write_bytes(data)
    url = http_server.serve("/image.iso", data)
    built = manifest_builder.build_manifest(source, url, chunk_size=chunk_size)
    path = tmp_path / "m.chunkget.manifest"
    path.write_bytes(built.to_json().encode("utf-8"))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return path, tmp_path / "out.bin", state_dir


def test_empty_file_is_created_and_verified_without_requests(tmp_path, http_server):
    manifest_path, destination, state_dir = manifest_for(tmp_path, http_server, b"", 100)
    received = []
    downloader.download(
        manifest_path, destination, state_dir, timeout=5, listener=received.append
    )
    assert destination.read_bytes() == b""
    assert http_server.requests == []
    assert events.GlobalCheckStarted(algorithm="sha256") in received
    [state_file] = [p for p in state_dir.iterdir() if p.suffix == ".json"]
    loaded = state_module.from_json(state_file.read_bytes())
    assert (loaded.chunk_states, loaded.status) == ("", "completed")


def test_empty_file_over_an_existing_empty_destination_needs_confirmation(
    tmp_path, http_server
):
    manifest_path, destination, state_dir = manifest_for(tmp_path, http_server, b"", 100)
    destination.write_bytes(b"")
    with pytest.raises(DestinationExistsError):
        downloader.download(manifest_path, destination, state_dir, timeout=5)
    downloader.download(manifest_path, destination, state_dir, timeout=5, overwrite=True)
    assert destination.read_bytes() == b""


def test_empty_file_repeated_still_verifies(tmp_path, http_server):
    manifest_path, destination, state_dir = manifest_for(tmp_path, http_server, b"", 100)
    downloader.download(manifest_path, destination, state_dir, timeout=5)
    downloader.download(manifest_path, destination, state_dir, timeout=5)
    assert http_server.requests == []


def test_file_smaller_than_a_chunk_takes_a_single_request(tmp_path, http_server):
    data = b"hello chunkget"
    manifest_path, destination, state_dir = manifest_for(tmp_path, http_server, data, 100)
    downloader.download(manifest_path, destination, state_dir, timeout=5)
    assert destination.read_bytes() == data
    assert [r.range for r in http_server.requests] == ["bytes=0-13"]


def test_file_of_exactly_one_chunk(tmp_path, http_server):
    data = bytes(range(100))
    manifest_path, destination, state_dir = manifest_for(tmp_path, http_server, data, 100)
    downloader.download(manifest_path, destination, state_dir, timeout=5)
    assert destination.read_bytes() == data
    assert [r.range for r in http_server.requests] == ["bytes=0-99"]


# --- restart and stale state (T58) ---


def test_restart_downloads_every_chunk_again(full_setup):
    server = full_setup[3]
    download(full_setup)
    server.requests.clear()
    download(full_setup, restart=True, overwrite=True)
    assert len(chunk_requests(server)) == 5
    assert full_setup[1].read_bytes() == CONTENT
    assert saved_chunk_states(full_setup) == "CCCCC"


def test_restart_discards_the_saved_state(full_setup):
    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt_after(2))
    assert saved_chunk_states(full_setup) == "CCCPP"
    full_setup[3].requests.clear()
    seen = []

    def listener(event):
        if isinstance(event, events.PassStarted):
            seen.append(saved_chunk_states(full_setup))

    download(full_setup, restart=True, overwrite=True, listener=listener)
    assert seen == ["PPPPP"]
    assert len(chunk_requests(full_setup[3])) == 5


def test_restart_still_asks_before_replacing_the_destination(full_setup):
    download(full_setup)
    full_setup[3].requests.clear()
    with pytest.raises(DestinationExistsError):
        download(full_setup, restart=True)
    assert chunk_requests(full_setup[3]) == []
    assert saved_chunk_states(full_setup) == "CCCCC"


def test_restart_replaces_a_wrong_size_destination_instead_of_failing(full_setup):
    download(full_setup)
    full_setup[1].write_bytes(b"short")
    with pytest.raises(StateInvalidError):
        download(full_setup)
    download(full_setup, restart=True, overwrite=True)
    assert full_setup[1].read_bytes() == CONTENT


def test_restart_without_a_state_is_a_new_download(full_setup):
    download(full_setup, restart=True)
    assert full_setup[1].read_bytes() == CONTENT


def test_state_whose_destination_is_gone_is_discarded_with_a_warning(full_setup):
    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt_after(2))
    full_setup[1].unlink()
    full_setup[3].requests.clear()
    received = []
    download(full_setup, listener=received.append)
    assert events.StaleStateDiscarded(destination=str(full_setup[1])) in received
    assert len(chunk_requests(full_setup[3])) == 5
    assert full_setup[1].read_bytes() == CONTENT


def test_no_warning_when_the_state_is_resumed_or_new(full_setup):
    received = []
    with pytest.raises(InterruptedByUser):
        download(full_setup, listener=interrupt_after(1))
    download(full_setup, listener=received.append)
    assert not any(isinstance(e, events.StaleStateDiscarded) for e in received)


def test_no_warning_on_restart(full_setup):
    download(full_setup)
    received = []
    download(full_setup, restart=True, overwrite=True, listener=received.append)
    assert not any(isinstance(e, events.StaleStateDiscarded) for e in received)
