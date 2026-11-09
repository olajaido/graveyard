"""Property tests for ``normalise_repo_url`` and ``repo_key`` (PV-INV-9 to 13).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.purl.repo_url import normalise_repo_url, repo_key
from core.purl.tests.strategies import adversarial_repo_urls, repo_urls

pytestmark = pytest.mark.property

# Local oracle, deliberately not imported from ``core.purl``.
_OUT = re.compile(r"^github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

# ``st.text()`` excludes surrogates by default, so generate them explicitly.
_ANY_TEXT = st.one_of(
    st.text(),
    st.text(st.characters(codec=None, categories=["Cs"])),
    st.text(st.characters(codec=None), max_size=3000),
)


def _check_shape(out: str | None) -> None:
    if out is None:
        return
    assert _OUT.fullmatch(out) is not None, out
    owner, repo = out.split("/")[1:]
    assert owner not in {".", ".."}
    assert repo not in {".", ".."}


@given(st.one_of(repo_urls().map(lambda t: t[0]), _ANY_TEXT))
def test_repo_normaliser_idempotent(s: str) -> None:
    """If ``r = normalise_repo_url(s)`` is not ``None`` then ``normalise_repo_url(r) == r``.

    **Validates: Requirements PV-INV-9**
    """
    r = normalise_repo_url(s)
    if r is not None:
        assert normalise_repo_url(r) == r


@given(st.one_of(repo_urls().map(lambda t: t[0]), adversarial_repo_urls(), _ANY_TEXT))
def test_repo_output_shape(s: str) -> None:
    """Output is ``None`` or fully matches the github.com/owner/repo shape.

    **Validates: Requirements PV-INV-10**
    """
    _check_shape(normalise_repo_url(s))


@given(st.one_of(repo_urls().map(lambda t: t[0]), adversarial_repo_urls(), _ANY_TEXT))
def test_repo_never_raises(s: str) -> None:
    """No exception escapes ``normalise_repo_url`` (PV-REPO-12).

    **Validates: Requirements PV-INV-10**
    """
    normalise_repo_url(s)


@given(adversarial_repo_urls())
def test_repo_adversarial_never_github(s: str) -> None:
    """Foreign hosts, userinfo tricks and path traversal never yield a result.

    **Validates: Requirements PV-INV-11**
    """
    assert normalise_repo_url(s) is None, s


_KEY_OUT = re.compile(r"^github\.com/[a-z0-9_.-]+/[a-z0-9_.-]+$")
_CASERS = st.sampled_from([str.lower, str.upper, str.swapcase])


@given(repo_urls())
def test_repo_key_idempotent(case: tuple[str, str, str]) -> None:
    """``repo_key(repo_key(r)) == repo_key(r)``; the key is itself valid input.

    **Validates: Requirements PV-INV-13**
    """
    r = normalise_repo_url(case[0])
    assert r is not None
    k = repo_key(r)
    assert repo_key(k) == k


@given(repo_urls(), _CASERS, _CASERS)
def test_repo_key_case_insensitive(
    case: tuple[str, str, str], owner_case: Callable[[str], str], repo_case: Callable[[str], str]
) -> None:
    """Keys are fully lower-case and equal for URLs differing only in owner/repo case.

    **Validates: Requirements PV-INV-13**
    """
    url, owner, repo = case
    r = normalise_repo_url(url)
    assert r is not None
    k = repo_key(r)
    assert _KEY_OUT.fullmatch(k) is not None, k

    variant = normalise_repo_url(f"https://github.com/{owner_case(owner)}/{repo_case(repo)}")
    assert variant is not None
    assert repo_key(variant) == k


@given(repo_urls())
def test_repo_accepted_forms_exact(case: tuple[str, str, str]) -> None:
    """Every accepted form gives exactly ``github.com/<owner>/<repo>``, case preserved.

    **Validates: Requirements PV-INV-12**
    """
    url, owner, repo = case
    assert normalise_repo_url(url) == f"github.com/{owner}/{repo}"
