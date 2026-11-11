"""Property tests for ``why``, the gate, the report and the renderer (T6.7; CLI-TEST-6).

Inputs are valid-domain ``Signals`` from the scoring strategies, so every case is a
package the real pipeline could produce. The Hypothesis profile sets ``max_examples``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.args import GateClass
from cli.gate import evaluate, matches
from cli.render import render_stderr_notes, render_table
from cli.report import report_to_dict
from cli.tests.support import make_report
from cli.text import sanitise
from cli.why import why
from core.scoring import score_package
from core.scoring.tests.strategies import valid_signals_kwargs
from core.scoring.types import Signals

pytestmark = pytest.mark.property

_WORDS: tuple[GateClass, ...] = ("dead", "cursed", "ailing")
_class_sets = st.frozensets(st.sampled_from(_WORDS))


def _signals_list(kwargs_list: list[dict[str, Any]]) -> list[Signals]:
    """Distinct purls (the sort requires uniqueness) and one shared as_of."""
    as_of = kwargs_list[0]["as_of"]
    out: list[Signals] = []
    for index, kwargs in enumerate(kwargs_list):
        values = dict(kwargs)
        values["purl"] = f"pkg:npm/p{index}@1.0.0"
        values["as_of"] = as_of
        out.append(Signals(**{**values, "paths": None, "services_affected": None}))
    return out


_signal_lists = st.lists(valid_signals_kwargs(), min_size=1, max_size=5).map(_signals_list)


@given(valid_signals_kwargs())
def test_why_total_and_clean(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements CLI-OUT-4, CLI-OUT-8**"""
    signals = Signals(**kwargs)
    text = why(score_package(signals), signals)
    assert text
    assert sanitise(text) == text
    assert "\n" not in text


@given(valid_signals_kwargs(), _class_sets, _class_sets)
def test_gate_monotone(kwargs: dict[str, Any], first: frozenset[GateClass], extra: Any) -> None:
    """Adding a class to ``--fail-on`` never turns a match into a non-match.

    **Validates: Requirements CLI-GATE-1**
    """
    result = score_package(Signals(**kwargs))
    wider = first | extra
    if matches(result, first):
        assert matches(result, wider)


@given(_signal_lists, _class_sets)
def test_gate_subset_of_rows(signals_list: list[Signals], fail_on: frozenset[GateClass]) -> None:
    """The matches are a subsequence of the ranked purls; no fail-on class, no matches.

    **Validates: Requirements CLI-GATE-1, CLI-GATE-2**
    """
    report = make_report(signals_list, fail_on=fail_on)
    ranked = [row.scoring.purl for row in report.rows]
    assert set(report.matches) <= set(ranked)
    assert list(report.matches) == [p for p in ranked if p in set(report.matches)]
    assert evaluate(report.rows, frozenset()) == ()
    assert bool(report.matches) == (report.exit_code == 1)


@given(_signal_lists, _class_sets)
def test_report_dict_json_safe(signals_list: list[Signals], fail_on: frozenset[GateClass]) -> None:
    """**Validates: Requirements CLI-JSON-1, CLI-JSON-3, CLI-TEST-6**"""
    doc = report_to_dict(make_report(signals_list, fail_on=fail_on))
    text = json.dumps(doc, allow_nan=False)
    assert json.loads(text) == doc
    key_sets = {tuple(package) for package in doc["packages"]}
    assert len(key_sets) == 1
    assert [p["rank"] for p in doc["packages"]] == list(range(1, len(signals_list) + 1))
    assert sum(doc["summary"]["states"].values()) == len(signals_list)


@given(_signal_lists, st.integers(min_value=0, max_value=200), st.booleans())
def test_render_has_no_control_chars(
    signals_list: list[Signals], width: int, show_all: bool
) -> None:
    """**Validates: Requirements CLI-OUT-8, CLI-OUT-10**"""
    report = make_report(signals_list, fail_on=frozenset({"dead", "cursed", "ailing"}))
    for text in (render_table(report, width, show_all), render_stderr_notes(report)):
        assert sanitise(text.replace("\n", "")) == text.replace("\n", "")


@given(_signal_lists, st.booleans())
def test_render_is_deterministic(signals_list: list[Signals], show_all: bool) -> None:
    """**Validates: Requirements CLI-OUT-10**"""
    report = make_report(signals_list)
    again = replace(report)
    assert render_table(report, 100, show_all) == render_table(again, 100, show_all)
