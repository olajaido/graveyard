"""The release gate (EV-GATE-1 to EV-GATE-4, EV-RUN-5).

Pure except the two file readers, ``load_gate_config`` and ``frozen_weights_ok``. No
environment, no clock, no printing. Only as-captured, reviewed outcomes reach
``evaluate_gate``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import yaml

from eval.metrics import Ratio, confusion, fh_false_positive_rate, precision
from eval.outcome import Outcome

CheckName = Literal[
    "sample_dead", "sample_finished_healthy", "dead_precision", "finished_healthy_fpr"
]

_RATE_KEYS: Final = ("min_dead_precision", "max_finished_healthy_fpr")
_COUNT_KEYS: Final = ("min_reviewed_dead", "min_reviewed_finished_healthy")
_KEYS: Final = frozenset(_RATE_KEYS + _COUNT_KEYS)


class GateConfigError(ValueError):
    """``gate.yaml`` is unreadable, malformed or out of range."""


@dataclass(frozen=True)
class GateConfig:
    min_dead_precision: float
    max_finished_healthy_fpr: float
    min_reviewed_dead: int
    min_reviewed_finished_healthy: int


@dataclass(frozen=True)
class GateCheck:
    name: CheckName
    passed: bool
    value: float | None
    threshold: float
    num: int | None
    den: int | None
    reason: str  # "ok", "below/above threshold", "undefined (...)", "insufficient sample"


@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: tuple[GateCheck, ...]


def load_gate_config(path: Path) -> GateConfig:
    """Read and validate ``gate.yaml``; any problem raises ``GateConfigError``."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise GateConfigError(f"{path}: cannot read gate config: {exc}") from exc
    if not isinstance(data, dict):
        raise GateConfigError(f"{path}: gate config must be a mapping of keys to numbers")
    for key in data:
        if key not in _KEYS:
            raise GateConfigError(f"{path}: unknown key {key!r}")
    for key in sorted(_KEYS):
        if key not in data:
            raise GateConfigError(f"{path}: missing key {key!r}")

    rates: dict[str, float] = {}
    for key in _RATE_KEYS:
        raw = data[key]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise GateConfigError(f"{path}: {key!r} must be a number")
        if not 0.0 <= raw <= 1.0:  # also rejects nan
            raise GateConfigError(f"{path}: {key!r} must be within [0, 1]")
        rates[key] = float(raw)

    counts: dict[str, int] = {}
    for key in _COUNT_KEYS:
        raw = data[key]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise GateConfigError(f"{path}: {key!r} must be an integer")
        if raw < 0:
            raise GateConfigError(f"{path}: {key!r} must not be negative")
        counts[key] = raw

    return GateConfig(
        min_dead_precision=rates["min_dead_precision"],
        max_finished_healthy_fpr=rates["max_finished_healthy_fpr"],
        min_reviewed_dead=counts["min_reviewed_dead"],
        min_reviewed_finished_healthy=counts["min_reviewed_finished_healthy"],
    )


def _sample_check(name: CheckName, count: int, minimum: int) -> GateCheck:
    ok = count >= minimum
    return GateCheck(
        name=name,
        passed=ok,
        value=float(count),
        threshold=float(minimum),
        num=count,
        den=None,
        reason="ok" if ok else "insufficient sample",
    )


def _rate_check(
    name: CheckName,
    ratio: Ratio | None,
    threshold: float,
    *,
    floor: bool,
    undefined: str,
) -> GateCheck:
    if ratio is None:
        return GateCheck(name, False, None, threshold, None, None, undefined)
    value = ratio.value
    ok = value >= threshold if floor else value <= threshold
    reason = "ok" if ok else ("below threshold" if floor else "above threshold")
    return GateCheck(name, ok, value, threshold, ratio.num, ratio.den, reason)


def evaluate_gate(reviewed: Sequence[Outcome], cfg: GateConfig) -> GateResult:
    """Evaluate the four checks over the reviewed as-captured outcomes."""
    c = confusion(reviewed)
    true_dead = sum(c["dead"].values())
    true_fh = sum(c["finished-healthy"].values())
    checks = (
        _sample_check("sample_dead", true_dead, cfg.min_reviewed_dead),
        _sample_check("sample_finished_healthy", true_fh, cfg.min_reviewed_finished_healthy),
        _rate_check(
            "dead_precision",
            precision(c, "dead"),
            cfg.min_dead_precision,
            floor=True,
            undefined="undefined (no Dead predictions)",
        ),
        _rate_check(
            "finished_healthy_fpr",
            fh_false_positive_rate(c),
            cfg.max_finished_healthy_fpr,
            floor=False,
            undefined="undefined (no finished-healthy rows)",
        ),
    )
    return GateResult(passed=all(k.passed for k in checks), checks=checks)


def frozen_weights_ok(weights_path: Path, frozen_path: Path) -> bool:
    """True when the SHA-256 of the weights file equals the digest in the frozen file."""
    try:
        actual = hashlib.sha256(weights_path.read_bytes()).hexdigest()
        expected = frozen_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return False
    return actual == expected
