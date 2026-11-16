"""The v2 input set equals v1's (MV2-IN-1) and reads no text (MV2-IN-2).

The literals below were generated once from commit ``00c373e`` with ``git show`` (the files
``backend/core/scoring/{types,__init__,classify,constants,normalise,priority,score,sort,weights}.py``,
``backend/core/sources/model.py`` and ``backend/core/sources/urls.py``) and pasted here. They are
not recomputed from the working tree.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from importlib import import_module
from pathlib import Path

from core.scoring.types import Signals

SCORING_DIR = Path(__file__).resolve().parents[2]
SOURCES_DIR = SCORING_DIR.parents[0] / "sources"
V2_DIR = SCORING_DIR / "v2"

# MV2-IN-1: empty at this revision. Adding an element needs an amendment to requirements.md.
ALLOWED_NEW_SIGNALS: tuple[str, ...] = ()

# (a) field names of ``core.scoring.types.Signals`` at 00c373e.
SIGNALS_FIELDS_00C373E = frozenset(
    {
        "purl",
        "as_of",
        "s2_latest_release_at",
        "s3_last_push_at",
        "s4_maintained",
        "s5_committers",
        "s6_open_issues",
        "s6_closed_issues",
        "s8_overall",
        "s1_declared_death",
        "s1b_version_deprecated",
        "s7_advisories",
        "s9_weekly_downloads",
        "paths",
        "services_affected",
        "shared_repo",
    }
)

# (b) ``Signals`` attributes read (``ast.Attribute`` nodes whose name is a Signals field) by
# the v1 modules ``__init__``, ``classify``, ``constants``, ``normalise``, ``priority``,
# ``score``, ``sort`` and ``weights`` of ``core/scoring`` at 00c373e.
SIGNALS_ATTRS_READ_00C373E = frozenset(
    {
        "as_of",
        "paths",
        "purl",
        "s1_declared_death",
        "s1b_version_deprecated",
        "s2_latest_release_at",
        "s3_last_push_at",
        "s4_maintained",
        "s5_committers",
        "s6_closed_issues",
        "s6_open_issues",
        "s7_advisories",
        "s8_overall",
        "s9_weekly_downloads",
        "services_affected",
    }
)

# (c) ``core.sources.model.EVIDENCE_KEYS`` at 00c373e (SRC-API-3).
EVIDENCE_KEYS_00C373E = (
    "s1_declared_death",
    "s1b_version_deprecated",
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s7_advisories",
    "s8_overall",
    "s9_weekly_downloads",
)

# (d) top-level function names (builders and helpers) of ``core/sources/urls.py`` at 00c373e.
URL_FUNCTIONS_00C373E = frozenset(
    {
        "_depsdev_ecosystem",
        "_q",
        "depsdev_package_url",
        "depsdev_project_url",
        "depsdev_version_url",
        "github_graphql_url",
        "is_bulk_safe",
        "is_valid_osv_id",
        "npm_downloads_bulk_url",
        "npm_downloads_single_url",
        "npm_packument_url",
        "osv_querybatch_url",
        "osv_vuln_url",
        "pypi_json_url",
        "pypistats_recent_url",
        "scorecard_url",
        "strip_userinfo",
    }
)

TEXT_WORDS = re.compile(r"readme|description|badge|topic|changelog|summary|body", re.IGNORECASE)


def _require_v2() -> list[Path]:
    """Import ``core.scoring.v2`` (fails until T7.5) and return its non-test sources."""
    module = import_module("core.scoring.v2")
    assert callable(getattr(module, "score_package_v2", None)), "score_package_v2 is missing"
    return sorted(p for p in V2_DIR.rglob("*.py") if "tests" not in p.relative_to(V2_DIR).parts)


def _v2_closure_sources() -> list[Path]:
    """Scoring sources of the ``core.scoring.v2`` closure: the v1 modules and ``v2/``.

    ``versions.py`` is not in this closure (it imports ``v2`` inside a function).
    """
    v1 = [p for p in SCORING_DIR.glob("*.py") if p.name != "versions.py"]
    return sorted(v1 + _require_v2())


def _signals_attrs(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in SIGNALS_FIELDS_00C373E:
                found.add(node.attr)
    return found


def _url_functions() -> set[str]:
    tree = ast.parse((SOURCES_DIR / "urls.py").read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


def test_v2_input_set() -> None:
    """MV2-IN-1 (a) to (d), plus ``ALLOWED_NEW_SIGNALS == ()``."""
    assert ALLOWED_NEW_SIGNALS == ()
    sources = _v2_closure_sources()

    # (a)
    fields = {f.name for f in dataclasses.fields(Signals)}
    assert fields == SIGNALS_FIELDS_00C373E | set(ALLOWED_NEW_SIGNALS)

    # (b) over the whole closure: v2 modules add no attribute read.
    assert _signals_attrs(sources) == SIGNALS_ATTRS_READ_00C373E
    assert _signals_attrs(_require_v2()) <= SIGNALS_ATTRS_READ_00C373E

    # (c)
    model = import_module("core.sources.model")
    assert tuple(model.EVIDENCE_KEYS) == EVIDENCE_KEYS_00C373E

    # (d)
    assert _url_functions() == URL_FUNCTIONS_00C373E


def test_v2_no_text_features() -> None:
    """MV2-IN-2: no v2 module imports a text-bearing type or reads text; no endpoint added."""
    problems: list[str] = []
    for path in _require_v2():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "")] if node.level == 0 else []
            else:
                names = []
            for name in names:
                top = name.split(".")
                if top[0] == "sources" or name.startswith("core.sources"):
                    problems.append(f"{path.name}: imports {name}")
            identifiers: list[str] = []
            if isinstance(node, ast.Attribute):
                identifiers.append(node.attr)
            elif isinstance(node, ast.Name):
                identifiers.append(node.id)
            elif isinstance(node, ast.alias):
                identifiers.append(node.name)
            for ident in identifiers:
                if TEXT_WORDS.search(ident):
                    problems.append(f"{path.name}: text-bearing name {ident}")
    assert not problems, problems
    # The URL-builder set has gained no endpoint (MV2-IN-1 (d) again, by name).
    assert _url_functions() == URL_FUNCTIONS_00C373E
