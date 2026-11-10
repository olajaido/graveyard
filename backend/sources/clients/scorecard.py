"""Scorecard API client (design §5, §6; SRC-S4, SRC-S8).

``GET https://api.securityscorecards.dev/projects/github.com/{owner}/{repo}``; cache namespace
``scorecard``, subject ``repo_key``. A 404 is ``Absent`` (SRC-HTTP-9). The fact is a
``DepsDevProject``, so the assembler treats this source and the deps.dev project document
alike.
"""

from __future__ import annotations

from typing import Final

from core.sources.facts import DepsDevProject
from core.sources.parse.scorecard import parse_scorecard_api
from core.sources.urls import scorecard_url
from sources.cache import fact_codec
from sources.clients.common import (
    ClientContext,
    ClientResult,
    call_source,
    get_request,
    split_repo,
)

SOURCE: Final = "scorecard"

_CODEC: Final = fact_codec(DepsDevProject)


async def project(ctx: ClientContext, repo: str) -> ClientResult[DepsDevProject]:
    """The Scorecard API document of ``repo`` (``github.com/<owner>/<repo>``)."""
    key, owner, name = split_repo(repo)
    return await call_source(
        ctx,
        namespace="scorecard",
        subject=key,
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(SOURCE, scorecard_url(owner, name)),
        parse=parse_scorecard_api,
        codec=_CODEC,
    )
