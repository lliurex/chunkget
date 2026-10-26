import hashlib
import io

import pytest

from chunkget import cli, manifest

CONTENT = bytes(index % 251 for index in range(250))
DIGEST = "sha256:" + hashlib.sha256(CONTENT).hexdigest()


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


@pytest.fixture
def served(http_server):
    return http_server.serve("/remote.iso", CONTENT)


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def make(capsys, url, tmp_path, *extra):
    return run(
        capsys, "make-manifest", url, "-o", str(tmp_path / "out.manifest"),
        "--chunk-size", "100", *extra,
    )


def check(tmp_path, url, name):
    loaded = manifest.load_manifest_file(tmp_path / "out.manifest")
    assert loaded.url == url
    assert loaded.name == name
    assert loaded.global_hash == DIGEST
    assert len(loaded.chunks) == 3


# --- Flags: no questions (T70) ---


def test_download_to_downloads_and_generates(served, tmp_path, capsys, stdin):
    stdin("", tty=False)
    target = tmp_path / "copy.iso"
    code, out, err = make(capsys, served, tmp_path, "--download-to", str(target))
    assert code == 0
    assert out == "Manifest written: %s\n" % (tmp_path / "out.manifest")
    assert target.read_bytes() == CONTENT
    check(tmp_path, served, "copy.iso")


def test_download_warns_that_it_cannot_be_validated(served, tmp_path, capsys, stdin):
    stdin("", tty=False)
    code, out, err = make(capsys, served, tmp_path, "--download-to", str(tmp_path / "c"))
    assert code == 0
    assert "warning" in err.lower()
    assert "validate" in err.lower()


def test_local_file_is_used_without_downloading(
    served, http_server, tmp_path, capsys, stdin
):
    stdin("", tty=False)
    local = tmp_path / "mine.iso"
    local.write_bytes(CONTENT)
    code, out, err = make(capsys, served, tmp_path, "--local-file", str(local))
    assert code == 0
    assert err == ""
    assert http_server.requests == []
    check(tmp_path, served, "mine.iso")


def test_default_output_is_named_after_the_local_file(
    served, tmp_path, capsys, stdin, monkeypatch
):
    stdin("", tty=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    target = tmp_path / "copy.iso"
    code, out, err = run(
        capsys, "make-manifest", served, "--download-to", str(target)
    )
    assert code == 0
    assert out == "Manifest written: copy.iso.chunkget.manifest\n"
    assert (work / "copy.iso.chunkget.manifest").exists()


# --- Questions ---


def test_asks_download_then_the_path(served, tmp_path, capsys, stdin):
    target = tmp_path / "copy.iso"
    stdin("d\n%s\n" % target)
    code, out, err = make(capsys, served, tmp_path)
    assert code == 0
    assert target.read_bytes() == CONTENT
    check(tmp_path, served, "copy.iso")
    assert "download" in err.lower() and "local" in err.lower()


@pytest.mark.parametrize("answer", ["d", "D", "download", " Download "])
def test_answers_that_mean_download(served, tmp_path, capsys, stdin, answer):
    target = tmp_path / "copy.iso"
    stdin("%s\n%s\n" % (answer, target))
    assert make(capsys, served, tmp_path)[0] == 0
    assert target.exists()


@pytest.mark.parametrize("answer", ["l", "L", "local", " Local "])
def test_answers_that_mean_local_file(
    served, http_server, tmp_path, capsys, stdin, answer
):
    local = tmp_path / "mine.iso"
    local.write_bytes(CONTENT)
    stdin("%s\n%s\n" % (answer, local))
    assert make(capsys, served, tmp_path)[0] == 0
    assert http_server.requests == []
    check(tmp_path, served, "mine.iso")


def test_invalid_mode_and_empty_path_are_asked_again(served, tmp_path, capsys, stdin):
    target = tmp_path / "copy.iso"
    stdin("x\n\nd\n\n%s\n" % target)
    code, out, err = make(capsys, served, tmp_path)
    assert code == 0
    assert target.exists()


def test_input_ends_while_asking_is_a_usage_error(served, tmp_path, capsys, stdin):
    for text in ("", "d\n"):
        stdin(text)
        code, out, err = make(capsys, served, tmp_path)
        assert code == 2
        assert out == ""
        assert not (tmp_path / "out.manifest").exists()


def test_without_terminal_and_without_flags_is_a_usage_error(
    served, tmp_path, capsys, stdin
):
    stdin("d\n", tty=False)
    code, out, err = make(capsys, served, tmp_path)
    assert code == 2
    assert "--download-to" in err and "--local-file" in err


# --- Usage errors ---


def test_url_option_with_a_url_source_is_a_usage_error(served, tmp_path, capsys, stdin):
    stdin("", tty=False)
    code, out, err = make(
        capsys, served, tmp_path, "--url", served, "--download-to", str(tmp_path / "c")
    )
    assert code == 2
    assert "--url" in err
    assert not (tmp_path / "c").exists()


def test_both_flags_are_refused(served, tmp_path, capsys, stdin):
    stdin("", tty=False)
    code, out, err = make(
        capsys, served, tmp_path, "--download-to", "a", "--local-file", "b"
    )
    assert code == 2
    assert out == ""


@pytest.mark.parametrize("flag", ["--download-to", "--local-file"])
def test_flags_with_a_local_source_are_a_usage_error(tmp_path, capsys, stdin, flag):
    stdin("", tty=False)
    source = tmp_path / "f.iso"
    source.write_bytes(CONTENT)
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", "http://x.example/f",
        flag, str(tmp_path / "other"), "-o", str(tmp_path / "m"),
    )
    assert code == 2
    assert flag in err
    assert not (tmp_path / "m").exists()


