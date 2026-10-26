import inspect

import pytest

from chunkget import cli, errors, i18n
from chunkget.errors import ExitCode

# Every exception class of the package that carries its own exit code.
ERROR_CLASSES = sorted(
    (
        cls
        for _name, cls in inspect.getmembers(errors, inspect.isclass)
        if issubclass(cls, errors.ChunkgetError) and cls is not errors.ChunkgetError
    ),
    key=lambda cls: cls.__name__,
)

COMMANDS = [
    ("download", ["download", "m.manifest"], "_download"),
    ("make-manifest", ["make-manifest", "file.iso"], "_make_manifest"),
]


def failing(error):
    def handler(args):
        raise error

    return handler


@pytest.fixture(params=COMMANDS, ids=[c[0] for c in COMMANDS])
def command(request, monkeypatch):
    _name, argv, handler_name = request.param

    def fail_with(error):
        monkeypatch.setattr(cli, handler_name, failing(error))
        return argv

    return fail_with


def test_there_is_a_class_per_exit_code():
    assert len(ERROR_CLASSES) >= 14


@pytest.mark.parametrize("cls", ERROR_CLASSES, ids=lambda cls: cls.__name__)
def test_each_error_gives_its_code_and_message(cls, command, capsys):
    argv = command(cls("something went wrong"))
    code = cli.main(argv)
    captured = capsys.readouterr()
    assert code == cls.exit_code
    assert captured.out == ""
    assert captured.err == "chunkget: error: something went wrong\n"


def test_unexpected_exception_returns_1(command, capsys):
    argv = command(RuntimeError("boom"))
    code = cli.main(argv)
    captured = capsys.readouterr()
    assert code == ExitCode.UNEXPECTED == 1
    assert captured.out == ""
    assert captured.err.startswith("chunkget: error: ")
    assert captured.err.count("\n") == 1
    assert "boom" in captured.err


def test_the_base_error_is_unexpected(command, capsys):
    argv = command(errors.ChunkgetError("plain"))
    assert cli.main(argv) == 1
    assert capsys.readouterr().err == "chunkget: error: plain\n"


def test_message_is_printed_as_received_not_translated_twice(command, capsys):
    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        argv = command(errors.SourceError(i18n._("cannot read {path}").format(path="x")))
        cli.main(argv)
    finally:
        i18n.set_translation(previous)
    assert capsys.readouterr().err == "chunkget: error: «T»cannot read x\n"


def test_unexpected_error_text_is_translatable(command, capsys):
    class Prefix:
        def gettext(self, text):
            return "«T»" + text

        def ngettext(self, one, many, n):
            return "«T»" + (one if n == 1 else many)

    previous = i18n.get_translation()
    i18n.set_translation(Prefix())
    try:
        argv = command(RuntimeError("boom"))
        cli.main(argv)
    finally:
        i18n.set_translation(previous)
    assert "«T»" in capsys.readouterr().err


def test_success_returns_0_and_prints_no_error(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_download", lambda args: ExitCode.OK)
    assert cli.main(["download", "m.manifest"]) == 0
    assert capsys.readouterr().err == ""


def test_error_message_may_be_empty(command, capsys):
    argv = command(errors.NetworkError(""))
    assert cli.main(argv) == ExitCode.NETWORK_ERROR
    assert capsys.readouterr().err == "chunkget: error: \n"
