"""Orchestration of the ``make-manifest`` command."""

from chunkget import manifest, manifest_builder


def make_manifest(
    source, url, output=None, chunk_size=None, algorithm=None, listener=None
):
    """Build the manifest of the local file ``source`` and write it.

    The manifest is computed completely first and written at the end, so a
    failure while reading ``source`` leaves no partial file. ``output``
    defaults to ``./<name>.chunkget.manifest``. Returns the path written.
    """
    built = manifest_builder.build_manifest(
        source, url, chunk_size, algorithm, listener
    )
    return manifest.save_manifest(built.to_json().encode("utf-8"), output)
