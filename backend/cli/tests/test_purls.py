"""Unit tests for cli.purls.validate_purls (CLI-PURL-2, CLI-PURL-3)."""

from __future__ import annotations

import pytest

from cli.errors import UsageError
from cli.purls import validate_purls


def test_valid_npm() -> None:
    assert validate_purls(["pkg:npm/request@2.88.2"]) == ("pkg:npm/request@2.88.2",)


def test_valid_scoped_npm() -> None:
    assert validate_purls(["pkg:npm/@babel/core@7.0.0"]) == ("pkg:npm/%40babel/core@7.0.0",)


def test_pypi_is_normalised() -> None:
    assert validate_purls(["pkg:pypi/Foo_Bar@1.0"]) == ("pkg:pypi/foo-bar@1.0",)


@pytest.mark.parametrize(
    "text",
    ["not a purl", "pkg:maven/org.x/y@1.0", "pkg:npm/request", ""],
    ids=["text", "maven", "no-version", "empty"],
)
def test_invalid_is_rejected_with_one_line(text: str) -> None:
    with pytest.raises(UsageError) as info:
        validate_purls([text])
    message = info.value.message
    assert "\n" not in message
    assert message.startswith("--purl #1:")


def test_position_is_reported() -> None:
    with pytest.raises(UsageError, match=r"--purl #2:"):
        validate_purls(["pkg:npm/request@2.88.2", "nope"])


def test_long_text_is_truncated() -> None:
    with pytest.raises(UsageError) as info:
        validate_purls(["x" * 10_000])
    assert len(info.value.message) < 250
    assert "x" * 100 in info.value.message
    assert "x" * 101 not in info.value.message


def test_escape_is_replaced_in_message() -> None:
    with pytest.raises(UsageError) as info:
        validate_purls(["\x1b[31mevil"])
    message = info.value.message
    assert "\x1b" not in message
    assert "\ufffd" in message


def test_duplicates_collapse_keeping_smallest_canonical() -> None:
    # npm names are case-insensitive for package_key; "R" sorts before "r".
    result = validate_purls(["pkg:npm/request@2.88.2", "pkg:npm/Request@2.88.2"])
    assert result == ("pkg:npm/Request@2.88.2",)


def test_result_is_sorted_and_order_independent() -> None:
    raw = ["pkg:pypi/six@1.17.0", "pkg:npm/moment@2.0.0", "pkg:npm/express@4.17.1"]
    expected = tuple(sorted(validate_purls(raw)))
    assert validate_purls(raw) == expected
    assert validate_purls(list(reversed(raw))) == expected