# --- Overwriting ---


def test_existing_download_target_is_confirmed(served, tmp_path, capsys, stdin):
    target = tmp_path / "copy.iso"
    target.write_bytes(b"precious")
    stdin("y\n")
    code, out, err = make(capsys, served, tmp_path, "--download-to", str(target))
    assert code == 0
    assert str(target) in err
    assert target.read_bytes() == CONTENT


@pytest.mark.parametrize("answer", ["n", ""])
def test_existing_download_target_declined(
    served, http_server, tmp_path, capsys, stdin, answer
):
    target = tmp_path / "copy.iso"
    target.write_bytes(b"precious")
    stdin(answer + "\n")
    code, out, err = make(capsys, served, tmp_path, "--download-to", str(target))
    assert code == 4
    assert target.read_bytes() == b"precious"
    assert http_server.requests == []


def test_existing_download_target_without_terminal(
    served, http_server, tmp_path, capsys, stdin
):
    target = tmp_path / "copy.iso"
    target.write_bytes(b"precious")
    stdin("y\n", tty=False)
    code, *_ = make(capsys, served, tmp_path, "--download-to", str(target))
    assert code == 4
    assert target.read_bytes() == b"precious"


def test_yes_overwrites_download_target_and_output(served, tmp_path, capsys, stdin):
    stdin("", tty=False)
    target = tmp_path / "copy.iso"
    target.write_bytes(b"precious")
    (tmp_path / "out.manifest").write_bytes(b"previous")
    code, out, err = make(capsys, served, tmp_path, "--download-to", str(target), "-y")
    assert code == 0
    assert "overwrite" not in err.lower()
    assert target.read_bytes() == CONTENT
    check(tmp_path, served, "copy.iso")


def test_existing_output_manifest_is_confirmed_before_downloading(
    served, http_server, tmp_path, capsys, stdin
):
    (tmp_path / "out.manifest").write_bytes(b"previous")
    stdin("n\n")
    target = tmp_path / "copy.iso"
    code, out, err = make(capsys, served, tmp_path, "--download-to", str(target))
    assert code == 4
    assert (tmp_path / "out.manifest").read_bytes() == b"previous"
    assert http_server.requests == []
    assert not target.exists()


def test_existing_output_manifest_accepted(served, tmp_path, capsys, stdin):
    (tmp_path / "out.manifest").write_bytes(b"previous")
    stdin("y\n")
    code, *_ = make(capsys, served, tmp_path, "--download-to", str(tmp_path / "c"))
    assert code == 0
    check(tmp_path, served, "c")


# --- Source errors, other options ---


def test_404_is_code_3_and_leaves_no_manifest(http_server, tmp_path, capsys, stdin):
    stdin("", tty=False)
    code, out, err = make(
        capsys, http_server.url("/missing"), tmp_path, "--download-to", str(tmp_path / "c")
    )
    assert code == 3
    assert out == ""
    assert not (tmp_path / "out.manifest").exists()


def test_algorithm_and_timeout_are_used(served, tmp_path, capsys, stdin):
    stdin("", tty=False)
    local = tmp_path / "mine.iso"
    local.write_bytes(CONTENT)
    code, *_ = make(
        capsys, served, tmp_path, "--local-file", str(local),
        "--algorithm", "sha3_256", "--timeout", "7",
    )
    assert code == 0
    assert manifest.load_manifest_file(tmp_path / "out.manifest").global_hash.startswith(
        "sha3_256:"
    )


def test_texts_are_translatable(served, tmp_path, capsys, stdin):
    from chunkget import i18n

    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    stdin("d\n%s\n" % (tmp_path / "copy.iso"))
    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        code, out, err = make(capsys, served, tmp_path)
    finally:
        i18n.set_translation(previous)
    assert code == 0
    assert out.startswith("«T»Manifest written")
    assert "«T»" in err
