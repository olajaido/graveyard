"""RFC 9457 problem+json and JSON output (SB-API-6). Details are fixed text, never user input."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Final

PROBLEM_TYPE: Final = "about:blank"
_TITLES: Final = {
    400: "Bad request",
    404: "Not found",
    413: "Payload too large",
    429: "Too many requests",
    500: "Internal error",
    503: "Service unavailable",
}


def _default(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(type(value).__name__)


def dumps(value: Any) -> str:
    return json.dumps(value, default=_default, separators=(",", ":"), allow_nan=False)


def respond(status: int, body: Any, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "no-store",
            **(headers or {}),
        },
        "body": dumps(body),
    }


def problem(status: int, detail: str) -> dict[str, Any]:
    body = {
        "type": PROBLEM_TYPE,
        "title": _TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
    }
    return {
        "statusCode": status,
        "headers": {"content-type": "application/problem+json", "cache-control": "no-store"},
        "body": dumps(body),
    }
