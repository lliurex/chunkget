import hashlib
import io

import pytest

from chunkget import cli, manifest, manifest_builder

URL = "http://127.0.0.1:8000/image.iso"
CONTENT = bytes(index % 251 for index in range(250))


class FakeStdin(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "image.iso"
    path.write_bytes(CONTENT)
    return path


@pytest.fixture
def stdin(monkeypatch):
    def set_stdin(text="", tty=True):
        monkeypatch.setattr("sys.stdin", FakeStdin(text, tty))

    return set_stdin


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- With --url: no questions (T68) ---


def test_with_url_it_generates_without_asking(source, tmp_path, capsys, stdin):
    stdin("", tty=False)
    output = tmp_path / "out.manifest"
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output),
        "--chunk-size", "100",
    )
    assert code == 0
    assert out == "Manifest written: %s\n" % output
    assert err == ""
    loaded = manifest.load_manifest_file(output)
    assert loaded.url == URL
    assert loaded.name == "image.iso"
    assert loaded.global_hash == "sha256:" + hashlib.sha256(CONTENT).hexdigest()
    assert len(loaded.chunks) == 3


def test_default_output_path(source, tmp_path, capsys, stdin, monkeypatch):
    stdin("", tty=False)
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    code, out, err = run(capsys, "make-manifest", str(source), "--url", URL)
    assert code == 0
    assert out == "Manifest written: image.iso.chunkget.manifest\n"
    assert (work / "image.iso.chunkget.manifest").exists()


def test_options_reach_the_manifest(source, tmp_path, capsys, stdin):
    stdin("", tty=False)
    output = tmp_path / "m"
    code, *_ = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output),
        "--chunk-size", "50", "--algorithm", "sha3_256",
    )
    assert code == 0
    loaded = manifest.load_manifest_file(output)
    assert loaded.chunk_size == 50 and len(loaded.chunks) == 5
    assert loaded.global_hash.startswith("sha3_256:")


# --- Without --url: the URL is the last question ---


def test_url_is_asked_on_stderr_and_used(source, tmp_path, capsys, stdin):
    stdin(URL + "\n")
    output = tmp_path / "m"
    code, out, err = run(
        capsys, "make-manifest", str(source), "-o", str(output), "--chunk-size", "100"
    )
    assert code == 0
    assert out == "Manifest written: %s\n" % output
    assert "URL" in err
    assert manifest.load_manifest_file(output).url == URL


def test_url_is_asked_after_the_file_has_been_read(source, tmp_path, capsys, stdin, monkeypatch):
    order = []
    real_ask = cli._ask

    def ask(prompt):
        order.append("ask")
        return real_ask(prompt)

    monkeypatch.setattr(cli, "_ask", ask)
    real_compute = manifest_builder.compute_chunks

    def compute(*args, **kwargs):
        result = real_compute(*args, **kwargs)
        order.append("computed")
        return result

    monkeypatch.setattr(manifest_builder, "compute_chunks", compute)
    stdin(URL + "\n")
    run(capsys, "make-manifest", str(source), "-o", str(tmp_path / "m"))
    assert order == ["computed", "ask"]


def test_invalid_url_is_asked_again(source, tmp_path, capsys, stdin):
    stdin("\nnot a url\nftp://example.com/x\n" + URL + "\n")
    output = tmp_path / "m"
    code, out, err = run(capsys, "make-manifest", str(source), "-o", str(output))
    assert code == 0
    assert manifest.load_manifest_file(output).url == URL
    assert err.count("invalid URL") == 3
    assert out == "Manifest written: %s\n" % output


def test_url_with_spaces_around_is_accepted(source, tmp_path, capsys, stdin):
    stdin("   " + URL + "  \n")
    output = tmp_path / "m"
    assert run(capsys, "make-manifest", str(source), "-o", str(output))[0] == 0
    assert manifest.load_manifest_file(output).url == URL


def test_input_ends_before_a_valid_url_is_a_usage_error(source, tmp_path, capsys, stdin):
    stdin("bad\n")
    output = tmp_path / "m"
    code, out, err = run(capsys, "make-manifest", str(source), "-o", str(output))
    assert code == 2
    assert out == ""
    assert not output.exists()


def test_without_terminal_and_without_url_it_is_a_usage_error(
    source, tmp_path, capsys, stdin
):
    stdin(URL + "\n", tty=False)
    output = tmp_path / "m"
    code, out, err = run(capsys, "make-manifest", str(source), "-o", str(output))
    assert code == 2
    assert out == ""
    assert "--url" in err
    assert not output.exists()


def test_without_terminal_it_fails_before_reading_the_file(
    source, tmp_path, capsys, stdin, monkeypatch
):
    def never(*args, **kwargs):
        raise AssertionError("the file must not be read")

    monkeypatch.setattr(manifest_builder, "compute_chunks", never)
    stdin("", tty=False)
    assert run(capsys, "make-manifest", str(source))[0] == 2


