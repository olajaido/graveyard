"""The Graveyard Reader GitHub App: JWT and installation token (SB-FET-1, SB-SEC-3).

The private key arrives as an argument and is used only to sign. The token is wrapped in
``SecretToken`` so it cannot reach a log through ``repr`` or ``str``.
"""

from __future__ import annotations

import re
from typing import Final

import httpx
import jwt

from core.scan.errors import GITHUB_AUTH_FAILED, GITHUB_RATE_LIMITED, INTERNAL
from core.sources.secret import SecretToken

JWT_BACKDATE_SECONDS: Final = 60
JWT_LIFETIME_SECONDS: Final = 540  # at most 9 minutes (GitHub allows 10)
_DIGITS: Final = re.compile(r"[0-9]{1,20}")


def make_jwt(app_id: str, private_key_pem: str, now: int) -> str:
    """An RS256 JWT for the app, valid from ``now - 60`` for 9 minutes."""
    if _DIGITS.fullmatch(app_id) is None:
        raise GITHUB_AUTH_FAILED
    payload = {
        "iss": app_id,
        "iat": now - JWT_BACKDATE_SECONDS,
        "exp": now - JWT_BACKDATE_SECONDS + JWT_LIFETIME_SECONDS,
    }
    try:
        return jwt.encode(payload, private_key_pem, algorithm="RS256")
    except (ValueError, TypeError, jwt.PyJWTError):
        raise GITHUB_AUTH_FAILED from None


def installation_token(
    client: httpx.Client,
    app_id: str,
    installation_id: str,
    private_key_pem: str,
    now: int,
) -> SecretToken:
    """Ask GitHub for an installation access token. Public reads need no repository permission."""
    if _DIGITS.fullmatch(installation_id) is None:
        raise GITHUB_AUTH_FAILED
    signed = make_jwt(app_id, private_key_pem, now)
    try:
        response = client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {signed}"},
        )
    except httpx.HTTPError:
        raise INTERNAL from None
    if response.status_code in (401, 403, 404):
        raise GITHUB_AUTH_FAILED
    if response.status_code == 429:
        raise GITHUB_RATE_LIMITED
    if response.status_code != 201:
        raise INTERNAL
    try:
        return SecretToken(str(response.json()["token"]))
    except (ValueError, KeyError, TypeError):
        raise INTERNAL from None
