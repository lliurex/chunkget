import hashlib
import io
import re

import pytest

from chunkget import cli, manifest_builder

CONTENT = bytes(index % 251 for index in range(250))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A current directory and a state directory of their own."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return work


@pytest.fixture
def served(tmp_path, http_server):
    """(server, local manifest path, manifest URL) of a 250-byte file, 5 chunks."""
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    built = manifest_builder.build_manifest(source, url, chunk_size=50)
    text = built.to_json().encode("utf-8")
    path = tmp_path / "m.chunkget.manifest"
    path.write_bytes(text)
    manifest_url = http_server.serve("/image.iso.chunkget.manifest", text)
    return http_server, path, manifest_url


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- A download from a local manifest (T72) ---


def test_download_succeeds(env, served, capsys):
    server, path, _url = served
    code, out, err = run(capsys, "download", str(path))
    assert code == 0
    assert out == "Download completed: image.iso\n"
    assert (env / "image.iso").read_bytes() == CONTENT


def test_progress_lines_on_stderr(env, served, capsys):
    server, path, _url = served
    code, out, err = run(capsys, "download", str(path))
    lines = err.splitlines()
    chunk_lines = [line for line in lines if line.startswith("Downloading")]
    assert len(chunk_lines) == 5
    assert chunk_lines[0] == "Downloading image.iso: chunk 1/5 (20.0%), 50 B of 250 B"
    assert chunk_lines[-1] == "Downloading image.iso: chunk 5/5 (100.0%), 250 B of 250 B"
    assert lines[-1] == "Global hash verified (sha256)."


def test_progress_format_with_big_sizes(env, tmp_path, capsys, monkeypatch):
    # 12th chunk of 768 of 4 MiB each: the example of the plan.
    reporter = cli._DownloadReporter()
    from chunkget import events

    reporter(events.DownloadStarted(name="image.iso", size=768 * 4 * 1024**2, done_bytes=0))
    for index in range(12):
        reporter(events.ChunkDone(index=index, total=768, bytes=4 * 1024**2))
    err = capsys.readouterr().err
    assert err.splitlines()[-1] == (
        "Downloading image.iso: chunk 12/768 (1.6%), 48.0 MiB of 3.0 GiB"
    )


def test_stdout_only_has_the_result(env, served, capsys):
    code, out, err = run(capsys, "download", str(served[1]))
    assert out.count("\n") == 1
    assert "Downloading" not in out and "hash" not in out


def test_resumed_download_counts_the_bytes_already_done(env, served, capsys, monkeypatch):
    from chunkget import events

    reporter = cli._DownloadReporter()
    reporter(events.DownloadStarted(name="f", size=250, done_bytes=100))
    reporter(events.ChunkDone(index=2, total=5, bytes=50))
    assert capsys.readouterr().err.strip() == "Downloading f: chunk 3/5 (60.0%), 150 B of 250 B"


def test_retry_pass_line(env, served, capsys):
    from chunkget import events

    reporter = cli._DownloadReporter()
    reporter(events.RetryStarted(attempt=2, max_retries=5, pending=7))
    reporter(events.RetryStarted(attempt=1, max_retries=5, pending=1))
    lines = capsys.readouterr().err.splitlines()
    assert lines == [
        "Retry pass 2/5: 7 chunks pending",
        "Retry pass 1/5: 1 chunk pending",
    ]


def test_failed_chunks_are_retried_and_reported(env, served, capsys, monkeypatch):
    server, path, _url = served
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    server.cut_connection_after("/image.iso", 10, times=1)
    code, out, err = run(capsys, "download", str(path))
    assert code == 0
    assert "Retry pass 1/5: 1 chunk pending" in err
    assert (env / "image.iso").read_bytes() == CONTENT


# --- Manifest by URL ---


def test_manifest_url_prints_manifest_saved_first(env, served, capsys):
    server, _path, manifest_url = served
    code, out, err = run(capsys, "download", manifest_url)
    assert code == 0
    assert out.splitlines() == [
        "Manifest saved: image.iso.chunkget.manifest",
        "Download completed: image.iso",
    ]
    assert (env / "image.iso.chunkget.manifest").exists()
    assert (env / "image.iso").read_bytes() == CONTENT


