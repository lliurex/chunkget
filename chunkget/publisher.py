"""Orchestration of the ``make-manifest`` command."""

import os
import time

from chunkget import config, http, manifest, manifest_builder
from chunkget.errors import DestinationExistsError
from chunkget.i18n import _


def make_manifest(
    source,
    url,
    output=None,
    chunk_size=None,
    algorithm=None,
    overwrite=False,
    listener=None,
):
    """Build the manifest of the local file ``source`` and write it.

    The manifest is computed completely first and written at the end, so a
    failure while reading ``source`` leaves no partial file and keeps any
    previous manifest. ``output`` defaults to ``./<name>.chunkget.manifest``.
    If it exists with another content, ``OutputExistsError`` is raised
    unless ``overwrite`` is true (the caller asked the user, RF5); then it
    is truncated and written as if it did not exist. Returns the path.
    """
    built = manifest_builder.build_manifest(
        source, url, chunk_size, algorithm, listener
    )
    return manifest.save_manifest(built.to_json().encode("utf-8"), output, overwrite)


def make_manifest_from_url(
    url,
    output=None,
    download_to=None,
    local_file=None,
    chunk_size=None,
    algorithm=None,
    overwrite=False,
    overwrite_download=False,
    timeout=config.DEFAULT_TIMEOUT,
    max_retries=config.DEFAULT_MAX_RETRIES,
    sleep=time.sleep,
    listener=None,
):
    """Build the manifest of a file published at ``url`` (RF3).

    Exactly one of ``download_to`` (download the file there first) and
    ``local_file`` (use that existing copy) must be given: the caller has
    already asked the user. The manifest is then made as in
    ``make_manifest``, with ``url`` as its ``url`` and the base name of the
    local file as its ``name``. The download cannot be validated, because no
    manifest exists yet. An existing ``download_to`` raises
    ``DestinationExistsError`` unless ``overwrite_download`` is true.
    """
    if (download_to is None) == (local_file is None):
        raise ValueError(_("give either a file to download to or a local file"))
    http.validate_url(url)
    if download_to is not None:
        if os.path.lexists(download_to) and not overwrite_download:
            raise DestinationExistsError(
                _("the destination {path} already exists").format(path=download_to),
                path=download_to,
            )
        http.simple_download(url, download_to, timeout, max_retries, sleep)
        local_file = download_to
    return make_manifest(
        local_file, url, output, chunk_size, algorithm, overwrite, listener
    )
