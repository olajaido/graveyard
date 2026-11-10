"""Recorded-exchange cassette types and the canonical request hash (SRC-REC-3).

This is the pure half of the record/replay machinery. It works on values that are
already parsed JSON and does no file I/O; reading and writing the cassette file is
done by the tests and by ``scripts/record_source_responses.py``.

Format (``cassette_to_obj`` / ``cassette_from_obj``)::

    {"version": 1,
     "entries": [
        {"request":  {"method": "POST", "url": "https://...", "body": <json or null>},
         "response": {"status": 200, "content_type": "application/json" | null,
                      "retry_after": "120" | null, "body": <json>}},
        ...]}

* ``method`` is stored upper-case; ``url`` is the exact URL requested.
* ``retry_after`` is the raw ``Retry-After`` header value (seconds or HTTP date), or
  ``null``; ``content_type`` is the raw ``Content-Type`` value, or ``null``.
* Bodies are parsed JSON, stored verbatim. No request header is ever stored
  (SRC-SEC-7), so there is no field for one.
* The request hash is derived, never stored: ``request_key(method, url, body)`` is the
  SHA-256 hex digest of the canonical JSON of ``{"body", "method", "url"}`` (sorted
  keys, separators ``(",", ":")``, ``ensure_ascii``, no NaN or infinity).
* Entries are sorted by ``(url, request hash)`` so file diffs are stable. Two entries
  with the same request hash are rejected.

In the dataclasses, JSON objects are held as read-only ``MappingProxyType`` views and
arrays as tuples (SRC-PURE-3); ``cassette_to_obj`` and ``thaw_json`` turn them back
into plain ``dict`` and ``list``. Malformed input raises ``ValueError`` with a fixed
message that never repeats the offending content.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from core.sources.model import JsonValue

type FrozenJson = (
    None | bool | int | float | str | tuple[FrozenJson, ...] | Mapping[str, FrozenJson]
)

CASSETTE_VERSION: Final = 1
_MAX_DEPTH: Final = 64


def freeze_json(value: object, _depth: int = 0) -> FrozenJson:
    """Return ``value`` as an immutable JSON value (mappings read-only, lists as tuples).

    Raises ``ValueError`` if ``value`` is not JSON-compatible: a non-string key, a
    non-finite float, an unsupported type, or nesting deeper than 64 levels.
    """
    if _depth > _MAX_DEPTH:
        raise ValueError("JSON value is nested too deeply")
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("JSON value holds a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJson] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object has a non-string key")
            frozen[key] = freeze_json(item, _depth + 1)
        return MappingProxyType(frozen)
    if isinstance(value, list | tuple):
        return tuple(freeze_json(item, _depth + 1) for item in value)
    raise ValueError("value is not JSON-compatible")


def thaw_json(value: FrozenJson) -> JsonValue:
    """Return a plain ``dict`` / ``list`` copy of a frozen (or plain) JSON value."""
    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [thaw_json(item) for item in value]
    return value


def request_key(method: str, url: str, body: object = None) -> str:
    """SHA-256 hex digest of the canonical JSON of the request.

    ``body`` is JSON-compatible or ``None``. The method is upper-cased. The digest does
    not depend on key order in ``body`` and differs for different bodies.
    """
    if not isinstance(method, str) or not method:
        raise ValueError("method must be a non-empty string")
    if not isinstance(url, str) or not url:
        raise ValueError("url must be a non-empty string")
    plain = thaw_json(freeze_json(body))
    canonical = json.dumps(
        {"body": plain, "method": method.upper(), "url": url},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class CassetteEntry:
    """One recorded exchange: the request identity and the response to replay."""

    method: str
    url: str
    request_body: FrozenJson
    status: int
    content_type: str | None
    retry_after: str | None
    response_body: FrozenJson
    key: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.method, str) or not self.method:
            raise ValueError("entry method must be a non-empty string")
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("entry url must be a non-empty string")
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise ValueError("entry status must be an integer")
        if not 100 <= self.status <= 599:
            raise ValueError("entry status is out of range")
        for name in ("content_type", "retry_after"):
            item = getattr(self, name)
            if item is not None and not isinstance(item, str):
                raise ValueError(f"entry {name} must be a string or null")
        object.__setattr__(self, "method", self.method.upper())
        object.__setattr__(self, "request_body", freeze_json(self.request_body))
        object.__setattr__(self, "response_body", freeze_json(self.response_body))
        object.__setattr__(self, "key", request_key(self.method, self.url, self.request_body))


@dataclass(frozen=True)
class Cassette:
    """A set of recorded exchanges, sorted by ``(url, request hash)``, hash-unique."""

    entries: tuple[CassetteEntry, ...] = ()

    def __post_init__(self) -> None:
        entries = tuple(self.entries)
        if not all(isinstance(entry, CassetteEntry) for entry in entries):
            raise ValueError("cassette entries must be CassetteEntry values")
        ordered = tuple(sorted(entries, key=lambda entry: (entry.url, entry.key)))
        if len({entry.key for entry in ordered}) != len(ordered):
            raise ValueError("cassette holds two entries with the same request")
        object.__setattr__(self, "entries", ordered)

    def index(self) -> Mapping[str, CassetteEntry]:
        """Read-only view of the entries by request hash, for order-free matching."""
        return MappingProxyType({entry.key: entry for entry in self.entries})


def cassette_to_obj(cassette: Cassette) -> dict[str, JsonValue]:
    """Convert a cassette to plain JSON-compatible dicts and lists."""
    entries: list[JsonValue] = [
        {
            "request": {
                "method": entry.method,
                "url": entry.url,
                "body": thaw_json(entry.request_body),
            },
            "response": {
                "status": entry.status,
                "content_type": entry.content_type,
                "retry_after": entry.retry_after,
                "body": thaw_json(entry.response_body),
            },
        }
        for entry in cassette.entries
    ]
    return {"version": CASSETTE_VERSION, "entries": entries}


def _exact_mapping(obj: object, keys: frozenset[str], what: str) -> Mapping[str, Any]:
    if not isinstance(obj, Mapping):
        raise ValueError(f"{what} must be an object")
    if set(obj.keys()) != keys:
        raise ValueError(f"{what} has missing or unexpected keys")
    return obj


_TOP_KEYS: Final = frozenset({"version", "entries"})
_ENTRY_KEYS: Final = frozenset({"request", "response"})
_REQUEST_KEYS: Final = frozenset({"method", "url", "body"})
_RESPONSE_KEYS: Final = frozenset({"status", "content_type", "retry_after", "body"})


def _entry_from_obj(obj: object) -> CassetteEntry:
    entry = _exact_mapping(obj, _ENTRY_KEYS, "cassette entry")
    request = _exact_mapping(entry["request"], _REQUEST_KEYS, "cassette request")
    response = _exact_mapping(entry["response"], _RESPONSE_KEYS, "cassette response")
    return CassetteEntry(
        method=request["method"],
        url=request["url"],
        request_body=request["body"],
        status=response["status"],
        content_type=response["content_type"],
        retry_after=response["retry_after"],
        response_body=response["body"],
    )


def cassette_from_obj(obj: object) -> Cassette:
    """Build a cassette from already-parsed JSON; inverse of ``cassette_to_obj``.

    Raises ``ValueError`` (with a fixed message) on any malformed shape, a wrong
    ``version``, a bad field, or duplicate requests. The input is not mutated.
    """
    top = _exact_mapping(obj, _TOP_KEYS, "cassette")
    version = top["version"]
    if isinstance(version, bool) or version != CASSETTE_VERSION:
        raise ValueError("unsupported cassette version")
    raw = top["entries"]
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise ValueError("cassette entries must be an array")
    return Cassette(entries=tuple(_entry_from_obj(item) for item in raw))
