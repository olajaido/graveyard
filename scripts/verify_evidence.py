#!/usr/bin/env python3
"""Check that every labelled row's evidence_quote appears at its evidence_url (T14 review).

For each row of ``eval/labelled_packages.csv`` this makes one read-only HTTPS GET to
``evidence_url`` and looks for ``evidence_quote`` in the response. Matching collapses every
whitespace run to one space and tries, in order: the raw body; the body with HTML tags
stripped and entities unescaped; and, for JSON bodies, every string value joined. There is
no other normalisation (no case folding, no quote-character folding).

Tag stripping is tried two ways (tags replaced by nothing, and by a space) because neither
is right for every page; both count as "tags stripped".

Per-row status: ``found``, ``not_found`` or ``fetch_error``. Two flags are raised
independently of status:

* ``amendment_1_3``: label ``alive`` and the quote is a machine timestamp.
* ``still_works_fail``: label ``finished-healthy`` and the row is not ``pass`` or
  ``pass_install_only`` in ``eval/review/still_works.tsv``.

Writes ``eval/review/evidence.tsv`` and prints a summary plus every row that is not
``found`` or has a flag. Does not read the labelled CSV for anything but its rows, writes
nothing else, and does not use Graveyard code or output.

Safety: https only; every connection (including each redirect hop) is made to an address
resolved and checked in the same step, and private, loopback, link-local and other
non-public addresses are refused.

Usage:
    python3 scripts/verify_evidence.py [--csv PATH] [--still-works PATH] [--out PATH] [--limit N]
"""

from __future__ import annotations

import argparse
import csv
import html
import http.client
import ipaddress
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO_ROOT / "eval" / "labelled_packages.csv"
DEFAULT_STILL_WORKS = REPO_ROOT / "eval" / "review" / "still_works.tsv"
DEFAULT_OUT = REPO_ROOT / "eval" / "review" / "evidence.tsv"
TIMEOUT_SECONDS = 20
HOST_DELAY_SECONDS = 1.0
MAX_BODY_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 5
USER_AGENT = "graveyard-eval-evidence-check (read-only label review; one GET per row)"

FOUND, NOT_FOUND, FETCH_ERROR = "found", "not_found", "fetch_error"
FLAG_AMENDMENT_1_3 = "amendment_1_3"
FLAG_STILL_WORKS = "still_works_fail"
STILL_WORKS_OK = frozenset({"pass", "pass_install_only"})

COLUMNS = ("ecosystem", "name", "label", "evidence_kind", "status", "flags", "detail")


# --------------------------------------------------------------------------- pure logic


def collapse_ws(text: str) -> str:
    """Collapse every whitespace run to one space and trim the ends."""
    return re.sub(r"\s+", " ", text).strip()


_TAG = re.compile(r"<[^>]*>")


def strip_html_variants(body: str) -> tuple[str, str]:
    """Body with tags removed and entities unescaped: tags -> '' and tags -> ' '."""
    return (
        html.unescape(_TAG.sub("", body)),
        html.unescape(_TAG.sub(" ", body)),
    )


def json_string_values(value: Any) -> list[str]:
    """Every string value (not key) in a decoded JSON document, depth-first."""
    out: list[str] = []
    stack: list[Any] = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))
    return out


def parse_json_body(body: str) -> Any | None:
    """Decoded JSON, or None when the body is not JSON."""
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        return None


@dataclass(frozen=True)
class MatchResult:
    found: bool
    view: str = ""  # raw | html | json


def match_quote(quote: str, body: str) -> MatchResult:
    """Look for ``quote`` in ``body`` under the three allowed views."""
    needle = collapse_ws(quote)
    if not needle:
        return MatchResult(False)
    if needle in collapse_ws(body):
        return MatchResult(True, "raw")
    for stripped in strip_html_variants(body):
        if needle in collapse_ws(stripped):
            return MatchResult(True, "html")
    decoded = parse_json_body(body)
    if decoded is not None:
        joined = " ".join(json_string_values(decoded))
        if needle in collapse_ws(joined):
            return MatchResult(True, "json")
    return MatchResult(False)