@pytest.mark.parametrize("url", ["", "nope", "ftp://example.com/x", "http:///x"])
def test_invalid_url_option_is_a_usage_error(source, tmp_path, capsys, stdin, url):
    stdin("", tty=True)
    output = tmp_path / "m"
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", url, "-o", str(output)
    )
    assert code == 2
    assert not output.exists()
    assert err.startswith("chunkget: error: ")


# --- Errors that already have their code ---


def test_missing_source_is_code_3(tmp_path, capsys, stdin):
    stdin("", tty=False)
    code, out, err = run(
        capsys, "make-manifest", str(tmp_path / "nope"), "--url", URL,
        "-o", str(tmp_path / "m"),
    )
    assert code == 3
    assert out == ""
    assert not (tmp_path / "m").exists()


def test_existing_output_without_terminal_is_refused(source, tmp_path, capsys, stdin):
    stdin("", tty=False)
    output = tmp_path / "m"
    output.write_bytes(b"previous")
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )
    assert code == 4
    assert output.read_bytes() == b"previous"


def test_message_text_is_translatable(source, tmp_path, capsys, stdin):
    from chunkget import i18n

    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    stdin(URL + "\n")
    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        code, out, err = run(capsys, "make-manifest", str(source), "-o", str(tmp_path / "m"))
    finally:
        i18n.set_translation(previous)
    assert code == 0
    assert out.startswith("«T»Manifest written")
    assert err.startswith("«T»")


# --- Overwriting the output manifest (T69) ---


def existing_output(tmp_path):
    output = tmp_path / "m"
    output.write_bytes(b"previous")
    return output


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", "  yes  "])
def test_affirmative_answer_replaces_the_file(source, tmp_path, capsys, stdin, answer):
    output = existing_output(tmp_path)
    stdin(answer + "\n")
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )
    assert code == 0
    assert out == "Manifest written: %s\n" % output
    assert str(output) in err and "overwrite" in err.lower()
    assert manifest.load_manifest_file(output).url == URL


@pytest.mark.parametrize("answer", ["n", "no", "", "maybe", "yess"])
def test_any_other_answer_declines(source, tmp_path, capsys, stdin, answer):
    output = existing_output(tmp_path)
    stdin(answer + "\n")
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )
    assert code == 4
    assert out == ""
    assert "overwrite" in err.lower()
    assert output.read_bytes() == b"previous"


def test_input_ended_declines(source, tmp_path, capsys, stdin):
    output = existing_output(tmp_path)
    stdin("")
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )
    assert code == 4
    assert output.read_bytes() == b"previous"


@pytest.mark.parametrize("flag", ["-y", "--yes"])
def test_yes_replaces_without_asking(source, tmp_path, capsys, stdin, flag):
    output = existing_output(tmp_path)
    stdin("", tty=False)
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output), flag
    )
    assert code == 0
    assert err == ""
    assert manifest.load_manifest_file(output).url == URL


def test_without_terminal_the_question_is_declined(source, tmp_path, capsys, stdin):
    output = existing_output(tmp_path)
    stdin("y\n", tty=False)
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )
    assert code == 4
    assert output.read_bytes() == b"previous"


def test_declining_does_not_read_the_file(source, tmp_path, capsys, stdin, monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("the file must not be read")

    monkeypatch.setattr(manifest_builder, "compute_chunks", never)
    output = existing_output(tmp_path)
    stdin("n\n")
    assert run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )[0] == 4


def test_overwrite_is_asked_before_the_url(source, tmp_path, capsys, stdin):
    output = existing_output(tmp_path)
    stdin("y\n" + URL + "\n")
    code, out, err = run(capsys, "make-manifest", str(source), "-o", str(output))
    assert code == 0
    assert err.lower().index("overwrite") < err.index("URL")
    assert manifest.load_manifest_file(output).url == URL


def test_no_question_when_the_output_does_not_exist(source, tmp_path, capsys, stdin):
    stdin("", tty=False)
    output = tmp_path / "new"
    code, out, err = run(
        capsys, "make-manifest", str(source), "--url", URL, "-o", str(output)
    )
    assert code == 0
    assert err == ""


def test_default_output_is_checked_too(source, tmp_path, capsys, stdin, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    default = work / "image.iso.chunkget.manifest"
    default.write_bytes(b"previous")
    stdin("n\n")
    code, *_ = run(capsys, "make-manifest", str(source), "--url", URL)
    assert code == 4
    assert default.read_bytes() == b"previous"
    stdin("y\n")
    assert run(capsys, "make-manifest", str(source), "--url", URL)[0] == 0
    assert default.read_bytes() != b"previous"


def test_yes_help_is_listed(capsys):
    code, out, err = run(capsys, "make-manifest", "--help")
    assert "-y" in out and "--yes" in out
