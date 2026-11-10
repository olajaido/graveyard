"""Pure half of the autopsy source clients (spec ``autopsy-sources``).

Purpose: everything needed to turn raw responses from deps.dev, OSV, the npm
registry, PyPI, npm downloads, pypistats, the Scorecard API and GitHub GraphQL
into a ``Signals`` value plus per-signal evidence, without doing any I/O. It
holds URL builders, response parsers, ``has_fix`` from OSV affected ranges,
the repository resolution rules, signal assembly, the "could this be Resting"
predicate, and the config and result types.

This package is pure: no network, files, environment, logging, clock or
randomness. Callers pass in the secrets, contact strings and timestamps. The
I/O half lives in ``backend/sources/``, which imports this package. An ``ast``
purity test guards this rule.

D1, two packages: this is the pure half; the async gateway, the per-source
clients, the cache and the session are the I/O half in ``sources``. Only
``resting.py`` may import ``core.scoring`` beyond ``core.scoring.types``.

D3, never raise: source, network and data problems never raise. Every parser
returns ``None`` or a value for any ``object``, and every fetch outcome is a
value (``Ok``, ``NotFound`` or ``Failed``). ``ValueError`` is for programmer
errors only.

D4, missing is ``None``: an absent signal is ``None``, never ``0`` and never a
guess. A 404 is a definitive absence (a note on the evidence, no warning). A
failure is a warning, and failures are not cached.

D5, three-valued logic: S1 and S1b use Kleene logic. ``s1`` is the OR of its
parts and ``s1b`` is ``resolved_deprecated AND NOT latest_deprecated``. ``True``
wins, ``False`` needs every applicable part known to be ``False``, and
anything else is ``None``.

D11, untrusted text: response bodies are never copied into evidence, notes or
warnings. Only parsed, validated scalar fields and fixed message templates
are.
"""

from core.sources.clock import Clock
from core.sources.config import (
    CachePolicy,
    HostPolicy,
    Limits,
    RetryPolicy,
    SourcesConfig,
    Timeouts,
)
from core.sources.model import (
    EVIDENCE_KEYS,
    ITEM_ERROR_CODES,
    REPO_VIA_VALUES,
    SOURCE_NAMES,
    WARNING_CODES,
    BatchResult,
    Evidence,
    ItemError,
    JsonValue,
    SourceResult,
    SourceStats,
    SourceWarning,
)
from core.sources.repo_resolve import RepoVia
from core.sources.secret import SecretToken, redact

__all__ = [
    "EVIDENCE_KEYS",
    "ITEM_ERROR_CODES",
    "REPO_VIA_VALUES",
    "SOURCE_NAMES",
    "WARNING_CODES",
    "BatchResult",
    "CachePolicy",
    "Clock",
    "Evidence",
    "HostPolicy",
    "ItemError",
    "JsonValue",
    "Limits",
    "RepoVia",
    "RetryPolicy",
    "SecretToken",
    "SourceResult",
    "SourceStats",
    "SourceWarning",
    "SourcesConfig",
    "Timeouts",
    "redact",
]