_ISO_BARE = re.compile(
    r"""^["']?\d{4}-\d{2}-\d{2}
        (?:[Tt ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:[Zz]|[+-]\d{2}:?\d{2})?)?
        ["']?$""",
    re.VERBOSE,
)
_ISO_WITH_TIME = re.compile(r"\d{2}:\d{2}")
_TS_FIELD = re.compile(
    r"""\bupload_time\w*\b | \bcreated_at\b | "time"\s*:
    | \btime\s*[:=]\s*["']?\d{4}-\d{2}-\d{2}""",
    re.VERBOSE | re.IGNORECASE,
)


def is_machine_timestamp(quote: str, *, json_body: bool = False) -> bool:
    """True if the quote is a registry or API timestamp rather than release notes.

    Matches: a quote naming ``upload_time*``, ``created_at`` or a ``time`` field; a bare ISO
    timestamp with a time-of-day; and, when the evidence is a JSON record, a bare ISO date.
    """
    q = collapse_ws(quote)
    if not q:
        return False
    if _TS_FIELD.search(q):
        return True
    if _ISO_BARE.match(q):
        return bool(_ISO_WITH_TIME.search(q)) or json_body
    return False


def amendment_1_3_flag(label: str, quote: str, *, json_body: bool = False) -> bool:
    return label == "alive" and is_machine_timestamp(quote, json_body=json_body)


def still_works_fail_flag(row: dict[str, str], results: dict[tuple[str, str, str], str]) -> str:
    """Empty string when fine; otherwise the reason a finished-healthy row fails."""
    if row["label"] != "finished-healthy":
        return ""
    key = (row["ecosystem"], row["name"], row["version"])
    result = results.get(key)
    if result is None:
        return "no still-works result"
    return "" if result in STILL_WORKS_OK else f"still-works: {result}"


def load_still_works(path: Path) -> dict[tuple[str, str, str], str]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return {(r["ecosystem"], r["name"], r["version"]): r["result"] for r in reader}


def blocked_address_reason(address: str) -> str:
    """Why an IP is refused, or '' if it is a public address."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return f"not an IP address: {address}"
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link-local"
    if ip.is_private:
        return "private"
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved:
        return "non-public"
    if not ip.is_global:
        return "non-public"
    return ""


def check_url(url: str) -> str:
    """Why a URL is refused before any DNS lookup, or '' if it is acceptable."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https":
        return "https only"
    if not parts.hostname:
        return "no host"
    if parts.username or parts.password:
        return "credentials in URL"
    return ""


def select_public_address(
    infos: Iterable[tuple[Any, ...]],
) -> tuple[str, str]:
    """Pick the first address from getaddrinfo results; refuse if ANY is non-public.

    Returns (address, ""), or ("", reason).
    """
    addresses: list[str] = []
    for info in infos:
        addr = str(info[4][0])
        reason = blocked_address_reason(addr)
        if reason:
            return "", f"{addr} is {reason}"
        addresses.append(addr)
    if not addresses:
        return "", "no addresses"
    return addresses[0], ""


