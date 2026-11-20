"""GitHub Trees and blobs for a public repository (SB-FET-2, SB-FET-6).

Every URL is built here from a validated ``Repo`` and ``ref``; nothing from a response is
followed as a URL. The client is passed in with ``base_url="https://api.github.com"``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from core.scan.errors import (
    GITHUB_AUTH_FAILED,
    GITHUB_RATE_LIMITED,
    INTERNAL,
    NO_MANIFESTS,
    REPO_NOT_FOUND,
    TOO_LARGE,
    TREE_TRUNCATED,
)
from core.sources.secret import SecretToken
from exhume.validate import Repo


class GithubReader:
    def __init__(self, client: httpx.Client, token: SecretToken) -> None:
        self._client = client
        self._token = token
        self.rate_remaining: int | None = None

    def _get(self, path: str, accept: str) -> httpx.Response:
        try:
            response = self._client.get(
                path,
                headers={
                    "Authorization": f"Bearer {self._token.reveal()}",
                    "Accept": accept,
                },
            )
        except httpx.HTTPError:
            raise INTERNAL from None
        remaining = response.headers.get("x-ratelimit-remaining")
        if remaining is not None and remaining.isdigit():
            self.rate_remaining = int(remaining)
        if response.status_code == 429 or (
            response.status_code == 403 and (remaining == "0" or "retry-after" in response.headers)
        ):
            raise GITHUB_RATE_LIMITED
        if response.status_code == 401:
            raise GITHUB_AUTH_FAILED
        if response.status_code in (403, 404):
            raise REPO_NOT_FOUND
        if response.status_code == 409:  # an empty repository
            raise NO_MANIFESTS
        if response.status_code != 200:
            raise INTERNAL
        return response

    def tree(self, repo: Repo, ref: str | None) -> list[dict[str, Any]]:
        """The recursive tree entries. Raises ``TREE_TRUNCATED`` when GitHub cut the list."""
        target = quote(ref or "HEAD", safe="/")
        response = self._get(
            f"/repos/{repo.owner}/{repo.name}/git/trees/{target}?recursive=1",
            "application/vnd.github+json",
        )
        try:
            body = response.json()
            if body.get("truncated"):
                raise TREE_TRUNCATED
            entries = body["tree"]
        except (ValueError, KeyError, AttributeError):
            raise INTERNAL from None
        if not isinstance(entries, list):
            raise INTERNAL
        return [e for e in entries if isinstance(e, dict)]

    def blob(self, repo: Repo, sha: str, max_bytes: int) -> bytes:
        """The raw bytes of one blob, at most ``max_bytes``."""
        if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
            raise INTERNAL
        response = self._get(
            f"/repos/{repo.owner}/{repo.name}/git/blobs/{sha}",
            "application/vnd.github.raw+json",
        )
        if len(response.content) > max_bytes:
            raise TOO_LARGE
        return response.content