def test_local_manifest_prints_no_manifest_saved(env, served, capsys):
    code, out, err = run(capsys, "download", str(served[1]))
    assert "Manifest saved" not in out
    assert [p.name for p in env.iterdir()] == ["image.iso"]


# --- Terminal output ---


class TtyStream(io.StringIO):
    def isatty(self):
        return True


def test_on_a_terminal_the_line_is_rewritten(env, served, capsys, monkeypatch):
    from chunkget import events

    stream = TtyStream()
    monkeypatch.setattr("sys.stderr", stream)
    reporter = cli._DownloadReporter()
    reporter(events.DownloadStarted(name="f", size=100, done_bytes=0))
    reporter(events.ChunkDone(index=0, total=2, bytes=50))
    reporter(events.ChunkDone(index=1, total=2, bytes=50))
    reporter(events.GlobalCheckStarted(algorithm="sha256"))
    reporter(events.Finished(destination="f"))
    text = stream.getvalue()
    assert text.count("\r") == 2
    assert "\n" in text
    assert text.index("chunk 2/2") < text.index("Global hash verified")
    # The progress line is ended before the next message.
    assert re.search(r"chunk 2/2.*\nGlobal hash verified", text, re.S)


def test_not_on_a_terminal_there_is_no_carriage_return(env, served, capsys):
    code, out, err = run(capsys, "download", str(served[1]))
    assert "\r" not in err


# --- Errors ---


def test_missing_manifest_is_code_3(env, capsys):
    code, out, err = run(capsys, "download", "missing.manifest")
    assert code == 3
    assert out == ""
    assert err.startswith("chunkget: error: ")


def test_invalid_manifest_is_code_5(env, capsys):
    (env / "bad.manifest").write_text("not a manifest")
    code, out, err = run(capsys, "download", "bad.manifest")
    assert code == 5


def test_texts_are_translatable(env, served, capsys):
    from chunkget import i18n

    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        code, out, err = run(capsys, "download", str(served[1]))
    finally:
        i18n.set_translation(previous)
    assert code == 0
    assert out.startswith("«T»Download completed")
    assert all(line.startswith("«T»") for line in err.splitlines())


# --- Questions and options (T73) ---

from chunkget import manifest as manifest_module


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.fixture
def stdin(monkeypatch):
    def set_stdin(text="", tty=True):
        monkeypatch.setattr("sys.stdin", FakeStdin(text, tty))

    return set_stdin


# Destination that exists without a state


def test_existing_destination_asks_and_yes_replaces_it(env, served, capsys, stdin):
    (env / "image.iso").write_bytes(b"precious")
    stdin("y\n")
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 0
    assert "image.iso" in err and "overwrite" in err.lower()
    assert (env / "image.iso").read_bytes() == CONTENT


@pytest.mark.parametrize("answer", ["n", "", "no"])
def test_existing_destination_declined(env, served, capsys, stdin, answer):
    (env / "image.iso").write_bytes(b"precious")
    stdin(answer + "\n")
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 4
    assert out == ""
    assert (env / "image.iso").read_bytes() == b"precious"
    assert served[0].requests == []


def test_existing_destination_with_yes_option(env, served, capsys, stdin):
    (env / "image.iso").write_bytes(b"precious")
    stdin("", tty=False)
    code, out, err = run(capsys, "download", str(served[1]), "-y")
    assert code == 0
    assert "overwrite" not in err.lower()
    assert (env / "image.iso").read_bytes() == CONTENT


def test_existing_destination_without_terminal(env, served, capsys, stdin):
    (env / "image.iso").write_bytes(b"precious")
    stdin("y\n", tty=False)
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 4
    assert (env / "image.iso").read_bytes() == b"precious"


# Manifest downloaded from a URL that differs from the local file


def local_manifest(env):
    path = env / "image.iso.chunkget.manifest"
    path.write_text("a different manifest")
    return path


def test_different_local_manifest_yes_replaces_it(env, served, capsys, stdin):
    path = local_manifest(env)
    stdin("y\n")
    code, out, err = run(capsys, "download", served[2])
    assert code == 0
    assert path.name in err and "overwrite" in err.lower()
    assert path.read_bytes() == served[1].read_bytes()
    assert (env / "image.iso").read_bytes() == CONTENT