def sanitize_cell(text: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", text).strip()


def build_row(
    row: dict[str, str],
    status: str,
    flags: list[str],
    detail: str,
) -> dict[str, str]:
    return {
        "ecosystem": row["ecosystem"],
        "name": row["name"],
        "label": row["label"],
        "evidence_kind": row["evidence_kind"],
        "status": status,
        "flags": ",".join(flags),
        "detail": sanitize_cell(detail),
    }


def needs_attention(out_row: dict[str, str]) -> bool:
    return out_row["status"] != FOUND or bool(out_row["flags"])


class HostThrottle:
    """Waits so that requests to the same host are at least ``delay`` seconds apart."""

    def __init__(
        self,
        delay: float = HOST_DELAY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._delay = delay
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            remaining = self._delay - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = self._clock()


# --------------------------------------------------------------------------- network


class _RefusedError(Exception):
    pass


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Resolves, checks and connects in one step so the checked IP is the one used."""

    def connect(self) -> None:
        port = self.port or 443
        infos = socket.getaddrinfo(self.host, port, type=socket.SOCK_STREAM)
        address, reason = select_public_address(infos)
        if reason:
            raise _RefusedError(f"refused address for {self.host}: {reason}")
        sock = socket.create_connection((address, port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_PinnedHTTPSConnection, req)


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        reason = check_url(newurl)
        if reason:
            raise _RefusedError(f"refused redirect to {newurl}: {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # Empty ProxyHandler: never route through an environment proxy (it would bypass the
    # address check).
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _PinnedHTTPSHandler(), _HttpsOnlyRedirect()
    )


@dataclass(frozen=True)
class FetchResult:
    body: str = ""
    error: str = ""  # non-empty means fetch_error


def _decode(raw: bytes, content_type: str) -> str:
    m = re.search(r"charset=([\w.-]+)", content_type, re.IGNORECASE)
    for enc in ([m.group(1)] if m else []) + ["utf-8"]:
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch(url: str, opener: urllib.request.OpenerDirector | None = None) -> FetchResult:
    reason = check_url(url)
    if reason:
        return FetchResult(error=f"refused: {reason}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with (opener or _opener()).open(req, timeout=TIMEOUT_SECONDS) as resp:
            raw = resp.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                return FetchResult(error="response larger than 10 MB")
            return FetchResult(body=_decode(raw, resp.headers.get("Content-Type", "")))
    except urllib.error.HTTPError as exc:
        return FetchResult(error=f"HTTP {exc.code}")
    except _RefusedError as exc:
        return FetchResult(error=str(exc))
    except urllib.error.URLError as exc:
        inner = exc.reason
        if isinstance(inner, _RefusedError):
            return FetchResult(error=str(inner))
        return FetchResult(error=f"{type(inner).__name__}: {inner}")
    except (OSError, http.client.HTTPException) as exc:
        return FetchResult(error=f"{type(exc).__name__}: {exc}")


def verify_row(
    row: dict[str, str],
    still_works: dict[tuple[str, str, str], str],
    fetcher: Callable[[str], FetchResult],
    throttle: HostThrottle,
) -> dict[str, str]:
    url = row["evidence_url"]
    host = urllib.parse.urlsplit(url).hostname or ""
    throttle.wait(host)
    result = fetcher(url)
    flags: list[str] = []
    details: list[str] = []
    if result.error:
        status = FETCH_ERROR
        details.append(result.error)
        json_body = False
    else:
        match = match_quote(row["evidence_quote"], result.body)
        status = FOUND if match.found else NOT_FOUND
        if match.found:
            details.append(f"matched in {match.view}")
        elif not collapse_ws(row["evidence_quote"]):
            details.append("empty quote")
        json_body = parse_json_body(result.body) is not None
    if amendment_1_3_flag(row["label"], row["evidence_quote"], json_body=json_body):
        flags.append(FLAG_AMENDMENT_1_3)
        details.append("quote is a machine timestamp")
    sw = still_works_fail_flag(row, still_works)
    if sw:
        flags.append(FLAG_STILL_WORKS)
        details.append(sw)
    return build_row(row, status, flags, "; ".join(details))


# --------------------------------------------------------------------------- driver


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summarise(rows: list[dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    flag_counts = {
        f: sum(1 for r in rows if f in r["flags"].split(",") if r["flags"])
        for f in (FLAG_AMENDMENT_1_3, FLAG_STILL_WORKS)
    }
    lines = [f"rows: {len(rows)}"]
    lines += [f"  {s}: {counts.get(s, 0)}" for s in (FOUND, NOT_FOUND, FETCH_ERROR)]
    lines += [f"  flag {f}: {n}" for f, n in flag_counts.items()]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--still-works", type=Path, default=DEFAULT_STILL_WORKS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="only the first N rows")
    args = parser.parse_args(argv)

    with args.csv.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if args.limit:
        rows = rows[: args.limit]
    still_works = load_still_works(args.still_works)
    if not still_works:
        print(f"warning: no still-works results at {args.still_works}", file=sys.stderr)

    throttle = HostThrottle()
    out_rows: list[dict[str, str]] = []
    for i, row in enumerate(rows, 1):
        out = verify_row(row, still_works, fetch, throttle)
        out_rows.append(out)
        print(
            f"[{i}/{len(rows)}] {out['ecosystem']}/{out['name']}: {out['status']}", file=sys.stderr
        )

    write_tsv(args.out, out_rows)
    print(summarise(out_rows))
    print(f"wrote {args.out}")
    attention = [r for r in out_rows if needs_attention(r)]
    if attention:
        print("\nrows not found or flagged:")
        for r in attention:
            print("\t".join(r[c] for c in COLUMNS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
