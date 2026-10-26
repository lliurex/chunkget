"""Command line interface: the only module that talks to the terminal."""

import argparse
import sys

import chunkget
from chunkget.errors import ChunkgetError, ExitCode
from chunkget.i18n import _


def build_parser():
    parser = argparse.ArgumentParser(
        prog="chunkget",
        description=_("Chunked, validated and resumable downloads of large files."),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="chunkget " + chunkget.__version__,
        help=_("show the version and exit"),
    )
    commands = parser.add_subparsers(
        dest="command", required=True, metavar="{make-manifest,download}"
    )

    make = commands.add_parser(
        "make-manifest",
        help=_("generate the manifest of a file"),
        description=_("Generate the manifest that describes a file."),
    )
    make.add_argument("source", metavar="SOURCE", help=_("local file or http(s) URL"))
    make.set_defaults(handler=_make_manifest)

    download = commands.add_parser(
        "download",
        help=_("download a file described by a manifest"),
        description=_("Download a file in validated chunks, resuming if needed."),
    )
    download.add_argument(
        "manifest", metavar="MANIFEST", help=_("local path or http(s) URL of a manifest")
    )
    download.set_defaults(handler=_download)
    return parser


def _make_manifest(args):
    return _not_implemented()


def _download(args):
    return _not_implemented()


def _not_implemented():
    _error(_("this command is not implemented yet"))
    return ExitCode.UNEXPECTED


def main(argv=None):
    """Run the command line and return the exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as stop:
        # argparse exits for --help, --version and usage errors (code 2).
        return 0 if stop.code is None else stop.code
    try:
        return int(args.handler(args))
    except ChunkgetError as error:
        # The message of an expected error is already translated.
        _error(str(error))
        return int(error.exit_code)
    except Exception as error:  # noqa: BLE001 - last resort: report, exit 1
        _error(
            _("unexpected error ({kind}): {reason}").format(
                kind=type(error).__name__, reason=error
            )
        )
        return int(ExitCode.UNEXPECTED)


def _error(message):
    print("chunkget: error: " + message, file=sys.stderr)
