"""Repo and ref validation (SB-VAL-1, SB-VAL-2). The one place that decides what a repo name is.

Only ``owner/name`` is accepted; the server builds every GitHub URL from the parts (T2, SSRF).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from core.scan.errors import INVALID_INPUT

_OWNER: Final = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
_NAME: Final = re.compile(r"[A-Za-z0-9._-]{1,100}")
_REF: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")


@dataclass(frozen=True)
class Repo:
    owner: str
    name: str

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


def parse_repo(text: object) -> Repo:
    """``owner/name`` to a ``Repo``. Raises ``INVALID_INPUT`` for anything else."""
    if not isinstance(text, str) or text.count("/") != 1:
        raise INVALID_INPUT
    owner, name = text.split("/")
    if _OWNER.fullmatch(owner) is None or _NAME.fullmatch(name) is None or name in {".", ".."}:
        raise INVALID_INPUT
    return Repo(owner, name)


def parse_ref(text: object) -> str:
    """A branch, tag or commit name. Raises ``INVALID_INPUT`` for anything else."""
    if (
        not isinstance(text, str)
        or _REF.fullmatch(text) is None
        or ".." in text
        or "//" in text
        or text.endswith(("/", ".lock"))
    ):
        raise INVALID_INPUT
    return text
