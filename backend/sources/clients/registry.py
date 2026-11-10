"""npm registry and PyPI clients (design §5, §6; SRC-LAT-1, SRC-S1, SRC-S2).

* ``npm_abbreviated``: ``GET registry.npmjs.org/{name}`` with
  ``Accept: application/vnd.npm.install-v1+json``; namespace ``registry.npm``, subject
  ``package_key`` of the resolved version (the parsed fact depends on it).
* ``npm_full``: the same URL with ``Accept: application/json``, the fallback for S2 and the
  repo; namespace ``registry.npm.full``, subject ``package_key`` of the latest version.
* ``pypi``: ``GET pypi.org/pypi/{name}/json``; namespace ``registry.pypi``, subject
  ``package_key`` of the resolved version.

A 404 is ``Absent``: the package does not exist there, which also rules out the deps.dev
latest-version fallback (SRC-LAT-3). See ``clients.common`` for the result shape.
"""

from __future__ import annotations

import dataclasses
from functools import partial
from typing import Final

from core.purl import Purl, package_key, registry_name
from core.sources.facts import NpmFull, NpmRegistry, PypiDoc
from core.sources.parse.registry import parse_npm_abbreviated, parse_npm_full, parse_pypi
from core.sources.urls import npm_packument_url, pypi_json_url
from sources.cache import fact_codec
from sources.clients.common import (
    ClientContext,
    ClientResult,
    call_source,
    get_request,
    require_version,
)

NPM_SOURCE: Final = "npm_registry"
PYPI_SOURCE: Final = "pypi"

NPM_ABBREVIATED_ACCEPT: Final = "application/vnd.npm.install-v1+json"

_NPM_CODEC: Final = fact_codec(NpmRegistry)
_NPM_FULL_CODEC: Final = fact_codec(NpmFull)
_PYPI_CODEC: Final = fact_codec(PypiDoc)


async def npm_abbreviated(ctx: ClientContext, purl: Purl) -> ClientResult[NpmRegistry]:
    """The abbreviated packument of an npm package; ``purl.version`` is the resolved version."""
    resolved = require_version(purl)
    return await call_source(
        ctx,
        namespace="registry.npm",
        subject=package_key(purl),
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(
            NPM_SOURCE, npm_packument_url(registry_name(purl)), accept=NPM_ABBREVIATED_ACCEPT
        ),
        parse=partial(parse_npm_abbreviated, resolved=resolved),
        codec=_NPM_CODEC,
    )


async def npm_full(ctx: ClientContext, purl: Purl, latest: str) -> ClientResult[NpmFull]:
    """The full packument of an npm package, read at its ``latest`` version.

    ``purl.version`` is not used, so the same purl serves any version.
    """
    latest_purl = dataclasses.replace(purl, version=latest)
    return await call_source(
        ctx,
        namespace="registry.npm.full",
        subject=package_key(latest_purl),
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(NPM_SOURCE, npm_packument_url(registry_name(purl))),
        parse=partial(parse_npm_full, latest=latest),
        codec=_NPM_FULL_CODEC,
    )


async def pypi(ctx: ClientContext, purl: Purl) -> ClientResult[PypiDoc]:
    """The PyPI JSON document of a project; ``purl.version`` is the resolved version."""
    resolved = require_version(purl)
    return await call_source(
        ctx,
        namespace="registry.pypi",
        subject=package_key(purl),
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(PYPI_SOURCE, pypi_json_url(registry_name(purl))),
        parse=partial(parse_pypi, resolved=resolved),
        codec=_PYPI_CODEC,
    )
