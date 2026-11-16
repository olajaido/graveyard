"""Pin (MV2-SRC-1, design 12.1): a Scorecard 404 is ``Absent`` and raises no warning.

The capture path in ``scripts/capture_anchors.py`` records a Scorecard 404 as "not scanned"
and relies on this client behaviour (SRC-HTTP-9). No client code changes for MV2-SRC-1.
"""

from __future__ import annotations

from datetime import date

from core.sources.urls import depsdev_project_url, scorecard_url
from sources.cache import Absent
from sources.clients import scorecard
from sources.tests.clients_support import ok, run_clients
from sources.tests.test_session import (
    LEFT_PAD,
    Web,
    collect,
    left_pad_routes,
    only,
)

AS_OF = date(2026, 11, 3)
REPO = "github.com/stevemao/left-pad"


def test_scorecard_client_returns_absent_for_a_404() -> None:
    run = run_clients(ok({}, 404), lambda ctx: scorecard.project(ctx, REPO))
    assert isinstance(run.value, Absent)


def test_assembled_result_has_no_s4_or_s8_warning_for_a_scorecard_404() -> None:
    routes = left_pad_routes()
    del routes[depsdev_project_url("stevemao", "left-pad")]  # deps.dev gives neither value
    web = Web(routes)  # the Scorecard URL is unrouted, so it answers 404

    result = only(collect(web, [(LEFT_PAD, AS_OF)]))

    assert scorecard_url("stevemao", "left-pad") in web.urls  # the Scorecard API was asked
    assert result.error is None and result.signals is not None
    assert result.signals.s4_maintained is None
    assert result.signals.s8_overall is None
    named = {s for w in result.warnings for s in w.signals}
    assert not {"s4_maintained", "s8_overall"} & named
    assert not [w for w in result.warnings if w.source in {"scorecard", "depsdev"}]
