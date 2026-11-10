"""Parser for the Scorecard API document (design §6; SRC-S4, SRC-S8).

``GET api.securityscorecards.dev/projects/github.com/<owner>/<repo>`` returns the
scorecard itself at the top level: ``{"score": 6.2, "checks": [{"name": "Maintained",
"score": 10, ...}, ...], ...}`` (the deps.dev project document nests the same data under
``scorecard`` with ``overallScore``; see ``parse.depsdev.parse_project``).

The result is a ``DepsDevProject`` so that the assembler treats both sources alike: the
fact is the pair (``maintained``, ``overall``) plus ``has_scorecard``, and the evidence
URL says which source it came from. Reading rules match ``parse_project``:

* ``overall`` is ``score`` and ``maintained`` is the ``score`` of the first ``checks[]``
  entry named ``Maintained``, both through ``as_score`` (``-1`` passes through; out of
  range, non-finite, ``bool`` and non-numeric values become ``None``).
* ``has_scorecard`` is true when the document carries the scorecard shape: a ``score``
  key or a ``checks`` list. A mapping with neither (for example an error body) gives
  ``has_scorecard`` false and no values.
* A non-mapping gives ``None``.

Check names, reasons, details, repo and commit fields are never read (D11). Never raises.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from typing import Final

from core.sources.accessors import as_list, as_mapping, as_score
from core.sources.facts import DepsDevProject

_MAINTAINED: Final = "Maintained"


def parse_scorecard_api(data: object) -> DepsDevProject | None:
    """Reduce a Scorecard API document to its overall and ``Maintained`` scores."""
    doc = as_mapping(data)
    if doc is None:
        return None
    checks = as_list(doc.get("checks"))
    has_scorecard = "score" in doc or checks is not None
    maintained: float | None = None
    for item in checks or []:
        check = as_mapping(item)
        if check is not None and check.get("name") == _MAINTAINED:
            maintained = as_score(check.get("score"))
            break
    return DepsDevProject(
        maintained=maintained,
        overall=as_score(doc.get("score")),
        has_scorecard=has_scorecard,
    )
