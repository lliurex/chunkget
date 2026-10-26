"""Orchestration of the ``make-manifest`` command."""

from chunkget import manifest, manifest_builder


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
