"""Pure parsing of install commands for the ``kiro-power`` spec (KPW-PARSE-*, KPW-PAY-3).

No I/O, clock, environment, subprocess or logging. ``parse_install`` is the entry
point; the types, the payload extractor and the segment splitter are exported too.
"""

from core.install.model import (
    Latest,
    ParseResult,
    Pinned,
    Range,
    RequirementRef,
    Spec,
    Target,
)
from core.install.parse import parse_install
from core.install.payload import COMMAND_FIELD, CWD_FIELD, HookPayload, extract_payload
from core.install.segments import split

__all__ = [
    "COMMAND_FIELD",
    "CWD_FIELD",
    "HookPayload",
    "Latest",
    "ParseResult",
    "Pinned",
    "Range",
    "RequirementRef",
    "Spec",
    "Target",
    "extract_payload",
    "parse_install",
    "split",
]
