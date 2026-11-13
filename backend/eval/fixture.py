"""Captured fixtures to ``Signals`` and ``SourceWarning`` s (EV-RUN-3, EV-NOGH-1, EV-NOGH-2).

The mapping functions are pure. ``load_fixtures`` is the only reader and the only place that
raises ``FixtureError``; every message names the fixture file (relative to the fixtures root)
and never repeats file content.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Final

from core.scoring.types import Advisory, PathInfo, Signals
from core.sources.assemble import FEEDS
from core.sources.model import SourceWarning

# The scored signals: only these feed ``cli.gate.unverified_sources`` (design, fixture format).
SCORED_SIGNALS: Final = (
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s8_overall",
)

#: Host of a signal's ``source`` URL to ``SOURCE_NAMES`` member; anything else is ``internal``.
HOST_SOURCES: Final[Mapping[str, str]] = {
    "api.github.com": "github",
    "api.deps.dev": "depsdev",
    "api.securityscorecards.dev": "scorecard",
    "registry.npmjs.org": "npm_registry",
    "pypi.org": "pypi",
}

_UNAVAILABLE_DETAIL: Final = "capture-time failure recorded in the fixture"
_GITHUB_DISABLED_DETAIL: Final = "no GitHub token configured; GitHub signals unavailable"


class FixtureError(ValueError):
    """A fixture is unreadable, inconsistent with its row, or cannot be mapped (EV-RUN-3)."""


@dataclass(frozen=True)
class LoadedFixture:
    ecosystem: str
    package: str
    resolved_version: str
    as_of: date
    signals: Signals
    warnings: tuple[SourceWarning, ...]
    registry_deprecated: bool | None  # from s1_parts
    raw: Mapping[str, Any]  # for the no_github derivation


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def signals_from_fixture(fixture: Mapping[str, Any]) -> Signals:
    """Map a captured fixture to Signals (dates parsed; lists become tuples; None stays None).

    The same mapping as ``core.scoring.tests.test_anchors.signals_from_fixture``.
    """
    s = fixture["signals"]

    def v(key: str) -> Any:
        return s[key]["value"]

    raw_adv = v("s7_advisories")
    advisories = (
        None
        if raw_adv is None
        else tuple(
            Advisory(id=a["id"], has_fix=a["has_fix"], published_at=_date(a["published_at"]))
            for a in raw_adv
        )
    )
    raw_paths = fixture.get("paths")
    paths = (
        None
        if raw_paths is None
        else tuple(PathInfo(runtime=p["runtime"], direct=p["direct"]) for p in raw_paths)
    )
    return Signals(
        purl=fixture["purl"],
        as_of=date.fromisoformat(fixture["as_of"]),
        s2_latest_release_at=_date(v("s2_latest_release_at")),
        s3_last_push_at=_date(v("s3_last_push_at")),
        s4_maintained=v("s4_maintained"),
        s5_committers=v("s5_committers"),
        s6_open_issues=v("s6_open_issues"),
        s6_closed_issues=v("s6_closed_issues"),
        s8_overall=v("s8_overall"),
        s1_declared_death=v("s1_declared_death"),
        s1b_version_deprecated=v("s1b_version_deprecated"),
        s7_advisories=advisories,
        s9_weekly_downloads=v("s9_weekly_downloads"),
        paths=paths,
        services_affected=fixture.get("services_affected"),
        shared_repo=fixture.get("shared_repo", False),
    )


def _source_name(entry: Mapping[str, Any]) -> str:
    source = entry.get("source")
    if not isinstance(source, str):
        return "internal"
    # No urllib (EV-RUN-4): the host is whatever sits between "https://" and the next "/".
    prefix = "https://"
    if not source.startswith(prefix):
        return "internal"
    host = source[len(prefix) :].split("/", 1)[0].lower()
    return HOST_SOURCES.get(host, "internal")


def warnings_from_fixture(fixture: Mapping[str, Any]) -> tuple[SourceWarning, ...]:
    """One ``INTERNAL_ERROR`` warning per source with a scored signal marked ``unavailable``.

    Only the scored signals count; the marker on any other signal is ignored. A null signal
    without the marker gives nothing (nothing was skipped).
    """
    signals = fixture["signals"]
    by_source: dict[str, list[str]] = {}
    for key in SCORED_SIGNALS:
        entry = signals.get(key)
        if isinstance(entry, Mapping) and entry.get("unavailable") is True:
            by_source.setdefault(_source_name(entry), []).append(key)
    return tuple(
        SourceWarning(
            code="INTERNAL_ERROR",
            source=source,
            signals=tuple(sorted(keys)),
            detail=_UNAVAILABLE_DETAIL,
        )
        for source, keys in sorted(by_source.items())
    )


def no_github_variant(loaded: LoadedFixture) -> tuple[Signals, tuple[SourceWarning, ...]]:
    """The fixture as the CLI sees it with no GitHub token (EV-NOGH-2, SRC-GH-7).

    The GITHUB_DISABLED warning is added only when the fixture's top-level ``repo`` is not
    null: the CLI's GitHub client warns per repo target, so a package without a repository
    has nothing skipped and stays verified.
    """
    signals = dataclasses.replace(
        loaded.signals,
        s3_last_push_at=None,
        s5_committers=None,
        s6_open_issues=None,
        s6_closed_issues=None,
        s1_declared_death=True if loaded.registry_deprecated is True else None,
    )
    kept = tuple(w for w in loaded.warnings if w.source != "github")
    if loaded.raw.get("repo") is None:
        return signals, kept
    disabled = SourceWarning(
        code="GITHUB_DISABLED",
        source="github",
        signals=FEEDS["github"],
        detail=_GITHUB_DISABLED_DETAIL,
    )
    return signals, (*kept, disabled)


def _registry_deprecated(raw: Mapping[str, Any], name: str) -> bool | None:
    parts = raw.get("s1_parts")
    if not isinstance(parts, Mapping):
        raise FixtureError(f"{name}: missing s1_parts")
    entries = [parts.get("registry_deprecated"), parts.get("repo_archived")]
    if not all(isinstance(e, Mapping) and "value" in e for e in entries):
        raise FixtureError(f"{name}: s1_parts needs registry_deprecated and repo_archived")
    value = entries[0]["value"] if entries[0] is not None else None
    if value is not None and not isinstance(value, bool):
        raise FixtureError(f"{name}: s1_parts.registry_deprecated must be true, false or null")
    return value


def _read(path: Path, name: str) -> Mapping[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FixtureError(f"{name}: unreadable or invalid JSON ({type(exc).__name__})") from None
    if not isinstance(data, dict):
        raise FixtureError(f"{name}: fixture must be a JSON object")
    return data


def _load_one(path: Path, name: str, key: tuple[str, str], version: str | None) -> LoadedFixture:
    raw = _read(path, name)
    ecosystem, package = key
    for field, expected in (("ecosystem", ecosystem), ("package", package)):
        if raw.get(field) != expected:
            raise FixtureError(f"{name}: {field} does not match the row")
    resolved = raw.get("resolved_version")
    if not isinstance(resolved, str) or (version is not None and resolved != version):
        raise FixtureError(f"{name}: resolved_version does not match the row")
    registry_deprecated = _registry_deprecated(raw, name)
    try:
        signals = signals_from_fixture(raw)
        warnings = warnings_from_fixture(raw)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise FixtureError(f"{name}: cannot be mapped to Signals ({type(exc).__name__})") from None
    return LoadedFixture(
        ecosystem=ecosystem,
        package=package,
        resolved_version=resolved,
        as_of=signals.as_of,
        signals=signals,
        warnings=warnings,
        registry_deprecated=registry_deprecated,
        raw=raw,
    )


def load_fixtures(
    root: Path, keys: Collection[tuple[str, str]]
) -> dict[tuple[str, str], LoadedFixture]:
    """Load ``root/<ecosystem>/<name>.json`` for every ``(ecosystem, name)`` in ``keys``.

    ``keys`` may be a mapping from key to the row's version; then ``resolved_version`` is
    checked against it (EV-RUN-3). Raises ``FixtureError`` for a missing file, an orphan file,
    an identity mismatch, a missing ``s1_parts``, more than one ``as_of`` or an unmappable
    fixture. The result does not depend on the order of ``keys``.
    """
    versions: Mapping[tuple[str, str], str] = keys if isinstance(keys, Mapping) else {}
    wanted = set(keys)
    root_resolved = root.resolve()
    on_disk = {
        (
            path.relative_to(root).parts[0],
            "/".join(path.relative_to(root).parts[1:])[: -len(".json")],
        )
        for path in root.rglob("*.json")
        if len(path.relative_to(root).parts) >= 2
    }
    for ecosystem, package in sorted(on_disk - wanted):
        raise FixtureError(f"{ecosystem}/{package}.json: no row for this fixture")
    loaded: dict[tuple[str, str], LoadedFixture] = {}
    for key in sorted(wanted):
        ecosystem, package = key
        path = root / ecosystem / f"{package}.json"
        name = f"{ecosystem}/{package}.json"
        if not path.resolve().is_relative_to(root_resolved):
            raise FixtureError(f"{name}: path leaves the fixtures folder")
        if not path.is_file():
            raise FixtureError(f"{name}: no fixture for this row")
        loaded[key] = _load_one(path, name, key, versions.get(key))
    as_ofs = {fx.as_of for fx in loaded.values()}
    if len(as_ofs) > 1:
        first = next(k for k in sorted(loaded) if loaded[k].as_of != min(as_ofs))
        raise FixtureError(
            f"{first[0]}/{first[1]}.json: fixtures do not share one as_of "
            f"({len(as_ofs)} different values)"
        )
    return loaded
