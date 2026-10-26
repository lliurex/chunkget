"""Every message of the command line goes through gettext (RNF2, constitution §6).

A translation that puts «T» before each translated string is installed. Any
line of stdout or stderr that does not start with «T» (or, for errors, have
it right after the ``chunkget: error: `` prefix) did not pass through gettext.
"""

import collections
import io
import signal

import pytest

from chunkget import cli, i18n, manifest_builder
from chunkget import manifest as manifest_module
from chunkget import state as state_module

MARK = "«T»"
ERROR_PREFIX = "chunkget: error: "
CONTENT = bytes(index % 251 for index in range(250))
URL = "http://127.0.0.1:8000/image.iso"


class Mark:
    def gettext(self, text):
        return MARK + text

    def ngettext(self, one, many, n):
        return MARK + (one if n == 1 else many)


@pytest.fixture(autouse=True)
def marked_translation():
    previous = i18n.get_translation()
    i18n.set_translation(Mark())
    yield
    i18n.set_translation(previous)


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.fixture
def ctx(tmp_path, http_server, monkeypatch, capsys):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("COLUMNS", "1000")  # no wrapped help lines
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    source = tmp_path / "image.iso"
    source.write_bytes(CONTENT)
    url = http_server.serve("/image.iso", CONTENT)
    built = manifest_builder.build_manifest(source, url, chunk_size=50)
    text = built.to_json().encode("utf-8")
    manifest = tmp_path / "m.chunkget.manifest"
    manifest.write_bytes(text)

    class Context:
        pass

    c = Context()
    c.tmp, c.work, c.server, c.url = tmp_path, work, http_server, url
    c.source, c.manifest, c.built = source, manifest, built
    c.manifest_url = http_server.serve("/m.manifest", text)

    def go(*argv, stdin="", tty=True):
        monkeypatch.setattr("sys.stdin", FakeStdin(stdin, tty))
        code = cli.main(list(argv))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    c.go = go
    c.monkeypatch = monkeypatch
    return c


def untranslated(out, err):
    """Lines of the output that did not go through gettext."""
    bad = []
    for stream, text in (("stdout", out), ("stderr", err)):
        for line in text.splitlines():
            if not line:
                continue
            body = line[len(ERROR_PREFIX):] if line.startswith(ERROR_PREFIX) else line
            if not body.startswith(MARK):
                bad.append("%s: %r" % (stream, line))
    return bad


def assert_translated(result, code):
    got, out, err = result
    assert got == code, err
    assert untranslated(out, err) == []
    return out, err


# --- Shared options and usage errors raised by chunkget itself ---


def test_unsupported_algorithm(ctx):
    assert_translated(ctx.go("make-manifest", str(ctx.source), "--algorithm", "md5"), 2)


def test_chunk_size_errors(ctx):
    assert_translated(ctx.go("make-manifest", str(ctx.source), "--chunk-size", "0"), 2)
    assert_translated(ctx.go("make-manifest", str(ctx.source), "--chunk-size=x"), 2)


def test_retries_and_timeout_errors(ctx):
    assert_translated(ctx.go("download", "m", "--max-retries", "101"), 2)
    assert_translated(ctx.go("download", "m", "--timeout=abc"), 2)


# --- make-manifest, local source ---


def test_make_manifest_with_url(ctx):
    out, err = assert_translated(
        ctx.go("make-manifest", str(ctx.source), "--url", URL, "-o", "m"), 0
    )
    assert out.startswith(MARK + "Manifest written")


def test_make_manifest_asks_for_the_url_and_repeats_when_invalid(ctx):
    out, err = assert_translated(
        ctx.go("make-manifest", str(ctx.source), "-o", "m", stdin="bad\n" + URL + "\n"), 0
    )
    assert "invalid URL" in err


def test_make_manifest_without_url_or_terminal(ctx):
    assert_translated(ctx.go("make-manifest", str(ctx.source), stdin="", tty=False), 2)


def test_make_manifest_input_ended(ctx):
    assert_translated(ctx.go("make-manifest", str(ctx.source), "-o", "m", stdin=""), 2)


def test_make_manifest_invalid_url_option(ctx):
    assert_translated(
        ctx.go("make-manifest", str(ctx.source), "--url", "nope", "-o", "m"), 2
    )


