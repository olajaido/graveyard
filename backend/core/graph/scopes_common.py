"""Helpers shared by the four lockfile scope parsers (design §6, DG-SCP-0, DG-SCP-5).

Every parser calls ``check_size`` first, decodes with ``load_json`` or
``load_toml`` (both turn every decoder failure into ``ValueError``), collects
its warnings, and returns ``result``. Pure: no I/O, no logging.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable, Mapping
from typing import Any, Final

from core.graph.diagnostics import finalise_warnings, make_warning
from core.graph.model import (
    MAX_LOCKFILE_CHARS,
    MAX_TEXT,
    GraphWarning,
    Scope,
    ScopeResult,
    scope_map,
)

_DEEP_JSON: Final = "invalid JSON: nesting too deep"
_DEEP_TOML: Final = "invalid TOML: nesting too deep"


def check_size(text: object) -> None:
    """Raise ``ValueError`` unless ``text`` is a ``str`` within ``MAX_LOCKFILE_CHARS``."""
    if not isinstance(text, str):
        raise ValueError(f"lockfile text must be str, got {type(text).__name__}")
    if len(text) > MAX_LOCKFILE_CHARS:
        raise ValueError(f"lockfile text exceeds {MAX_LOCKFILE_CHARS} characters")


def load_json(text: str) -> Any:
    """Decode JSON. Any decoder failure, including ``RecursionError``, becomes ``ValueError``."""
    try:
        return json.loads(text)
    except RecursionError as exc:
        raise ValueError(_DEEP_JSON) from exc
    except ValueError as exc:  # JSONDecodeError and the int-digit limit are ValueErrors
        raise ValueError(f"invalid JSON: {str(exc)[:MAX_TEXT]}") from exc


def load_toml(text: str) -> dict[str, Any]:
    """Decode TOML. Any decoder failure, including ``RecursionError``, becomes ``ValueError``."""
    try:
        return tomllib.loads(text)
    except RecursionError as exc:
        raise ValueError(_DEEP_TOML) from exc
    except ValueError as exc:  # TOMLDecodeError is a ValueError
        raise ValueError(f"invalid TOML: {str(exc)[:MAX_TEXT]}") from exc


def cross_check(
    direct_scopes: Mapping[str, Scope],
    package_scopes: Mapping[str, Scope],
) -> list[GraphWarning]:
    """Return one ``SCOPE_DISAGREEMENT`` per key declared ``runtime`` but ``dev`` per package.

    Any other combination (declared ``dev``, package ``runtime``, key missing
    from ``package_scopes``) emits nothing (DG-SCP-5). Output follows sorted key order.
    """
    return [
        make_warning(
            "SCOPE_DISAGREEMENT",
            "declared runtime but the lockfile marks it dev-only (declared=runtime, package=dev)",
            None,
            (key,),
        )
        for key in sorted(direct_scopes)
        if direct_scopes[key] == "runtime" and package_scopes.get(key) == "dev"
    ]


def result(
    package_scopes: Mapping[str, Scope],
    direct_scopes: Mapping[str, Scope],
    warnings: Iterable[GraphWarning],
) -> ScopeResult:
    """Assemble a ``ScopeResult``: sorted read-only maps and finalised warnings."""
    return ScopeResult(
        package_scopes=scope_map(package_scopes),
        direct_scopes=scope_map(direct_scopes),
        warnings=finalise_warnings(warnings),
    )
