"""Limits and flags from SSM (SB-CFG-1). ``get`` reads one parameter below ``/graveyard/<env>/``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from exhume.select import Limits

type Getter = Callable[[str], str]

_DEFAULT_MAX_PURLS: Final = 2000


@dataclass(frozen=True)
class ScanLimits:
    select: Limits
    max_purls: int


def _int(get: Getter, name: str) -> int:
    value = int(get(name))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def load_limits(get: Getter) -> ScanLimits:
    return ScanLimits(
        select=Limits(
            max_services=_int(get, "limits/max-services"),
            max_manifest_bytes=_int(get, "limits/max-manifest-bytes"),
            max_file_bytes=_int(get, "limits/max-file-bytes"),
        ),
        max_purls=_int(get, "limits/max-purls"),
    )


def kill_switch_on(get: Getter) -> bool:
    """True only for the exact value ``true``. A read error is the caller's to handle."""
    return get("kill-switch").strip().lower() == "true"
