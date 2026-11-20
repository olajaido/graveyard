import pytest

from core.scan.errors import INVALID_INPUT
from exhume.validate import Repo, parse_ref, parse_repo


@pytest.mark.parametrize(
    "text", ["olajaido/haunted-house", "a/b", "a-b/c.d_e", "A1/x", "o/.github", "o/name.js"]
)
def test_repo_accepts(text: str) -> None:
    repo = parse_repo(text)
    assert isinstance(repo, Repo) and repo.full_name == text


@pytest.mark.parametrize(
    "text",
    [
        "http://github.com/a/b",
        "https://github.com/a/b",
        "github.com/a/b",
        "a/b/c",
        "a",
        "",
        "a/b?x=1",
        "a/b#frag",
        "a b/c",
        "a/b c",
        "é/x",
        "a/é",
        "a/.",
        "a/..",
        "-a/b",
        "a-/b/",
        "a" * 40 + "/b",
        "a/" + "b" * 101,
        "a/b\n",
        "a\\b",
        "a/b%2f",
        "@a/b",
        None,
        5,
        ["a/b"],
    ],
)
def test_repo_rejects(text: object) -> None:
    with pytest.raises(INVALID_INPUT):
        parse_repo(text)


def test_owner_may_be_39_characters() -> None:
    assert parse_repo("a" * 39 + "/b").owner == "a" * 39


@pytest.mark.parametrize("ref", ["main", "v1.2.3", "feature/x-y", "release_1", "0123abcd"])
def test_ref_accepts(ref: str) -> None:
    assert parse_ref(ref) == ref


@pytest.mark.parametrize(
    "ref", ["", "-x", "a..b", "a//b", "a/", "x.lock", "a b", "é", "a" * 201, "../x", "a?b", None]
)
def test_ref_rejects(ref: object) -> None:
    with pytest.raises(INVALID_INPUT):
        parse_ref(ref)
