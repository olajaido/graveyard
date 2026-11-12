"""The pure choice of a package's latest version (SRC-LAT-1; shared by KPW-RES-2).

A usable registry version (valid per ``is_valid_version``) wins. Otherwise the deps.dev
default version, if usable. Otherwise ``(None, None)``. Whether the deps.dev document may be
asked at all (not after a registry 404, SRC-LAT-3) is the caller's decision.

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from typing import Literal

from core.sources.facts import is_valid_version

type Latest = Literal["registry", "depsdev"]


def pick_latest(
    registry_latest: object, depsdev_default: object
) -> tuple[str | None, Latest | None]:
    """Return ``(version, via)``; ``(None, None)`` when neither candidate is usable."""
    if isinstance(registry_latest, str) and is_valid_version(registry_latest):
        return registry_latest, "registry"
    if isinstance(depsdev_default, str) and is_valid_version(depsdev_default):
        return depsdev_default, "depsdev"
    return None, None
