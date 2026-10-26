"""Command line interface: the only module that talks to the terminal."""

import argparse
import os
import sys

import chunkget
from chunkget import config, downloader, events, hashing, http, publisher
from chunkget.errors import (
    ChunkgetError,
    DestinationExistsError,
    ExitCode,
    GlobalHashMismatchError,
    OutputExistsError,
    RetriesExhaustedError,
    SourceError,
    UsageError,
    UserDeclinedError,
)
from chunkget.i18n import _, ngettext


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
    place = make.add_mutually_exclusive_group()
    place.add_argument(
        "--download-to",
        metavar="PATH",
        help=_("with a URL source: download the file to PATH"),
    )
    place.add_argument(
        "--local-file",
        metavar="PATH",
        help=_("with a URL source: use the existing local file PATH"),
    )
    make.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=_("answer yes when asked whether to overwrite a file"),
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
    download.add_argument(
        "-o",
        "--output",
        metavar="OUTPUT",
        help=_("file to download to (default: ./<name> from the manifest)"),
    )
    download.add_argument(
        "--state-dir",
        metavar="DIR",
        help=_("directory of the state files (default: ~/.local/state/chunkget)"),
    )
    download.add_argument(
        "--manifest-file",
        metavar="PATH",
        help=_(
            "with a manifest URL: where to save it "
            "(default: ./<name>.chunkget.manifest)"
        ),
    )
    download.add_argument(
        "--restart",
        action="store_true",
        help=_("discard the saved state and download everything again"),
    )
    download.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help=_("answer yes when asked whether to overwrite a file"),
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
        return _make_manifest_from_url(args)
    for option, value in (("--download-to", args.download_to), ("--local-file", args.local_file)):
        if value is not None:
            raise UsageError(
                _("{option} can only be used when SOURCE is a URL").format(option=option)
            )
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
    output, overwrite = _output_choice(args, args.source)
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


def _make_manifest_from_url(args):
    """``make-manifest`` for a source that is a URL (RF3)."""
    if args.url is not None:
        raise UsageError(_("--url cannot be used when SOURCE is already a URL"))
    http.validate_url(args.source)
    download_to, local_file = args.download_to, args.local_file
    if download_to is None and local_file is None:
        if not _is_interactive():
            raise UsageError(
                _(
                    "SOURCE is a URL: use --download-to or --local-file "
                    "(there is no terminal to ask)"
                )
            )
        download_to, local_file = _ask_download_or_local()
    overwrite_download = False
    if download_to is not None:
        if os.path.lexists(download_to) and not args.yes:
            _confirm_overwrite(download_to)
        overwrite_download = True
        print(
            _(
                "warning: the downloaded file cannot be validated, because there "
                "is no manifest yet; the manifest will describe what is received"
            ),
            file=sys.stderr,
        )
    output, overwrite = _output_choice(args, download_to or local_file)
    written = publisher.make_manifest_from_url(
        args.source,
        output,
        download_to=download_to,
        local_file=local_file,
        chunk_size=args.chunk_size,
        algorithm=args.algorithm,
        overwrite=overwrite,
        overwrite_download=overwrite_download,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )
    print(_("Manifest written: {path}").format(path=written))
    return ExitCode.OK


def _output_choice(args, file_path):
    """Return ``(output path, overwrite)``, asking before replacing it (RF5).

    The default output is named after ``file_path``. The question is asked
    before the file is read or downloaded, so a refusal wastes no work.
    """
    output = args.output or config.default_manifest_path(os.path.basename(file_path))
    exists = os.path.lexists(output)
    if exists and not args.yes:
        _confirm_overwrite(output)
    return output, exists


def _matches(answer, *words):
    """True if ``answer`` is one of ``words`` or their translations."""
    accepted = set(words) | {_(word) for word in words}
    return answer.lower() in {word.lower() for word in accepted}


def _ask_download_or_local():
    """Ask whether to download the file or use a local one (RF3).

    Returns ``(download_to, local_file)``, one of them None.
    """
    while True:
        answer = _ask(_("Download the file or use an existing local file? [d/l] "))
        if answer is None:
            raise UsageError(_("no answer to whether to download or use a local file"))
        if _matches(answer, "d", "download"):
            return _ask_path(_("Path to download the file to: ")), None
        if _matches(answer, "l", "local"):
            return None, _ask_path(_("Path of the local file: "))
        print(_("please answer d (download) or l (local file)"), file=sys.stderr)


def _ask_path(prompt):
    while True:
        answer = _ask(prompt)
        if answer is None:
            raise UsageError(_("no path was given"))
        if answer:
            return answer


def _confirm_overwrite(path):
    """Ask before replacing ``path`` (RF5); declining is ``UserDeclinedError``.

    No terminal, no answer or anything but yes counts as a refusal.
    """
    if _is_interactive():
        answer = _ask(_("{path} already exists. Overwrite it? [y/N] ").format(path=path))
        if answer is not None and _matches(answer, "y", "yes"):
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


