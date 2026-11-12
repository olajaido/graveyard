"""Property tests for the token rules in ``environment_from_mapping`` (CLI-ENV-2, CLI-ENV-3).

**Validates: Requirements CLI-ENV-2, CLI-ENV-3**
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.env import environment_from_mapping
from core.sources.secret import SecretToken

pytestmark = pytest.mark.property

_WHITESPACE = st.text(alphabet=" \t\r\n\v\f\u00a0\u2003\u3000", max_size=20)
_VALID = st.text(
    alphabet=st.characters(
        min_codepoint=33, max_codepoint=126, blacklist_categories=("Cc", "Cs", "Zs", "Zl", "Zp")
    ),
    min_size=1,
    max_size=255,
).filter(lambda raw: not (raw.startswith("${") and raw.endswith("}")))


@given(_WHITESPACE)
def test_empty_or_whitespace_only_is_absent(blank: str) -> None:
    env = environment_from_mapping({"GITHUB_TOKEN": blank}, 100)
    assert env.token is None
    assert env.token_rejected is False


@given(_VALID)
def test_a_valid_token_is_kept_and_never_shown(raw: str) -> None:
    env = environment_from_mapping({"GITHUB_TOKEN": raw}, 100)
    assert isinstance(env.token, SecretToken)
    assert env.token.reveal() == raw
    assert env.token_rejected is False
    assert repr(env.token) == str(env.token) == f"{env.token}" == "SecretToken(***)"


@given(st.text(max_size=300))
def test_every_value_is_absent_valid_or_rejected_and_never_leaks(raw: str) -> None:
    env = environment_from_mapping({"GITHUB_TOKEN": raw}, 100)
    # exactly one of: absent, kept, rejected
    states = [
        env.token is None and not env.token_rejected,
        env.token is not None and not env.token_rejected,
        env.token is None and env.token_rejected,
    ]
    assert sum(states) == 1
    assert (not raw.strip()) == (env.token is None and not env.token_rejected)
    assert "GITHUB_TOKEN" not in env.syft_env


@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=24, max_size=60))
def test_a_long_token_never_appears_in_the_environment_repr(raw: str) -> None:
    env = environment_from_mapping({"GITHUB_TOKEN": raw}, 100)
    assert raw not in repr(env)
    assert raw not in str(dict(env.syft_env))
