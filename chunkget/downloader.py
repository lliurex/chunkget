"""Orchestration of the ``download`` command."""

import re

from chunkget import config, events, http, manifest

# "scheme://": anything that looks like a URL is not a local path.
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def read_manifest(source, timeout):
    """Return ``(manifest, data)``: the validated manifest and, if it came
    from a URL, the bytes received (``None`` for a local file)."""
    text = str(source)
    if _URL_RE.match(text):
        http.validate_url(text)
        data = http.fetch_bytes(text, config.MAX_MANIFEST_BYTES, timeout)
        return manifest.load_manifest(data), data
    return manifest.load_manifest_file(source), None


def resolve_manifest(source, timeout=config.DEFAULT_TIMEOUT):
    """Return the validated manifest named by ``source``.

    ``source`` is a local path or an ``http(s)`` URL, told apart by its
    scheme. Any other URL scheme is a ``SourceError``. Nothing is written.
    """
    return read_manifest(source, timeout)[0]


def obtain_manifest(
    source,
    timeout=config.DEFAULT_TIMEOUT,
    manifest_file=None,
    overwrite_manifest=False,
    listener=None,
):
    """Resolve the manifest of a download, keeping a local copy of a remote one.

    A manifest read from a URL is validated, saved as a local file (see
    ``manifest.save_manifest``) and a ``ManifestSaved`` event is sent to
    ``listener``; the download goes on with the validated manifest in
    memory. A local manifest is used as it is and nothing is written.
    """
    loaded, data = read_manifest(source, timeout)
    if data is not None:
        path = manifest.save_manifest(data, manifest_file, overwrite_manifest)
        if listener is not None:
            listener(events.ManifestSaved(path=str(path)))
    return loaded
