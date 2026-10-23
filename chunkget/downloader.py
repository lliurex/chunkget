"""Orchestration of the ``download`` command."""

import re

from chunkget import config, http, manifest

# "scheme://": anything that looks like a URL is not a local path.
_URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")


def resolve_manifest(source, timeout=config.DEFAULT_TIMEOUT):
    """Return the validated manifest named by ``source``.

    ``source`` is a local path or an ``http(s)`` URL, told apart by its
    scheme. Any other URL scheme is a ``SourceError``.
    """
    text = str(source)
    if _URL_RE.match(text):
        http.validate_url(text)
        data = http.fetch_bytes(text, config.MAX_MANIFEST_BYTES, timeout)
        return manifest.load_manifest(data)
    return manifest.load_manifest_file(source)
