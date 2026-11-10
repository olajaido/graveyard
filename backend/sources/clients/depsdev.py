"""deps.dev client: version, package and project documents (design §5, §6; SRC-LAT-1).

* ``version``: ``GET /v3/systems/{s}/packages/{name}/versions/{version}``; cache namespace
  ``depsdev.version``, subject ``package_key`` of that version.
* ``package``: ``GET /v3/systems/{s}/packages/{name}``, the latest-version fallback when the
  registry failed; namespace ``depsdev.package``, subject ``<ecosystem>/<name>`` with the name
  ASCII-lower-cased (it holds no version).
* ``project``: ``GET /v3/projects/github.com%2F{owner}%2F{repo}``; namespace
  ``depsdev.project``, subject ``repo_key``.

A 404 is ``Absent`` for all three (SRC-HTTP-9). See ``clients.common`` for the result shape.
"""

from __future__ import annotations

import dataclasses
import string
from typing import Final

from core.purl import Purl, package_key, registry_name
from core.sources.facts import DepsDevPackage, DepsDevProject, DepsDevVersion
from core.sources.parse.depsdev import parse_package, parse_project, parse_version
from core.sources.urls import depsdev_package_url, depsdev_project_url, depsdev_version_url
from sources.cache import fact_codec
from sources.clients.common import (
    ClientContext,
    ClientResult,
    call_source,
    get_request,
    split_repo,
)

SOURCE: Final = "depsdev"

_ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_VERSION_CODEC: Final = fact_codec(DepsDevVersion)
_PACKAGE_CODEC: Final = fact_codec(DepsDevPackage)
_PROJECT_CODEC: Final = fact_codec(DepsDevProject)


async def version(
    ctx: ClientContext, purl: Purl, target_version: str
) -> ClientResult[DepsDevVersion]:
    """The deps.dev document of ``target_version`` of the package ``purl`` names.

    ``purl.version`` is not used, so the same purl serves the resolved and the latest version.
    """
    url = depsdev_version_url(purl.ecosystem, registry_name(purl), target_version)
    versioned = dataclasses.replace(purl, version=target_version)
    return await call_source(
        ctx,
        namespace="depsdev.version",
        subject=package_key(versioned),
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(SOURCE, url),
        parse=parse_version,
        codec=_VERSION_CODEC,
    )


async def package(ctx: ClientContext, purl: Purl) -> ClientResult[DepsDevPackage]:
    """The deps.dev package document, reduced to its default version (SRC-LAT-1)."""
    name = registry_name(purl)
    url = depsdev_package_url(purl.ecosystem, name)
    return await call_source(
        ctx,
        namespace="depsdev.package",
        subject=f"{purl.ecosystem}/{name.translate(_ASCII_LOWER)}",
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(SOURCE, url),
        parse=parse_package,
        codec=_PACKAGE_CODEC,
    )


async def project(ctx: ClientContext, repo: str) -> ClientResult[DepsDevProject]:
    """The deps.dev project document (Scorecard block) of ``github.com/<owner>/<repo>``."""
    key, owner, name = split_repo(repo)
    return await call_source(
        ctx,
        namespace="depsdev.project",
        subject=key,
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(SOURCE, depsdev_project_url(owner, name)),
        parse=parse_project,
        codec=_PROJECT_CODEC,
    )
