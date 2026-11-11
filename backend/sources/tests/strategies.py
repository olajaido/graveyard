"""Hypothesis strategies for the session-level tests (T10.4; design §12).

Every strategy draws seeds and small choices, never large structures: a ``PackageSet`` is a
``(seed, size)`` pair that ``fakeweb`` expands, a ``RequestBatch`` is a list of item *kinds*
that is resolved against a web only when a test calls ``requests(web)``, and a ``FaultPlan`` is
a list of ``(position, Fault)`` picks that is resolved against the request keys of a clean run.
Examples are therefore cheap to draw, shrink well, and print readably.

* ``faults()`` / ``fault_plans()``: plans for ``transports.fault_transport``. A plan is keyed by
  request key, which depends on the web. ``FaultPlan.resolve(keys)`` maps each pick to one of
  the given keys (taken in sorted order), so a test runs the clean web first, takes
  ``web.request_keys``, and passes ``plan.resolve(keys)`` to ``fault_transport``. The result
  does not depend on scheduling. ``oversize`` faults are excluded by default: they build
  megabyte bodies, and the gateway tests already cover them.
* ``package_sets()``: ``PackageSet(seed, size)``; ``.web(...)`` builds the ``FakeWeb``.
* ``request_batches()``: ``RequestBatch`` with valid and invalid purls, non-``str`` purls,
  ``datetime`` and other bad ``as_of`` values, versionless purls, duplicates, respelled
  duplicates and mixed ``as_of`` dates. ``requests(web)`` gives the ``(purl, as_of)`` inputs and
  ``expected_errors()`` the ``ItemError`` code each one must get (``None`` for a valid item).
* ``cache_ops()``: sequences of ``put`` / ``get`` / ``advance`` / eviction-pressure operations
  for a ``MemoryCache``; ``run_cache_ops`` plays them and returns what the gets saw.

Hypothesis profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py``; nothing
here sets ``max_examples``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final, Literal, get_args

from hypothesis import strategies as st

from core.sources.model import JsonValue
from sources.cache import MemoryCache
from sources.tests.clock import FakeClock
from sources.tests.fakeweb import FakeWeb, fakeweb
from sources.tests.transports import ALWAYS, Fault, FaultKind

# ---------------------------------------------------------------------- faults

FAST_FAULT_KINDS: Final[tuple[FaultKind, ...]] = tuple(
    kind for kind in get_args(FaultKind) if kind not in ("oversize", "wrong_one_leaf")
)
"""Every fault kind except ``oversize`` (slow) and ``wrong_one_leaf`` (targeted: the dedicated
single-leaf properties of ``test_properties_session`` use it on chosen hosts)."""

_STATUSES: Final = (404, 429, 500, 502, 503, 504, 401, 403)
_RETRY_AFTER: Final = (None, "1", "0", "5", "120", "Wed, 21 Oct 2026 07:28:00 GMT", "soon")
_REDIRECT_STATUSES: Final = (301, 302, 307, 308)
_LOCATIONS: Final = ("https://example.com/elsewhere", "https://api.github.com/graphql", "/next")
_OVERSIZE_BYTES: Final = 1_100_000  # above the 1 MiB cap of the downloads hosts


@st.composite
def faults(draw: st.DrawFn, kinds: Sequence[FaultKind] = FAST_FAULT_KINDS) -> Fault:
    """One ``Fault`` of a kind in ``kinds``, applied once, twice or on every attempt."""
    kind = draw(st.sampled_from(tuple(kinds)))
    times = draw(st.sampled_from((1, 1, 2, ALWAYS)))
    if kind == "status":
        return Fault(
            kind,
            times,
            status=draw(st.sampled_from(_STATUSES)),
            retry_after=draw(st.sampled_from(_RETRY_AFTER)),
        )
    if kind == "redirect":
        return Fault(
            kind,
            times,
            status=draw(st.sampled_from(_REDIRECT_STATUSES)),
            location=draw(st.sampled_from(_LOCATIONS)),
        )
    if kind == "oversize":
        return Fault(kind, times, size=_OVERSIZE_BYTES, chunked=draw(st.booleans()))
    if kind == "wrong_one_leaf":
        return Fault(kind, times, leaf=draw(st.integers(0, 10_000)))
    return Fault(kind, times)


@dataclass(frozen=True)
class FaultPlan:
    """Abstract faults: ``(position, fault)`` picks, resolved against concrete request keys."""

    picks: tuple[tuple[int, Fault], ...]

    def resolve(self, keys: Iterable[str]) -> dict[str, Fault]:
        """Map each pick to ``sorted(set(keys))[position % n]``. Empty keys give an empty plan.

        A later pick that lands on the same key replaces the earlier one.
        """
        ordered = sorted(set(keys))
        if not ordered:
            return {}
        return {ordered[position % len(ordered)]: fault for position, fault in self.picks}


def fault_plans(
    max_faults: int = 10, kinds: Sequence[FaultKind] = FAST_FAULT_KINDS
) -> st.SearchStrategy[FaultPlan]:
    """Plans of up to ``max_faults`` faults (an empty plan is the clean run)."""
    pick = st.tuples(st.integers(0, 10_000), faults(kinds))
    return st.builds(FaultPlan, picks=st.lists(pick, max_size=max_faults).map(tuple))


# --------------------------------------------------------------- package sets


@dataclass(frozen=True)
class PackageSet:
    """A reproducible set of packages: the arguments of ``fakeweb`` that decide the world."""

    seed: int
    size: int

    def web(
        self,
        *,
        malformed: bool = False,
        adversarial_token: str | None = None,
        hostile_errors: bool = False,
        as_of: date | None = None,
    ) -> FakeWeb:
        """A fresh ``FakeWeb`` (empty logs) for this set."""
        if as_of is None:
            return fakeweb(
                self.seed,
                packages=self.size,
                malformed=malformed,
                adversarial_token=adversarial_token,
                hostile_errors=hostile_errors,
            )
        return fakeweb(
            self.seed,
            packages=self.size,
            as_of=as_of,
            malformed=malformed,
            adversarial_token=adversarial_token,
            hostile_errors=hostile_errors,
        )


def package_sets(min_size: int = 1, max_size: int = 6) -> st.SearchStrategy[PackageSet]:
    """``PackageSet`` values: a seed and between ``min_size`` and ``max_size`` projects."""
    return st.builds(
        PackageSet, seed=st.integers(0, 2**31 - 1), size=st.integers(min_size, max_size)
    )


# -------------------------------------------------------------- request batches

ItemKind = Literal[
    "valid",
    "valid_other_date",
    "duplicate",
    "respelled",
    "invalid_purl",
    "versionless",
    "non_str",
    "datetime_as_of",
    "bad_as_of",
]
ITEM_KINDS: Final[tuple[ItemKind, ...]] = (
    "valid",
    "valid_other_date",
    "duplicate",
    "respelled",
    "invalid_purl",
    "versionless",
    "non_str",
    "datetime_as_of",
    "bad_as_of",
)

INVALID_PURLS: Final[tuple[str, ...]] = (
    "",
    " ",
    "not a purl",
    "pkg:",
    "pkg:npm/",
    "pkg:npm/@1.0.0",
    "pkg:maven/org.apache/commons@1.0",
    "pkg:pypi/bad name@1.0.0",
    "pkg:pypi/@1.0.0",
    "npm/left-pad@1.0.0",
    "pkg:npm/left-pad@1.0.0 ",
    "pkg:npm/left-pad@",
    "pkg:npm/%zz@1.0.0",
    "pkg:" + "a" * 3000,
)
"""Strings that ``parse_purl`` rejects (checked by ``test_fakeweb``)."""

_NON_STR: Final[tuple[Any, ...]] = (
    None,
    0,
    1.5,
    True,
    b"pkg:npm/x@1.0.0",
    ["pkg:npm/x@1.0.0"],
    {"purl": "pkg:npm/x@1.0.0"},
    ("pkg:npm/x@1.0.0",),
)
_BAD_AS_OF: Final[tuple[Any, ...]] = ("2026-11-03", 20261103, None, 1.5, True, [], (2026, 11, 3))
_DATETIMES: Final[tuple[datetime, ...]] = (
    datetime(2026, 11, 3, tzinfo=UTC),
    datetime(2026, 11, 3, 12, 30),
    datetime(2020, 1, 1, tzinfo=UTC),
)
_ERROR_OF: Final[dict[str, str]] = {
    "invalid_purl": "INVALID_PURL",
    "non_str": "INVALID_PURL",
    "versionless": "MISSING_VERSION",
    "datetime_as_of": "INVALID_AS_OF",
    "bad_as_of": "INVALID_AS_OF",
}


@dataclass(frozen=True)
class ItemSpec:
    """One input described by kind; ``RequestBatch.requests`` turns it into a real input.

    ``index`` picks one of the web's purls (modulo their number) or, for ``duplicate``, an
    earlier input (modulo the number so far). ``days`` is how far before the web's ``as_of`` a
    ``valid_other_date`` item is. ``text`` is the ``invalid_purl`` string. ``variant`` picks one
    of the odd values for ``non_str``, ``datetime_as_of`` and ``bad_as_of``.
    """

    kind: ItemKind
    index: int = 0
    days: int = 1
    text: str = ""
    variant: int = 0


def _respell(purl: str) -> str:
    """The same package, spelled differently: upper-case type, and for PyPI an upper-case name
    with underscores."""
    head, _, rest = purl.partition("/")
    ecosystem = head.removeprefix("pkg:")
    if ecosystem == "pypi":
        name, at, version = rest.partition("@")
        rest = name.upper().replace("-", "_") + at + version
    return f"pkg:{ecosystem.upper()}/{rest}"


@dataclass(frozen=True)
class RequestBatch:
    """A package set and a list of item specs to run against its web."""

    package_set: PackageSet
    items: tuple[ItemSpec, ...]

    def resolve(self, web: FakeWeb) -> list[tuple[tuple[Any, Any], str | None]]:
        """``[(input, expected ItemError code or None)]`` for ``web``, one per item."""
        out: list[tuple[tuple[Any, Any], str | None]] = []
        purls = web.purls
        for spec in self.items:
            base = purls[spec.index % len(purls)]
            item: tuple[Any, Any]
            error = _ERROR_OF.get(spec.kind)
            if spec.kind == "duplicate" and out:
                item, error = out[spec.index % len(out)]
                item = copy.deepcopy(item)
            elif spec.kind == "valid_other_date":
                item = (base, web.as_of - timedelta(days=spec.days))
            elif spec.kind == "respelled":
                item = (_respell(base), web.as_of)
            elif spec.kind == "invalid_purl":
                item = (spec.text, web.as_of)
            elif spec.kind == "versionless":
                item = (base.rsplit("@", 1)[0], web.as_of)
            elif spec.kind == "non_str":
                item = (copy.deepcopy(_NON_STR[spec.variant % len(_NON_STR)]), web.as_of)
            elif spec.kind == "datetime_as_of":
                item = (base, _DATETIMES[spec.variant % len(_DATETIMES)])
            elif spec.kind == "bad_as_of":
                item = (base, copy.deepcopy(_BAD_AS_OF[spec.variant % len(_BAD_AS_OF)]))
            else:  # "valid", and a "duplicate" with nothing before it
                item = (base, web.as_of)
            out.append((item, error))
        return out

    def requests(self, web: FakeWeb) -> list[tuple[Any, Any]]:
        """The inputs to pass to ``collect`` (``Any`` because some are invalid on purpose)."""
        return [item for item, _ in self.resolve(web)]

    def expected_errors(self, web: FakeWeb) -> list[str | None]:
        """The ``ItemError`` code each input must get, or ``None`` for a valid input."""
        return [error for _, error in self.resolve(web)]


def invalid_purl_texts() -> st.SearchStrategy[str]:
    """Strings that are not purls: a fixed pool and arbitrary text without a ``pkg:`` prefix."""
    return st.one_of(
        st.sampled_from(INVALID_PURLS),
        st.text(max_size=30).filter(lambda text: not text.lower().startswith("pkg:")),
    )


def item_specs() -> st.SearchStrategy[ItemSpec]:
    """Item specs, with valid items about as common as the invalid kinds together."""
    kinds = st.sampled_from(
        (
            "valid",
            "valid",
            "valid",
            "valid",
            "valid_other_date",
            "duplicate",
            "respelled",
            "invalid_purl",
            "versionless",
            "non_str",
            "datetime_as_of",
            "bad_as_of",
        )
    )
    return st.builds(
        ItemSpec,
        kind=kinds,
        index=st.integers(0, 50),
        days=st.integers(1, 400),
        text=invalid_purl_texts(),
        variant=st.integers(0, 7),
    )


def request_batches(
    max_items: int = 12, package_set: st.SearchStrategy[PackageSet] | None = None
) -> st.SearchStrategy[RequestBatch]:
    """Batches of up to ``max_items`` inputs (possibly none) over a package set."""
    return st.builds(
        RequestBatch,
        package_set=package_set if package_set is not None else package_sets(),
        items=st.lists(item_specs(), max_size=max_items).map(tuple),
    )


# ------------------------------------------------------------------ cache ops

CACHE_KEYS: Final = ("a", "b", "c", "d", "e")


@dataclass(frozen=True)
class CachePut:
    key: str
    value: JsonValue
    ttl: int


@dataclass(frozen=True)
class CacheGet:
    key: str


@dataclass(frozen=True)
class CacheAdvance:
    seconds: int


@dataclass(frozen=True)
class CachePressure:
    """``count`` puts of fresh keys, to push entries out of a small cache."""

    count: int
    ttl: int


type CacheOp = CachePut | CacheGet | CacheAdvance | CachePressure


def cache_ops(max_ops: int = 30) -> st.SearchStrategy[list[CacheOp]]:
    """Sequences of cache operations over a handful of keys, small values and small TTLs."""
    ttl = st.integers(1, 5)
    value = st.one_of(
        st.integers(0, 9), st.text(max_size=4), st.lists(st.integers(0, 9), max_size=3)
    )
    op: st.SearchStrategy[CacheOp] = st.one_of(
        st.builds(CachePut, key=st.sampled_from(CACHE_KEYS), value=value, ttl=ttl),
        st.builds(CacheGet, key=st.sampled_from(CACHE_KEYS)),
        st.builds(CacheAdvance, seconds=st.integers(0, 6)),
        st.builds(CachePressure, count=st.integers(1, 8), ttl=ttl),
    )
    return st.lists(op, max_size=max_ops)


async def run_cache_ops(
    cache: MemoryCache, clock: FakeClock, ops: Iterable[CacheOp]
) -> list[JsonValue | None]:
    """Play ``ops`` on ``cache``; return the value each ``CacheGet`` saw (``None`` on a miss)."""
    seen: list[JsonValue | None] = []
    fresh = 0
    for op in ops:
        if isinstance(op, CachePut):
            await cache.put(op.key, op.value, ttl_seconds=op.ttl)
        elif isinstance(op, CacheAdvance):
            clock.advance(op.seconds)
        elif isinstance(op, CachePressure):
            for _ in range(op.count):
                fresh += 1
                await cache.put(f"fresh{fresh}", fresh, ttl_seconds=op.ttl)
        else:
            entry = await cache.get(op.key)
            seen.append(None if entry is None else entry.value)
    return seen
