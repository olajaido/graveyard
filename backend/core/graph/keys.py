"""Package-key builders for lockfile entries (design §6, DG-DEP-2).

Each function builds a ``Purl`` and returns ``core.purl.package_key``, so keys
are never formatted by hand. The ``Purl`` constructor's ``ValueError`` is not
caught here: callers turn it into ``LOCKFILE_ENTRY_SKIPPED``. Pure: no I/O.
"""

from __future__ import annotations

from core.purl import Purl, normalise_pypi_name, package_key


def npm_key(name: str, version: str) -> str:
    """Return the package key of an npm package.

    ``@scope/name`` is split at the first ``/`` into namespace ``@scope`` and
    name ``name``. A malformed name (``@scope`` alone, extra ``/``, empty parts)
    makes the ``Purl`` constructor raise ``ValueError``.
    """
    if name.startswith("@") and "/" in name:
        namespace, _, bare = name.partition("/")
        return package_key(Purl("npm", namespace, bare, version))
    return package_key(Purl("npm", None, name, version))


def pypi_key(name: str, version: str) -> str:
    """Return the package key of a PyPI package, with ``name`` PEP 503-normalised."""
    return package_key(Purl("pypi", None, normalise_pypi_name(name), version))
