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
