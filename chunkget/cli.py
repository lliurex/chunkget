"""Command line interface: the only module that talks to the terminal."""

import argparse
import os
import sys

import chunkget
from chunkget import config, downloader, hashing, http, publisher
from chunkget.errors import (
    ChunkgetError,
    ExitCode,
    SourceError,
    UsageError,
    UserDeclinedError,
)
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
    make.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        help=_("manifest to write (default: ./<name>.chunkget.manifest)"),
    )
    make.add_argument(
        "--url",
        metavar="URL",
        help=_("URL the file will be downloaded from (asked for if missing)"),
    )
    make.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=_("answer yes when asked whether to overwrite the manifest"),
    )
    make.add_argument(
        "--chunk-size",
        metavar="SIZE",
        help=_("chunk size, with an optional suffix K, M or G (default: 100M)"),
    )
    make.add_argument(
        "--algorithm",
        metavar="NAME",
        help=_("hash algorithm: {algorithms} (default: {default})").format(
            algorithms=", ".join(hashing.SUPPORTED_ALGORITHMS),
            default=config.DEFAULT_ALGORITHM,
        ),
    )
    _add_network_options(make)
    make.set_defaults(handler=_make_manifest)

    download = commands.add_parser(
        "download",
        help=_("download a file described by a manifest"),
        description=_("Download a file in validated chunks, resuming if needed."),
    )
    download.add_argument(
        "manifest", metavar="MANIFEST", help=_("local path or http(s) URL of a manifest")
    )
    _add_network_options(download)
    download.set_defaults(handler=_download)
    return parser


def _add_network_options(parser):
    parser.add_argument(
        "--max-retries",
        metavar="N",
        help=_("retry passes for failed chunks, 0 to 100 (default: {default})").format(
            default=config.DEFAULT_MAX_RETRIES
        ),
    )
    parser.add_argument(
        "--timeout",
        metavar="SECONDS",
        help=_("network timeout in seconds, 1 to 3600 (default: {default})").format(
            default=config.DEFAULT_TIMEOUT
        ),
    )


def _parse_int(name, text):
    try:
        return int(text)
    except ValueError:
        raise UsageError(
            _("invalid {name} {value!r}: expected an integer").format(
                name=name, value=text
            )
        ) from None


def resolve_options(args):
    """Replace the shared options by validated values, or their defaults (RF1.2).

    Raises ``UsageError`` (code 2) for a value that is not supported (RF1.3).
    """
    if hasattr(args, "chunk_size"):
        if args.chunk_size is None:
            args.chunk_size = config.DEFAULT_CHUNK_SIZE
        else:
            args.chunk_size = config.validate_chunk_size(
                config.parse_size(args.chunk_size)
            )
    if hasattr(args, "algorithm"):
        if args.algorithm is None:
            args.algorithm = config.DEFAULT_ALGORITHM
        else:
            hashing.validate_algorithm(args.algorithm)
    if args.max_retries is None:
        args.max_retries = config.DEFAULT_MAX_RETRIES
    else:
        args.max_retries = config.validate_max_retries(
            _parse_int("max retries", args.max_retries)
        )
    if args.timeout is None:
        args.timeout = config.DEFAULT_TIMEOUT
    else:
        args.timeout = config.validate_timeout(_parse_int("timeout", args.timeout))


def _make_manifest(args):
    if downloader.is_url(args.source):
        return _not_implemented()
    url = args.url
    if url is None:
        if not _is_interactive():
            raise UsageError(
                _("the download URL is needed: use --url (there is no terminal to ask)")
            )
        # Not called here: build_manifest calls it after reading the file, so
        # the URL is the last thing asked (RF2).
        url = _ask_url
    else:
        url = _checked_url(url)
    output = args.output or config.default_manifest_path(os.path.basename(args.source))
    overwrite = os.path.lexists(output)
    if overwrite and not args.yes:
        _confirm_overwrite(output)
    written = publisher.make_manifest(
        args.source,
        url,
        output,
        chunk_size=args.chunk_size,
        algorithm=args.algorithm,
        overwrite=overwrite,
    )
    print(_("Manifest written: {path}").format(path=written))
    return ExitCode.OK


def _confirm_overwrite(path):
    """Ask before replacing ``path`` (RF5); declining is ``UserDeclinedError``.

    No terminal, no answer or anything but yes counts as a refusal.
    """
    if _is_interactive():
        answer = _ask(_("{path} already exists. Overwrite it? [y/N] ").format(path=path))
        yes = {"y", "yes", _("y").lower(), _("yes").lower()}
        if answer is not None and answer.lower() in yes:
            return
    raise UserDeclinedError(_("not overwriting {path}").format(path=path))


def _is_interactive():
    return sys.stdin is not None and sys.stdin.isatty()


def _ask(prompt):
    """Ask on stderr and read the answer; None if the input has ended."""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    line = sys.stdin.readline()
    if not line:
        sys.stderr.write("\n")
        return None
    return line.strip()


def _checked_url(url):
    try:
        return http.validate_url(url)
    except SourceError as error:
        raise UsageError(_("invalid --url: {reason}").format(reason=error)) from None


def _ask_url():
    """Ask for the download URL until a valid one is given (RF2)."""
    while True:
        answer = _ask(_("Download URL of the file: "))
        if answer is None:
            raise UsageError(_("no valid download URL was given"))
        try:
            return http.validate_url(answer)
        except SourceError as error:
            print(str(error), file=sys.stderr)


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
        resolve_options(args)
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