@pytest.mark.parametrize("answer", ["n", ""])
def test_different_local_manifest_declined(env, served, capsys, stdin, answer):
    path = local_manifest(env)
    stdin(answer + "\n")
    code, out, err = run(capsys, "download", served[2])
    assert code == 4
    assert out == ""
    assert path.read_text() == "a different manifest"
    assert not (env / "image.iso").exists()


def test_different_local_manifest_with_yes_option(env, served, capsys, stdin):
    path = local_manifest(env)
    stdin("", tty=False)
    code, out, err = run(capsys, "download", served[2], "-y")
    assert code == 0
    assert path.read_bytes() == served[1].read_bytes()


def test_different_local_manifest_without_terminal(env, served, capsys, stdin):
    path = local_manifest(env)
    stdin("y\n", tty=False)
    code, out, err = run(capsys, "download", served[2])
    assert code == 4
    assert path.read_text() == "a different manifest"


def test_same_manifest_url_again_asks_nothing(env, served, capsys, stdin):
    stdin("", tty=False)
    assert run(capsys, "download", served[2])[0] == 0
    code, out, err = run(capsys, "download", served[2])
    assert code == 0
    assert "overwrite" not in err.lower()


def test_both_questions_are_asked_in_order(env, served, capsys, stdin):
    local_manifest(env)
    (env / "image.iso").write_bytes(b"precious")
    stdin("y\ny\n")
    code, out, err = run(capsys, "download", served[2])
    assert code == 0
    assert err.index("image.iso.chunkget.manifest") < err.index("Downloading")
    assert (env / "image.iso").read_bytes() == CONTENT


def test_manifest_is_requested_only_once_when_nothing_conflicts(
    env, served, capsys, stdin
):
    stdin("", tty=False)
    run(capsys, "download", served[2])
    paths = [r.path for r in served[0].requests]
    assert paths.count("/image.iso.chunkget.manifest") == 1


# Options


def test_output_option_selects_the_destination(env, served, tmp_path, capsys):
    target = tmp_path / "elsewhere.bin"
    code, out, err = run(capsys, "download", str(served[1]), "-o", str(target))
    assert code == 0
    assert out == "Download completed: %s\n" % target
    assert target.read_bytes() == CONTENT
    assert not (env / "image.iso").exists()


def test_long_output_option(env, served, tmp_path, capsys):
    target = tmp_path / "x.bin"
    assert run(capsys, "download", str(served[1]), "--output", str(target))[0] == 0
    assert target.exists()


def test_state_dir_option_places_the_state_there(env, served, tmp_path, capsys):
    state_dir = tmp_path / "my_state"
    code, *_ = run(capsys, "download", str(served[1]), "--state-dir", str(state_dir))
    assert code == 0
    suffixes = sorted(p.suffix for p in state_dir.iterdir())
    assert suffixes == [".json", ".lock"]
    assert not (tmp_path / "state").exists()


def test_manifest_file_option_saves_the_manifest_there(env, served, tmp_path, capsys):
    target = tmp_path / "saved.manifest"
    code, out, err = run(
        capsys, "download", served[2], "--manifest-file", str(target)
    )
    assert code == 0
    assert out.splitlines()[0] == "Manifest saved: %s" % target
    assert target.read_bytes() == served[1].read_bytes()
    assert not (env / "image.iso.chunkget.manifest").exists()


def test_manifest_file_with_a_local_manifest_is_a_usage_error(
    env, served, tmp_path, capsys
):
    code, out, err = run(
        capsys, "download", str(served[1]), "--manifest-file", str(tmp_path / "x")
    )
    assert code == 2
    assert out == ""
    assert "--manifest-file" in err
    assert not (env / "image.iso").exists()
    assert served[0].requests == []


def test_restart_downloads_again(env, served, capsys, stdin):
    stdin("", tty=False)
    assert run(capsys, "download", str(served[1]))[0] == 0
    served[0].requests.clear()
    code, out, err = run(capsys, "download", str(served[1]), "--restart", "-y")
    assert code == 0
    assert len(served[0].requests) == 5
    assert (env / "image.iso").read_bytes() == CONTENT


def test_restart_asks_before_replacing_the_destination(env, served, capsys, stdin):
    assert run(capsys, "download", str(served[1]))[0] == 0
    served[0].requests.clear()
    stdin("n\n")
    code, out, err = run(capsys, "download", str(served[1]), "--restart")
    assert code == 4
    assert served[0].requests == []


