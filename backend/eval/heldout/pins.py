"""Pure checks for the held-out snapshot pins (design 8.3; MV2-POP-2, MV2-POP-3).

The network script `scripts/heldout_pin.py` downloads the bytes. Everything that decides
whether those bytes are acceptable lives here, so it can be tested without a network:

- `parse_hugovk`: the PyPI top list (strict JSON, size cap, row shape, non-increasing counts).
- `parse_npm_top_js`: the one `top.js` member of `npm-high-impact`, read as text, never run.
- `verify_pins`: re-hash committed files against `pins.json`.

A shape that does not match raises `PinError`. The fix is a design amendment, not a looser parser.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, NoReturn

from eval.labels import _NAME_RE as _LABELS_NPM_NAME

MAX_BYTES = 5 * 1024 * 1024

_HUGOVK_ROW_KEYS = frozenset({"download_count", "project"})
_JS_OPEN = re.compile(r"^export const [A-Za-z_$][A-Za-z0-9_$]* = \[$")
_JS_NAME = re.compile(r"^[ \t]*'([^'\\\r\n]+)',$")
_JS_CLOSE = "]"
_SCOPED = re.compile(r"^@[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def is_valid_npm_name(name: str) -> bool:
    """True when `eval.labels` accepts `name` for an npm row (the rule the merge applies)."""
    return _LABELS_NPM_NAME.fullmatch(name) is not None


def invalid_unscoped_names(names: list[str]) -> list[str]:
    """Sorted distinct unscoped names that the labels validator rejects (excluded from the draw)."""
    return sorted({n for n in names if not n.startswith("@") and not is_valid_npm_name(n)})


class PinError(ValueError):
    """A snapshot does not have the pinned shape, or a hash does not match."""


def sha256_hex(data: bytes) -> str:
    """SHA-256 hex digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def _reject_constant(token: str) -> NoReturn:
    raise PinError(f"non-standard JSON constant {token}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise PinError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def _check_size(data: bytes, what: str) -> None:
    if len(data) > MAX_BYTES:
        raise PinError(f"{what} is {len(data)} bytes, over the {MAX_BYTES} byte cap")


def parse_hugovk(data: bytes, top_n: int) -> list[tuple[str, int]]:
    """Return the first `top_n` `(project, download_count)` rows of the hugovk file.

    The file is an object with a `rows` list of objects with exactly the keys `download_count`
    (a non-negative integer) and `project` (a non-empty string). Counts must not increase.
    """
    if top_n <= 0:
        raise PinError("top_n must be positive")
    _check_size(data, "hugovk file")
    try:
        doc = json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_no_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PinError(f"hugovk file is not strict JSON: {exc}") from exc
    if not isinstance(doc, dict):
        raise PinError("hugovk file is not a JSON object")
    rows = doc.get("rows")
    if not isinstance(rows, list):
        raise PinError("hugovk file has no `rows` list")
    if len(rows) < top_n:
        raise PinError(f"hugovk file has {len(rows)} rows, fewer than {top_n}")
    out: list[tuple[str, int]] = []
    previous: int | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _HUGOVK_ROW_KEYS:
            raise PinError(f"row {index} does not have exactly the keys download_count, project")
        project, count = row["project"], row["download_count"]
        if not isinstance(project, str) or not project:
            raise PinError(f"row {index}: project is not a non-empty string")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise PinError(f"row {index}: download_count is not a non-negative integer")
        if previous is not None and count > previous:
            raise PinError(f"row {index}: download_count increases ({previous} to {count})")
        previous = count
        if index < top_n:
            out.append((project, count))
        else:
            # Rows beyond the cut are still shape-checked; nothing more to keep.
            continue
    return out


def parse_npm_top_js(data: bytes) -> list[str]:
    """Return the names of the `top.js` member, in file order.

    Exact shape: a first line `export const <id> = [`, then one `'name',` per line, then a
    last line `]` with no semicolon, as the pinned package writes it (a single trailing newline is
    allowed; any other final line, including `];`, is rejected). Every name is returned as
    downloaded. A name starting with `@` must be a well-formed scoped name (else `PinError`);
    scoped names are kept so the caller can count them, and are excluded from the population
    later. An unscoped name that fails `is_valid_npm_name` (the labels.py rule) does not abort:
    the caller lists it with `invalid_unscoped_names` and it is excluded from the population.
    A duplicate among the other names is rejected; a repeated invalid name is not.
    """
    _check_size(data, "top.js")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PinError(f"top.js is not UTF-8: {exc}") from exc
    if "\r" in text:
        raise PinError("top.js contains a carriage return")
    if text.endswith("\n"):
        text = text[:-1]
    lines = text.split("\n")
    if len(lines) < 3:
        raise PinError("top.js has no names")
    if not _JS_OPEN.fullmatch(lines[0]):
        raise PinError("top.js first line is not `export const <id> = [`")
    if lines[-1] != _JS_CLOSE:
        raise PinError("top.js last line is not `]`")
    names: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(lines[1:-1], start=2):
        match = _JS_NAME.fullmatch(line)
        if match is None:
            raise PinError(f"top.js line {number} is not a `'name',` entry")
        name = match.group(1)
        if name.startswith("@"):
            if not _SCOPED.fullmatch(name):
                raise PinError(f"top.js line {number}: invalid npm name {name!r}")
        elif not is_valid_npm_name(name):
            names.append(name)
            continue
        if name in seen:
            raise PinError(f"top.js line {number}: duplicate name {name!r}")
        seen.add(name)
        names.append(name)
    return names


def verify_pins(pins_json: Mapping[str, Any], files: Mapping[str, bytes]) -> list[str]:
    """Re-hash committed files against `pins.json`; return problems (empty means all good).

    `pins_json["sources"]` maps a source id to an object with `file` (a key of `files`),
    `trimmed_sha256` (hex) and optionally `row_count` (int, the number of entries in the file's
    JSON list or in its `rows`). Nothing is downloaded.
    """
    sources = pins_json.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        return ["pins.json has no `sources`"]
    problems: list[str] = []
    for source_id, entry in sources.items():
        if not isinstance(entry, Mapping):
            problems.append(f"{source_id}: entry is not an object")
            continue
        file_name = entry.get("file")
        expected = entry.get("trimmed_sha256")
        if not isinstance(file_name, str) or not isinstance(expected, str):
            problems.append(f"{source_id}: needs string `file` and `trimmed_sha256`")
            continue
        if _SHA256.fullmatch(expected) is None:
            problems.append(f"{source_id}: trimmed_sha256 is not 64 lowercase hex digits")
            continue
        content = files.get(file_name)
        if content is None:
            problems.append(f"{source_id}: file {file_name} is missing")
            continue
        actual = sha256_hex(content)
        if actual != expected:
            problems.append(f"{source_id}: hash mismatch for {file_name}")
            continue
        count = entry.get("row_count")
        if count is not None:
            actual_count = _count_entries(content)
            if isinstance(count, bool) or count != actual_count:
                problems.append(f"{source_id}: row_count {count!r} but file has {actual_count}")
    return problems


def _count_entries(content: bytes) -> int | None:
    try:
        doc = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if isinstance(doc, dict):
        doc = doc.get("rows")
    return len(doc) if isinstance(doc, list) else None
