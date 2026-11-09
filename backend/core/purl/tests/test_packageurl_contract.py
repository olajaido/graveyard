"""Contract tests pinning the packageurl-python behaviours that our wrapper compensates for.

See design §2 and §6.3 of the purl-and-versions spec. These tests assert the
*library's* current behaviour, not ours. If a library upgrade makes one of them
fail, that is the intended signal to simplify the wrapper (and update the
test), not to delete it.

Finding (T2.2): on packageurl-python 0.17.6, ``from_string`` accepts unpaired
surrogates; only ``quote`` / ``to_string`` raise ``UnicodeEncodeError``.

Validates: PV-PURL-2, PV-PURL-5, PV-PURL-7, PV-PURL-8, PV-PURL-11, PV-PURL-13.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from packageurl import PackageURL, quote

FIXTURES = Path(__file__).parent / "fixtures"

# The purl Syft v1.56.0 emitted for the npm package `JSONStream` (copied from
# fixtures/syft_jsonstream.json; test_fixture_purl_matches_literal keeps the two in sync).
# Syft preserved the registry case in `purl` (its `bom-ref` is lower case).
SYFT_JSONSTREAM_PURL = "pkg:npm/JSONStream@1.3.5"


def _load_syft_component() -> dict[str, Any]:
    with (FIXTURES / "syft_jsonstream.json").open(encoding="utf-8") as fh:
        return cast("dict[str, Any]", json.load(fh))


class TestNpmNameCase:
    def test_from_string_lower_cases_npm_name(self) -> None:
        assert PackageURL.from_string("pkg:npm/JSONStream@1.3.5").name == "jsonstream"

    def test_to_string_lower_cases_npm_name(self) -> None:
        purl = PackageURL(type="npm", name="JSONStream", version="1.3.5")
        assert purl.to_string() == "pkg:npm/jsonstream@1.3.5"

    def test_normalize_purl_false_keeps_case(self) -> None:
        purl = PackageURL.from_string("pkg:npm/JSONStream@1.3.5", normalize_purl=False)
        assert purl.name == "JSONStream"


class TestPypiNames:
    def test_dot_is_not_normalised(self) -> None:
        assert PackageURL.from_string("pkg:pypi/zope.interface@6.0").name == "zope.interface"

    def test_underscore_runs_become_double_hyphen(self) -> None:
        purl = PackageURL(type="pypi", name="Zope.Interface__x")
        assert purl.name == "zope.interface--x"


class TestParsingQuirks:
    def test_empty_version_is_none(self) -> None:
        assert PackageURL.from_string("pkg:npm/left-pad@").version is None

    def test_duplicate_qualifier_keys_collapse_to_last(self) -> None:
        purl = PackageURL.from_string("pkg:npm/x?a=1&a=2")
        assert purl.qualifiers == {"a": "2"}

    def test_encoded_slash_decodes_into_name_and_formats_unencoded(self) -> None:
        purl = PackageURL.from_string("pkg:npm/x%2Fy@1")
        assert purl.name == "x/y"
        assert purl.to_string() == "pkg:npm/x/y@1"

    def test_malformed_escape_kept_literally(self) -> None:
        assert PackageURL.from_string("pkg:npm/%zz@1").name == "%zz"

    def test_spaces_around_segments_are_stripped(self) -> None:
        assert PackageURL.from_string("pkg:npm/ x @1").name == "x"

    def test_double_at_parses_with_trailing_at_in_name(self) -> None:
        purl = PackageURL.from_string("pkg:npm/x@@1")
        assert purl.name == "x@"
        assert purl.version == "1"


class TestScheme:
    def test_upper_case_scheme_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            PackageURL.from_string("PKG:npm/x@1")

    def test_double_slash_scheme_accepted(self) -> None:
        purl = PackageURL.from_string("pkg://npm/x@1")
        assert (purl.type, purl.name, purl.version) == ("npm", "x", "1")


class TestQuote:
    @pytest.mark.parametrize("ch", ["/", ":"])
    def test_leaves_safe_characters_unencoded(self, ch: str) -> None:
        assert quote(f"a{ch}b") == f"a{ch}b"

    @pytest.mark.parametrize(
        ("ch", "encoded"),
        [
            ("@", "%40"),
            ("+", "%2B"),
            ("?", "%3F"),
            ("#", "%23"),
            ("%", "%25"),
            ("é", "%C3%A9"),
        ],
    )
    def test_encodes_reserved_and_non_ascii(self, ch: str, encoded: str) -> None:
        assert quote(f"a{ch}b") == f"a{encoded}b"


class TestSurrogates:
    # Design §2 says `from_string` raises here. On 0.17.6 it does not: parsing
    # accepts the surrogate and the failure surfaces only when encoding
    # (`quote` / `to_string`). The wrapper must therefore guard both sides.

    def test_from_string_accepts_unpaired_surrogate(self) -> None:
        assert PackageURL.from_string("pkg:npm/\ud800@1").name == "\ud800"

    def test_quote_raises_unicode_encode_error(self) -> None:
        with pytest.raises(UnicodeEncodeError) as info:
            quote("\ud800")
        assert isinstance(info.value, ValueError)

    def test_to_string_raises_unicode_encode_error(self) -> None:
        purl = PackageURL.from_string("pkg:npm/\ud800@1")
        with pytest.raises(UnicodeEncodeError) as info:
            purl.to_string()
        assert isinstance(info.value, ValueError)


class TestSyftJsonStream:
    """PV-SYFT-3: Syft v1.56.0 emitted the upper-case spelling `pkg:npm/JSONStream@1.3.5`.

    The assertions below hold whichever case Syft emits.
    """

    # TODO(T4.4, T5.2): add parse_purl, package_key and registry_name assertions.

    def test_fixture_purl_matches_literal(self) -> None:
        assert _load_syft_component()["purl"] == SYFT_JSONSTREAM_PURL

    def test_library_accepts_emitted_purl(self) -> None:
        purl = PackageURL.from_string(SYFT_JSONSTREAM_PURL)
        assert purl.type == "npm"
        assert purl.version == _load_syft_component()["version"]

    def test_registry_name_equivalent_is_component_name(self) -> None:
        component = _load_syft_component()
        raw = PackageURL.from_string(SYFT_JSONSTREAM_PURL, normalize_purl=False)
        assert raw.name == component["name"] == "JSONStream"

    def test_lower_case_spelling_has_same_dedupe_identity(self) -> None:
        emitted = PackageURL.from_string(SYFT_JSONSTREAM_PURL)
        lowered = PackageURL.from_string(SYFT_JSONSTREAM_PURL.lower())
        assert (emitted.namespace, emitted.name, emitted.version) == (
            lowered.namespace,
            lowered.name,
            lowered.version,
        )
