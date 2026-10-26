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