def test_without_restart_a_finished_download_is_only_verified(env, served, capsys):
    assert run(capsys, "download", str(served[1]))[0] == 0
    served[0].requests.clear()
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 0
    assert served[0].requests == []
    assert "Global hash verified" in err


def test_help_lists_the_options(capsys):
    code, out, err = run(capsys, "download", "--help")
    for option in ("-o", "--output", "--state-dir", "--manifest-file", "--restart", "-y", "--yes"):
        assert option in out


# --- Final errors and their messages (T74) ---

import collections
import dataclasses

from chunkget import state as state_module

PREFIX = "chunkget: error: "


@pytest.fixture
def fast(monkeypatch):
    """Retry passes do not wait."""
    monkeypatch.setattr("time.sleep", lambda seconds: None)


def last_line(err):
    return err.splitlines()[-1]


def error_lines(err):
    return [line for line in err.splitlines() if line.startswith(PREFIX)]


def test_retries_exhausted_is_code_7_with_the_message_of_the_plan(env, served, capsys, fast):
    served[0].corrupt_range("/image.iso", 50, 60)
    served[0].corrupt_range("/image.iso", 100, 110)  # only the last one is kept
    code, out, err = run(capsys, "download", str(served[1]), "--max-retries", "5")
    assert code == 7
    assert out == ""
    assert error_lines(err) == [
        PREFIX + "Download incomplete: 1 chunk still failed after 5 retry passes. "
        "Run the command again to resume."
    ]


def test_retries_exhausted_with_several_chunks_and_other_retries(env, served, capsys, fast):
    served[0].corrupt_range("/image.iso", 0, 250)
    code, out, err = run(capsys, "download", str(served[1]), "--max-retries", "2")
    assert code == 7
    assert error_lines(err) == [
        PREFIX + "Download incomplete: 5 chunks still failed after 2 retry passes. "
        "Run the command again to resume."
    ]


def test_retries_exhausted_with_one_pass(env, served, capsys, fast):
    served[0].corrupt_range("/image.iso", 0, 250)
    code, out, err = run(capsys, "download", str(served[1]), "--max-retries", "1")
    assert "after 1 retry pass." in last_line(err)


def test_retries_exhausted_keeps_the_correct_chunks_and_can_be_resumed(
    env, served, capsys, fast
):
    served[0].corrupt_range("/image.iso", 50, 60)
    assert run(capsys, "download", str(served[1]), "--max-retries", "0")[0] == 7
    served[0].corruptions.clear()
    served[0].requests.clear()
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 0
    assert [r.range for r in served[0].requests] == ["bytes=50-99"]


def altered_global_hash(tmp_path, served):
    from chunkget import manifest as manifest_module

    loaded = manifest_module.load_manifest_file(served[1])
    bad = dataclasses.replace(loaded, global_hash="sha256:" + "0" * 64)
    path = tmp_path / "bad.manifest"
    path.write_bytes(bad.to_json().encode("utf-8"))
    return path


def test_global_hash_mismatch_is_code_8_with_the_message_of_the_plan(
    env, served, tmp_path, capsys
):
    path = altered_global_hash(tmp_path, served)
    code, out, err = run(capsys, "download", str(path))
    assert code == 8
    assert out == ""
    assert error_lines(err) == [
        PREFIX + "Global validation failed: the file does not match the manifest "
        "hash. Use --restart to download it again."
    ]
    assert (env / "image.iso").read_bytes() == CONTENT  # nothing is deleted


def test_missing_manifest_is_code_3(env, capsys):
    code, out, err = run(capsys, "download", "nope.manifest")
    assert code == 3
    assert "nope.manifest" in last_line(err)


def test_manifest_url_with_404_is_code_3(env, served, capsys):
    code, out, err = run(capsys, "download", served[0].url("/missing.manifest"))
    assert code == 3
    assert "404" in last_line(err)


def test_invalid_manifest_is_code_5_with_a_message(env, capsys):
    (env / "bad.manifest").write_text("{}")
    code, out, err = run(capsys, "download", "bad.manifest")
    assert code == 5
    assert len(error_lines(err)) == 1


def test_fatal_http_error_is_code_6(env, served, capsys, fast):
    served[0].respond_with_statuses("/image.iso", [404])
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 6
    assert "404" in last_line(err)


