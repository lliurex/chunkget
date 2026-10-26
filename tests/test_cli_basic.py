import subprocess
import sys
from pathlib import Path

import pytest

import chunkget
from chunkget import cli, i18n

ROOT = Path(__file__).resolve().parent.parent


def run(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_version(capsys):
    code, out, err = run(capsys, "--version")
    assert code == 0
    assert out == "chunkget %s\n" % chunkget.__version__
    assert err == ""


def test_no_subcommand_is_a_usage_error(capsys):
    code, out, err = run(capsys)
    assert code == 2
    assert out == ""
    assert "usage:" in err


def test_unknown_subcommand_is_a_usage_error(capsys):
    code, out, err = run(capsys, "frobnicate")
    assert code == 2
    assert out == ""
    assert "frobnicate" in err


def test_help_lists_both_subcommands(capsys):
    code, out, err = run(capsys, "-h")
    assert code == 0
    assert "make-manifest" in out
    assert "download" in out
    assert "--version" in out
    assert err == ""


@pytest.mark.parametrize("command", ["make-manifest", "download"])
def test_subcommand_help(capsys, command):
    code, out, err = run(capsys, command, "--help")
    assert code == 0
    assert command in out
    assert err == ""


@pytest.mark.parametrize("command", ["make-manifest", "download"])
def test_subcommand_needs_its_positional_argument(capsys, command):
    code, out, err = run(capsys, command)
    assert code == 2
    assert out == ""
    assert "usage:" in err


def test_subcommands_accept_their_positional_argument():
    parser = cli.build_parser()
    assert parser.parse_args(["make-manifest", "file.iso"]).source == "file.iso"
    assert parser.parse_args(["download", "m.manifest"]).manifest == "m.manifest"


def test_main_reads_sys_argv_by_default(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["chunkget", "--version"])
    assert cli.main() == 0
    assert capsys.readouterr().out == "chunkget %s\n" % chunkget.__version__


def test_help_goes_through_gettext(capsys):
    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        code, out, err = run(capsys, "-h")
    finally:
        i18n.set_translation(previous)
    assert code == 0
    assert "«T»" in out


def test_module_can_be_run():
    result = subprocess.run(
        [sys.executable, "-m", "chunkget", "--version"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout == "chunkget %s\n" % chunkget.__version__


def test_module_without_arguments_exits_with_2():
    result = subprocess.run(
        [sys.executable, "-m", "chunkget"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
