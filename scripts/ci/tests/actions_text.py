"""A line-based reader for composite actions and workflows: enough for these files, no YAML library.

It reads steps written in the repository's own style: a list item at a fixed indent, keys one level in, and
`run: |` blocks. It is deliberately strict: a file it cannot read fails the tests instead of being skipped.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parents[3]
ACTIONS = REPO / ".github" / "actions"


class Step(dict):
    """name, id, uses, if, shell, run, env (dict), with (dict)."""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _unquote(value: str) -> str:
    """Remove one pair of matching outer quotes, and nothing else (a command may end in a quote of its own)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'" and value.count(value[0]) == 2:
        return value[1:-1]
    return value


def parse_map(lines: List[str], base: int) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _indent(line) == base:
            m = re.match(r"\s*([A-Za-z0-9_.-]+):\s*(.*)$", line)
            if m:
                out[m.group(1)] = _unquote(m.group(2))
    return out


def steps_of(text: str, item_indent: int = 4) -> List[Step]:
    """Steps of a composite action (`runs.steps`) or of a job (`steps:`), whose items sit at item_indent."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if re.match(rf"^ {{{item_indent}}}- ", line)]
    result: List[Step] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = [lines[start].replace("- ", "  ", 1)] + lines[start + 1 : end]
        key_indent = item_indent + 2
        step = Step(env={}, **{"with": {}})
        i = 0
        while i < len(block):
            line = block[i]
            m = re.match(rf"^ {{{key_indent}}}([A-Za-z0-9_-]+):\s*(.*)$", line)
            if not m:
                i += 1
                continue
            key, value = m.group(1), m.group(2)
            if key == "run" and value in ("|", ">-", ">"):
                body: List[str] = []
                j = i + 1
                while j < len(block) and (not block[j].strip() or _indent(block[j]) > key_indent):
                    body.append(block[j][key_indent + 2 :] if block[j].strip() else "")
                    j += 1
                step["run"] = "\n".join(body).rstrip("\n") + "\n"
                i = j
                continue
            if key in ("env", "with") and value == "":
                j = i + 1
                nested: List[str] = []
                while j < len(block) and (not block[j].strip() or _indent(block[j]) > key_indent):
                    nested.append(block[j])
                    j += 1
                step[key] = parse_map(nested, key_indent + 2)
                i = j
                continue
            step[key] = _unquote(value) if not value.startswith(">") else value
            i += 1
        result.append(step)
    return result


def action_steps(name: str) -> List[Step]:
    text = (ACTIONS / name / "action.yml").read_text(encoding="utf-8")
    steps = steps_of(text)
    if not steps:
        raise AssertionError(f"no steps found in {name}")
    return steps


def step_named(steps: List[Step], fragment: str) -> Step:
    exact = [s for s in steps if str(s.get("name", "")).lower() == fragment.lower()]
    hits = exact or [s for s in steps if fragment.lower() in str(s.get("name", "")).lower()]
    if len(hits) != 1:
        raise AssertionError(f"expected exactly one step named like {fragment!r}, found {len(hits)}")
    return hits[0]


def _fold(lines: List[str], start: int, key_indent: int) -> tuple:
    """Value of a key whose scalar continues on more-indented lines (`if: >-`), joined by spaces."""
    parts: List[str] = []
    j = start + 1
    while j < len(lines) and (not lines[j].strip() or _indent(lines[j]) > key_indent):
        if lines[j].strip():
            parts.append(lines[j].strip())
        j += 1
    return " ".join(parts), j


def jobs_of(text: str) -> Dict[str, Dict]:
    """job id -> {keys, permissions, needs, steps, with, secrets, ...}. Job ids at indent 2, their keys at indent 4."""
    lines = text.splitlines()
    try:
        top = next(i for i, line in enumerate(lines) if line == "jobs:")
    except StopIteration:
        raise AssertionError("no jobs: section")
    starts = [i for i in range(top + 1, len(lines)) if re.match(r"^  [A-Za-z0-9_-]+:\s*$", lines[i])]
    jobs: Dict[str, Dict] = {}
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start + 1 : end]
        job: Dict = {"keys": {}, "permissions": {}, "with": {}, "secrets": {}, "needs": [], "lines": block}
        i = 0
        while i < len(block):
            m = re.match(r"^    ([A-Za-z0-9_-]+):\s*(.*)$", block[i])
            if not m:
                i += 1
                continue
            key, value = m.group(1), m.group(2)
            if value in (">-", ">", "|"):
                value, i = _fold(block, i, 4)
                job["keys"][key] = value
                continue
            if value == "":
                j = i + 1
                nested: List[str] = []
                while j < len(block) and (not block[j].strip() or _indent(block[j]) > 4):
                    nested.append(block[j])
                    j += 1
                if key in ("permissions", "with", "secrets", "concurrency", "outputs", "strategy"):
                    job[key] = parse_map(nested, 6) if key != "strategy" else nested
                job["keys"][key] = ""
                i = j
                continue
            job["keys"][key] = _unquote(value)
            i += 1
        needs = job["keys"].get("needs", "")
        if needs.startswith("["):
            job["needs"] = [x.strip() for x in needs.strip("[]").split(",") if x.strip()]
        elif needs:
            job["needs"] = [needs]
        job["steps"] = steps_of("\n".join(block), item_indent=6) if any(re.match(r"^    steps:", b) for b in block) else []
        jobs[lines[start].strip().rstrip(":")] = job
    return jobs
