import httpx
import jwt
import pytest

from core.scan.errors import GITHUB_AUTH_FAILED, INTERNAL
from exhume.github_app import installation_token, make_jwt
from exhume.tests.support import make_key

PRIVATE, PUBLIC = make_key()
NOW = 1_763_000_000


def test_jwt_claims() -> None:
    claims = jwt.decode(
        make_jwt("12345", PRIVATE, NOW),
        PUBLIC,
        algorithms=["RS256"],
        options={"verify_exp": False, "verify_iat": False},
    )
    assert claims == {"iss": "12345", "iat": NOW - 60, "exp": NOW - 60 + 540}


def test_jwt_rejects_bad_app_id_and_key() -> None:
    with pytest.raises(GITHUB_AUTH_FAILED):
        make_jwt("UNSET", PRIVATE, NOW)
    with pytest.raises(GITHUB_AUTH_FAILED):
        make_jwt("1", "not a key", NOW)


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler, base_url="https://api.github.com")


def test_installation_token_request_and_redaction() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"token": "ghs_" + "a" * 36})

    token = installation_token(_client(httpx.MockTransport(respond)), "12345", "678", PRIVATE, NOW)
    assert seen[0].method == "POST" and seen[0].url.path == "/app/installations/678/access_tokens"
    assert seen[0].headers["authorization"].startswith("Bearer ")
    assert token.reveal().startswith("ghs_")
    assert "ghs_" not in repr(token) and "ghs_" not in f"{token}"


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_failures(status: int) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(status))
    with pytest.raises(GITHUB_AUTH_FAILED):
        installation_token(_client(transport), "1", "2", PRIVATE, NOW)


def test_unset_installation_id_never_calls_github() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(GITHUB_AUTH_FAILED):
        installation_token(_client(httpx.MockTransport(boom)), "1", "UNSET", PRIVATE, NOW)


def test_bad_body_is_internal() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(201, json={"nope": 1}))
    with pytest.raises(INTERNAL):
        installation_token(_client(transport), "1", "2", PRIVATE, NOW)