def test_make_manifest_overwrite_questions(ctx):
    (ctx.work / "m").write_text("previous")
    assert_translated(
        ctx.go("make-manifest", str(ctx.source), "--url", URL, "-o", "m", stdin="n\n"), 4
    )
    assert_translated(
        ctx.go("make-manifest", str(ctx.source), "--url", URL, "-o", "m", stdin="y\n"), 0
    )
    assert_translated(
        ctx.go("make-manifest", str(ctx.source), "--url", URL, "-o", "m", stdin="", tty=False),
        4,
    )


def test_make_manifest_source_errors(ctx):
    assert_translated(
        ctx.go("make-manifest", "missing.iso", "--url", URL, "-o", "m"), 3
    )
    assert_translated(ctx.go("make-manifest", str(ctx.work), "--url", URL, "-o", "m"), 3)


# --- make-manifest, URL source ---


def test_make_manifest_url_source_download(ctx):
    out, err = assert_translated(
        ctx.go("make-manifest", ctx.url, "-o", "m", stdin="d\ncopy.iso\n"), 0
    )
    assert "warning" in err


def test_make_manifest_url_source_local_file(ctx):
    assert_translated(
        ctx.go("make-manifest", ctx.url, "-o", "m", stdin="x\nl\n%s\n" % ctx.source), 0
    )


def test_make_manifest_url_source_flags(ctx):
    assert_translated(
        ctx.go("make-manifest", ctx.url, "-o", "m", "--download-to", "copy.iso"), 0
    )
    assert_translated(
        ctx.go("make-manifest", ctx.url, "-o", "m", "--local-file", str(ctx.source), "-y"), 0
    )


def test_make_manifest_url_source_usage_errors(ctx):
    assert_translated(ctx.go("make-manifest", ctx.url, "--url", URL), 2)
    assert_translated(ctx.go("make-manifest", ctx.url, stdin="", tty=False), 2)
    assert_translated(ctx.go("make-manifest", ctx.url, stdin="d\n"), 2)
    assert_translated(
        ctx.go("make-manifest", str(ctx.source), "--url", URL, "--local-file", "x"), 2
    )


def test_make_manifest_url_source_questions_and_errors(ctx):
    (ctx.work / "copy.iso").write_text("precious")
    assert_translated(
        ctx.go("make-manifest", ctx.url, "-o", "m", "--download-to", "copy.iso", stdin="n\n"),
        4,
    )
    assert_translated(
        ctx.go("make-manifest", ctx.server.url("/missing"), "-o", "m2",
               "--download-to", "other.iso"),
        3,
    )


# --- download ---


def test_download_success_and_progress(ctx):
    out, err = assert_translated(ctx.go("download", str(ctx.manifest)), 0)
    assert out.startswith(MARK + "Download completed")
    assert MARK + "Downloading" in err
    assert MARK + "Global hash verified" in err


def test_download_from_a_manifest_url(ctx):
    out, err = assert_translated(ctx.go("download", ctx.manifest_url), 0)
    assert MARK + "Manifest saved" in out


def test_download_questions(ctx):
    (ctx.work / "image.iso").write_bytes(b"precious")
    assert_translated(ctx.go("download", str(ctx.manifest), stdin="n\n"), 4)
    assert_translated(ctx.go("download", str(ctx.manifest), stdin="y\n"), 0)
    (ctx.work / "image.iso.chunkget.manifest").write_text("different")
    assert_translated(ctx.go("download", ctx.manifest_url, stdin="n\n"), 4)
    assert_translated(ctx.go("download", ctx.manifest_url, stdin="", tty=False), 4)


def test_download_retry_messages(ctx):
    ctx.server.cut_connection_after("/image.iso", 10, times=1)
    out, err = assert_translated(ctx.go("download", str(ctx.manifest)), 0)
    assert MARK + "Retry pass" in err


def test_download_stale_state_warning(ctx):
    assert_translated(ctx.go("download", str(ctx.manifest)), 0)
    (ctx.work / "image.iso").unlink()
    out, err = assert_translated(ctx.go("download", str(ctx.manifest)), 0)
    assert "warning" in err


def test_download_manifest_file_with_a_local_manifest(ctx):
    assert_translated(ctx.go("download", str(ctx.manifest), "--manifest-file", "x"), 2)


