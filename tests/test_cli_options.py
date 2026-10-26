import pytest

from chunkget import cli, config
from chunkget.errors import ExitCode

MAKE = ["make-manifest", "file.iso"]
DOWNLOAD = ["download", "m.manifest"]


@pytest.fixture
def seen(monkeypatch):
    """Replace both handlers; the list receives the parsed arguments."""
    received = []

    def handler(args):
        received.append(args)
        return ExitCode.OK

    monkeypatch.setattr(cli, "_make_manifest", handler)
    monkeypatch.setattr(cli, "_download", handler)
    return received


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# --- Defaults ---


def test_make_manifest_defaults(seen, capsys):
    assert run(capsys, *MAKE)[0] == 0
    args = seen[0]
    assert args.chunk_size == config.DEFAULT_CHUNK_SIZE == 100 * 1024 * 1024
    assert args.algorithm == "sha256"
    assert args.max_retries == 5
    assert args.timeout == 30


def test_download_defaults(seen, capsys):
    assert run(capsys, *DOWNLOAD)[0] == 0
    assert seen[0].max_retries == 5
    assert seen[0].timeout == 30
    assert not hasattr(seen[0], "chunk_size")


# --- Valid values ---


@pytest.mark.parametrize(
    "text, expected",
    [("1", 1), ("4096", 4096), ("4K", 4096), ("100M", 100 * 1024**2), ("1G", 1024**3)],
)
def test_chunk_size_values(seen, capsys, text, expected):
    assert run(capsys, *MAKE, "--chunk-size", text)[0] == 0
    assert seen[0].chunk_size == expected


@pytest.mark.parametrize("name", ["sha256", "sha384", "sha512", "sha3_256", "sha3_512"])
def test_algorithms(seen, capsys, name):
    assert run(capsys, *MAKE, "--algorithm", name)[0] == 0
    assert seen[0].algorithm == name


@pytest.mark.parametrize("command", [MAKE, DOWNLOAD])
def test_retries_and_timeout_values(seen, capsys, command):
    assert run(capsys, *command, "--max-retries", "0", "--timeout", "3600")[0] == 0
    assert (seen[0].max_retries, seen[0].timeout) == (0, 3600)
    assert run(capsys, *command, "--max-retries", "100", "--timeout", "1")[0] == 0
    assert (seen[1].max_retries, seen[1].timeout) == (100, 1)


# --- Invalid values: code 2 and what is valid ---


def test_unsupported_algorithm_lists_the_valid_ones(seen, capsys):
    code, out, err = run(capsys, *MAKE, "--algorithm", "md5")
    assert code == ExitCode.USAGE == 2
    assert out == ""
    assert err.startswith("chunkget: error: ")
    assert "md5" in err
    for name in ("sha256", "sha384", "sha512", "sha3_256", "sha3_512"):
        assert name in err
    assert seen == []


@pytest.mark.parametrize("text", ["0", "1025M", "2G"])
def test_chunk_size_out_of_range_gives_the_range(seen, capsys, text):
    code, out, err = run(capsys, *MAKE, "--chunk-size", text)
    assert code == 2
    assert "between 1 and 1073741824" in err
    assert seen == []


@pytest.mark.parametrize("text", ["", "abc", "1.5M", "10T", "-5", "5 M"])
def test_chunk_size_bad_format_gives_the_format(seen, capsys, text):
    code, out, err = run(capsys, *MAKE, "--chunk-size=" + text)
    assert code == 2
    assert "K, M or G" in err
    assert seen == []


@pytest.mark.parametrize("command", [MAKE, DOWNLOAD])
@pytest.mark.parametrize("text", ["101", "-1"])
def test_max_retries_out_of_range(seen, capsys, command, text):
    code, out, err = run(capsys, *command, "--max-retries=" + text)
    assert code == 2
    assert "between 0 and 100" in err
    assert seen == []


@pytest.mark.parametrize("command", [MAKE, DOWNLOAD])
@pytest.mark.parametrize("text", ["0", "3601", "-1"])
def test_timeout_out_of_range(seen, capsys, command, text):
    code, out, err = run(capsys, *command, "--timeout=" + text)
    assert code == 2
    assert "between 1 and 3600" in err
    assert seen == []


@pytest.mark.parametrize("option", ["--max-retries", "--timeout"])
@pytest.mark.parametrize("text", ["abc", "1.5", ""])
def test_numbers_that_are_not_integers(seen, capsys, option, text):
    code, out, err = run(capsys, *DOWNLOAD, option + "=" + text)
    assert code == 2
    assert "integer" in err
    assert seen == []


def test_options_not_belonging_to_the_command_are_usage_errors(seen, capsys):
    assert run(capsys, *DOWNLOAD, "--chunk-size", "1M")[0] == 2
    assert run(capsys, *DOWNLOAD, "--algorithm", "sha256")[0] == 2
    assert seen == []


def test_help_shows_the_defaults(capsys):
    code, out, err = run(capsys, "make-manifest", "--help")
    assert code == 0
    for text in ("--chunk-size", "--algorithm", "--max-retries", "--timeout", "100M", "sha256"):
        assert text in out
