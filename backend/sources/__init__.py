"""I/O half of the autopsy source clients (spec ``autopsy-sources``).

Purpose: fetch the raw responses that ``core.sources`` knows how to parse. It
holds the async ``httpx`` gateway (per-host concurrency limits, rate limiting,
``Retry-After`` and exponential backoff), the per-source clients (deps.dev,
OSV, npm registry, PyPI, npm downloads, pypistats, Scorecard API, GitHub
GraphQL), the cache protocol with an in-memory implementation, the session,
and the public entry points ``autopsy_async`` and ``autopsy``.

This package imports ``core.sources``, never ``core.scoring``. It holds no
scoring logic and no response parsing rules; those live in the pure half. It
does not read environment variables, log or print. Secrets, contact strings
and tokens are passed in by the caller.

D1, two packages: this is the I/O half; the URL builders, parsers,
``has_fix``, repository resolution and signal assembly are the pure half in
``core.sources``.

D3, never raise: source, network and data problems never raise. Every fetch
returns an outcome value (``Ok``, ``NotFound`` or ``Failed``). A failure in
one source or package never fails the batch. ``ValueError`` is for programmer
errors only, and ``asyncio.CancelledError`` is never swallowed.

D4, missing is ``None``: an absent signal is ``None``, never ``0`` and never a
guess. A 404 is a definitive absence (a note on the evidence, no warning). A
failure is a warning, and failures are not cached.

D5, three-valued logic: S1 and S1b use Kleene logic (``True`` wins, ``False``
needs every applicable part known to be ``False``, otherwise ``None``), so a
failed source can turn a signal into ``None`` but never into a different
known value.

D11, untrusted text: response bodies are never copied into evidence, notes or
warnings. Only parsed, validated scalar fields and fixed message templates
are.
"""

from sources.api import autopsy, autopsy_async
from sources.cache import MemoryCache, SourceCache
from sources.clock import SystemClock
from sources.session import SourceSession

__all__ = [
    "MemoryCache",
    "SourceCache",
    "SourceSession",
    "SystemClock",
    "autopsy",
    "autopsy_async",
]
