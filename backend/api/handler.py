"""The Lambda entry point: route by ``routeKey``; no unexpected exception leaves as a 500 body."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from api.problem import problem
from api.routes import HANDLERS, ApiDeps

log = logging.getLogger("graveyard")


def dispatch(event: Mapping[str, Any], deps: ApiDeps) -> dict[str, Any]:
    route = HANDLERS.get(str(event.get("routeKey")))
    if route is None:
        return problem(404, "No such route.")
    try:
        return route(event, deps)
    except Exception as exc:
        log.error("route failed: %s", type(exc).__name__)  # class name only: no body, no token
        return problem(500, "The request failed because of an internal error.")


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from api import runtime

    return dispatch(event, runtime.deps())