def test_download_error_codes(ctx):
    # 3: no manifest, 5: invalid manifest
    assert_translated(ctx.go("download", "nope.manifest"), 3)
    (ctx.work / "bad.manifest").write_text("{}")
    assert_translated(ctx.go("download", "bad.manifest"), 5)
    # 7: retries exhausted
    ctx.server.corrupt_range("/image.iso", 50, 60)
    assert_translated(ctx.go("download", str(ctx.manifest), "-o", "a.iso"), 7)
    assert_translated(
        ctx.go("download", str(ctx.manifest), "-o", "a.iso", "--max-retries", "1"), 7
    )
    ctx.server.corruptions.clear()
    # 6: fatal network error
    ctx.server.respond_with_statuses("/image.iso", [404])
    assert_translated(ctx.go("download", str(ctx.manifest), "-o", "b.iso"), 6)
    # 11: incompatible server
    ctx.server.ignore_range("/image.iso")
    assert_translated(ctx.go("download", str(ctx.manifest), "-o", "c.iso"), 11)


def test_download_global_hash_failure(ctx):
    import dataclasses

    bad = dataclasses.replace(ctx.built, global_hash="sha256:" + "0" * 64)
    (ctx.work / "bad.manifest").write_bytes(bad.to_json().encode("utf-8"))
    assert_translated(ctx.go("download", "bad.manifest"), 8)


def test_download_no_space_and_filesystem_errors(ctx):
    usage = collections.namedtuple("usage", "total used free")
    with ctx.monkeypatch.context() as patch:
        patch.setattr("shutil.disk_usage", lambda path: usage(1, 1, 0))
        assert_translated(ctx.go("download", str(ctx.manifest)), 9)
    assert_translated(
        ctx.go("download", str(ctx.manifest), "-o", str(ctx.tmp / "no_dir" / "f")), 10
    )


def test_download_lock_and_state_errors(ctx):
    destination = ctx.work / "out.iso"
    state_dir = ctx.tmp / "state_here"
    state_dir.mkdir()
    key = state_module.state_key(ctx.built.global_hash, destination)
    with state_module.lock_download(state_dir, key):
        assert_translated(
            ctx.go("download", str(ctx.manifest), "-o", str(destination),
                   "--state-dir", str(state_dir)),
            12,
        )
    destination.write_bytes(b"short")
    state_module.save_state(state_module.new_state(ctx.built, destination), state_dir)
    assert_translated(
        ctx.go("download", str(ctx.manifest), "-o", str(destination),
               "--state-dir", str(state_dir)),
        13,
    )


def test_unexpected_error_and_not_a_chunkget_error(ctx):
    def boom(args):
        raise RuntimeError("boom")

    ctx.monkeypatch.setattr(cli, "_download", boom)
    assert_translated(ctx.go("download", str(ctx.manifest)), 1)


# --- Signals ---


@pytest.mark.parametrize("signum, code", [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_interruption_messages(ctx, signum, code):
    import os

    ctx.server.on_request(
        "/image.iso", lambda n: os.kill(os.getpid(), signum) if n == 2 else None
    )
    ctx.server.delay("/image.iso", 0.3)
    assert_translated(ctx.go("download", str(ctx.manifest)), code)


# --- Help ---


HEADINGS = {
    "positional arguments:",
    "options:",
    "optional arguments:",
    "{make-manifest,download}",  # the names of the commands, not a text
}


def help_problems(out):
    """Lines of a help text with a chunkget string that is not translated."""
    problems = []
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line == "")
    for line in lines[start:]:
        if not line.strip() or line.strip() in HEADINGS:
            continue
        if line.lstrip().startswith("-h, --help"):
            continue  # argparse's own text, translated by its own domain
        if MARK not in line:
            problems.append(line)
    return problems


@pytest.mark.parametrize("argv", [["-h"], ["make-manifest", "-h"], ["download", "-h"]])
def test_help_texts(ctx, argv):
    code, out, err = ctx.go(*argv)
    assert code == 0
    assert help_problems(out) == []


def test_version_has_no_text_to_translate(ctx):
    code, out, err = ctx.go("--version")
    assert (code, err) == (0, "")
    assert out.startswith("chunkget ")


def test_the_check_itself_detects_an_untranslated_line():
    assert untranslated(MARK + "ok\n", MARK + "ok\n" + ERROR_PREFIX + MARK + "ok\n") == []
    found = untranslated("plain\n", ERROR_PREFIX + "plain error\n")
    assert len(found) == 2