def test_no_space_is_code_9(env, served, capsys, monkeypatch):
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr("shutil.disk_usage", lambda path: usage(1000, 1000, 0))
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 9
    assert "space" in last_line(err)
    assert not (env / "image.iso").exists()


def test_unwritable_destination_is_code_10(env, served, tmp_path, capsys):
    code, out, err = run(
        capsys, "download", str(served[1]), "-o", str(tmp_path / "no_dir" / "f.iso")
    )
    assert code == 10
    assert len(error_lines(err)) == 1


def test_unwritable_state_dir_is_code_10(env, served, tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a directory")
    code, out, err = run(
        capsys, "download", str(served[1]), "--state-dir", str(blocker / "state")
    )
    assert code == 10
    assert not (env / "image.iso").exists()


def test_incompatible_server_is_code_11(env, served, capsys, fast):
    served[0].ignore_range("/image.iso")
    code, out, err = run(capsys, "download", str(served[1]))
    assert code == 11
    assert len(error_lines(err)) == 1
    assert (env / "image.iso").read_bytes() == bytes(250)


def test_download_already_running_is_code_12(env, served, tmp_path, capsys):
    from chunkget import manifest as manifest_module

    loaded = manifest_module.load_manifest_file(served[1])
    destination = tmp_path / "out.iso"
    state_dir = tmp_path / "state_here"
    state_dir.mkdir()
    key = state_module.state_key(loaded.global_hash, destination)
    with state_module.lock_download(state_dir, key):
        code, out, err = run(
            capsys, "download", str(served[1]), "-o", str(destination),
            "--state-dir", str(state_dir),
        )
    assert code == 12
    assert "already running" in last_line(err)
    assert not destination.exists()


def test_inconsistent_state_is_code_13(env, served, tmp_path, capsys):
    from chunkget import manifest as manifest_module

    loaded = manifest_module.load_manifest_file(served[1])
    destination = tmp_path / "out.iso"
    state_dir = tmp_path / "state_here"
    state_dir.mkdir()
    destination.write_bytes(b"short")
    state_module.save_state(state_module.new_state(loaded, destination), state_dir)
    code, out, err = run(
        capsys, "download", str(served[1]), "-o", str(destination),
        "--state-dir", str(state_dir),
    )
    assert code == 13
    assert "--restart" in last_line(err)
    assert destination.read_bytes() == b"short"


def test_corrupt_state_file_is_code_13(env, served, tmp_path, capsys):
    from chunkget import manifest as manifest_module

    loaded = manifest_module.load_manifest_file(served[1])
    destination = tmp_path / "out.iso"
    state_dir = tmp_path / "state_here"
    state_dir.mkdir()
    assert run(
        capsys, "download", str(served[1]), "-o", str(destination),
        "--state-dir", str(state_dir),
    )[0] == 0
    key = state_module.state_key(loaded.global_hash, destination)
    state_module.state_path(state_dir, key).write_text("not json")
    code, out, err = run(
        capsys, "download", str(served[1]), "-o", str(destination),
        "--state-dir", str(state_dir),
    )
    assert code == 13


def test_every_error_is_one_line_on_stderr_and_nothing_on_stdout(env, served, capsys, fast):
    served[0].corrupt_range("/image.iso", 50, 60)
    code, out, err = run(capsys, "download", str(served[1]), "--max-retries", "0")
    assert out == ""
    assert len(error_lines(err)) == 1


def test_error_after_a_progress_line_on_a_terminal_starts_a_new_line(
    env, served, capsys, monkeypatch, fast
):
    stream = TtyStream()
    monkeypatch.setattr("sys.stderr", stream)
    served[0].corrupt_range("/image.iso", 50, 60)
    code = cli.main(["download", str(served[1]), "--max-retries", "0"])
    assert code == 7
    assert "\n" + PREFIX in stream.getvalue()


def test_retry_messages_are_translatable(env, served, capsys, fast):
    from chunkget import i18n

    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    served[0].corrupt_range("/image.iso", 50, 60)
    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        code, out, err = run(capsys, "download", str(served[1]), "--max-retries", "0")
    finally:
        i18n.set_translation(previous)
    assert code == 7
    assert last_line(err).startswith(PREFIX + "«T»")