_SIZE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def _format_size(size):
    """``50 B``, ``48.0 MiB``, ``3.0 GiB``: binary units, one decimal."""
    value = float(size)
    for unit in _SIZE_UNITS[:-1]:
        if value < 1024:
            break
        value /= 1024
    else:
        unit = _SIZE_UNITS[-1]
    if unit == "B":
        return "%d B" % size
    return "%.1f %s" % (value, unit)


class _DownloadReporter:
    """Turns progress events into the messages of 7.4.

    Progress goes to stderr, one line per finished chunk; on a terminal the
    same line is rewritten. The saved manifest is a result and goes to stdout.
    """

    def __init__(self):
        self._name = ""
        self._size = 0
        self._done = 0
        self._algorithm = ""
        self._open_line = 0  # length of the progress line being rewritten

    def __call__(self, event):
        if isinstance(event, events.DownloadStarted):
            self._name, self._size, self._done = event.name, event.size, event.done_bytes
        elif isinstance(event, events.ManifestSaved):
            print(_("Manifest saved: {path}").format(path=event.path))
        elif isinstance(event, events.StaleStateDiscarded):
            self._message(
                _(
                    "warning: the saved state was discarded because {path} "
                    "no longer exists"
                ).format(path=event.destination)
            )
        elif isinstance(event, events.RetryStarted):
            self._message(
                ngettext(
                    "Retry pass {attempt}/{maximum}: {count} chunk pending",
                    "Retry pass {attempt}/{maximum}: {count} chunks pending",
                    event.pending,
                ).format(
                    attempt=event.attempt, maximum=event.max_retries, count=event.pending
                )
            )
        elif isinstance(event, events.ChunkDone):
            self._done += event.bytes
            self._progress(event)
        elif isinstance(event, events.GlobalCheckStarted):
            self._algorithm = event.algorithm
        elif isinstance(event, events.Finished):
            self._message(
                _("Global hash verified ({algorithm}).").format(algorithm=self._algorithm)
            )

    def _progress(self, event):
        percent = 100.0 * self._done / self._size if self._size else 100.0
        line = _(
            "Downloading {name}: chunk {index}/{total} ({percent:.1f}%), "
            "{done} of {size}"
        ).format(
            name=self._name,
            index=event.index + 1,
            total=event.total,
            percent=percent,
            done=_format_size(self._done),
            size=_format_size(self._size),
        )
        if sys.stderr.isatty():
            sys.stderr.write("\r" + line.ljust(self._open_line))
            self._open_line = len(line)
        else:
            sys.stderr.write(line + "\n")
        sys.stderr.flush()

    def finish(self):
        """End a progress line that is still being rewritten."""
        if self._open_line:
            sys.stderr.write("\n")
            sys.stderr.flush()
            self._open_line = 0

    def _message(self, text):
        """A line of its own: it ends a progress line that is being rewritten."""
        if self._open_line:
            sys.stderr.write("\n")
            self._open_line = 0
        sys.stderr.write(text + "\n")
        sys.stderr.flush()


def _download(args):
    if args.manifest_file is not None and not downloader.is_url(args.manifest):
        raise UsageError(
            _("--manifest-file can only be used when MANIFEST is a URL")
        )
    reporter = _DownloadReporter()
    try:
        return _run_download(args, reporter)
    except RetriesExhaustedError as error:
        if error.remaining is None:
            raise
        raise RetriesExhaustedError(
            _(
                "Download incomplete: {chunks} still failed after {passes}. "
                "Run the command again to resume."
            ).format(
                chunks=ngettext("{n} chunk", "{n} chunks", error.remaining).format(
                    n=error.remaining
                ),
                passes=ngettext(
                    "{n} retry pass", "{n} retry passes", error.retries
                ).format(n=error.retries),
            )
        ) from None
    except GlobalHashMismatchError:
        raise GlobalHashMismatchError(
            _(
                "Global validation failed: the file does not match the manifest "
                "hash. Use --restart to download it again."
            )
        ) from None
    finally:
        # An error message must not end up on the progress line.
        reporter.finish()


def _run_download(args, reporter):
    # The questions are asked when the core reports the conflict; it is then
    # called again with the answer already given.
    overwrite_manifest = args.yes
    while True:
        try:
            loaded = downloader.obtain_manifest(
                args.manifest,
                args.timeout,
                args.manifest_file,
                overwrite_manifest,
                reporter,
            )
            break
        except OutputExistsError as error:
            _confirm_overwrite(error.path)
            overwrite_manifest = True
    overwrite = args.yes
    while True:
        try:
            destination = downloader.download_manifest(
                loaded,
                args.output,
                args.state_dir,
                args.timeout,
                args.max_retries,
                restart=args.restart,
                overwrite=overwrite,
                listener=reporter,
            )
            break
        except DestinationExistsError as error:
            _confirm_overwrite(error.path)
            overwrite = True
    print(_("Download completed: {path}").format(path=destination))
    return ExitCode.OK


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
