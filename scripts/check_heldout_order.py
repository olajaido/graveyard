#!/usr/bin/env python3
"""Check the held-out order of work and create its tags (mortality-model-v2, design 13.2).

Part 1 (T5.22): the tag sequence, argument parsing, git helpers and checks 1 to 3
(tags in order and ancestors, no data early, artefact timing). Part 2 (T5.23): checks 4 and 5
(category A never amendable, category B amendable through AMENDMENTS.md). Part 3 (T5.24):
checks 6 to 9 (draw record, capture window and log, result files, v1 intact) and ``--tag``.

Every check takes a ``Context`` and returns a list of ``Finding`` objects; an empty list
means the check passed. Dates are committer dates converted to UTC, never tag object dates.
Local git only; standard library only.

Usage:
    python3 scripts/check_heldout_order.py --verify-all [--repo PATH]
    python3 scripts/check_heldout_order.py --step <tag> [--tag] [--repo PATH]

Exit codes: 0 all checks pass, 1 a check failed, 2 usage error or git failure.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIREMENTS_TAG = "v2-requirements"
ANALYSIS_TAG = "mortality-v2-analysis"
FROZEN_TAG = "mortality-v2-frozen"
DRAW_TAG = "eval-heldout-draw"
ANSWER_KEY_TAG = "eval-heldout-answer-key"
CAPTURE_TAG = "eval-heldout-capture"
RESULT_TAG = "eval-heldout-result"

TAG_SEQUENCE: tuple[str, ...] = (
    REQUIREMENTS_TAG,
    ANALYSIS_TAG,
    FROZEN_TAG,
    DRAW_TAG,
    ANSWER_KEY_TAG,
    CAPTURE_TAG,
    RESULT_TAG,
)

REJECT_REQUIREMENTS_TAG = "tag exists; not created by this script"

RULE_ORDER = "MV2-ORD-1"
RULE_EARLY = "MV2-ORD-2"
RULE_AMEND = "MV2-ORD-5"

HELDOUT_DIR = "eval/heldout/"
AMENDMENTS_PATH = "eval/heldout/AMENDMENTS.md"
REQUIREMENTS_PATH = ".kiro/specs/mortality-model-v2/requirements.md"

# Paths allowed under eval/heldout/ at the frozen tag (check 2).
FROZEN_HELDOUT_ALLOWED: frozenset[str] = frozenset(
    HELDOUT_DIR + name
    for name in (
        "README.md",
        "dataset.yaml",
        "gate.yaml",
        "f/queries.tsv",
        "FROZEN_HARNESS.json",
        "AMENDMENTS.md",
    )
)

# Artefact groups of design 13.1, keyed by the tag that owns them. Entries ending in "/" are
# directories. Check 3 looks at the commit that first added any path of the group.
ARTEFACT_GROUPS: dict[str, tuple[str, ...]] = {
    REQUIREMENTS_TAG: (REQUIREMENTS_PATH,),
    ANALYSIS_TAG: (
        ".kiro/specs/mortality-model-v2/design.md",
        ".kiro/specs/mortality-model-v2/tasks.md",
        "eval/V1_LOCK.json",
        "eval/analysis/v1-failures.json",
        "eval/analysis/v1-failures.md",
        "eval/analysis/conclusion.md",
        "scripts/make_v1_lock.py",
        "eval/analysis/moved-repo-probe/",
    ),
    FROZEN_TAG: (
        "backend/core/scoring/v2/",
        "backend/core/scoring/versions.py",
        "backend/core/scoring/weights.v2.yaml",
        "eval/FROZEN_WEIGHTS.v2.sha256",
        "eval/FROZEN_MODEL.v2.json",
        *sorted(FROZEN_HELDOUT_ALLOWED),
    ),
    DRAW_TAG: (
        HELDOUT_DIR + "snapshot/",
        HELDOUT_DIR + "exclusions.tsv",
        HELDOUT_DIR + "draw/",
        HELDOUT_DIR + "f/raw/",
    ),
    ANSWER_KEY_TAG: (
        HELDOUT_DIR + "labelled_packages.csv",
        HELDOUT_DIR + "review/",
    ),
    CAPTURE_TAG: (
        HELDOUT_DIR + "fixtures/",
        HELDOUT_DIR + "capture-log.tsv",
    ),
    RESULT_TAG: (
        HELDOUT_DIR + "results.v1.json",
        HELDOUT_DIR + "results.v2.json",
        HELDOUT_DIR + "comparison.json",
        HELDOUT_DIR + "comparison.md",
    ),
}


class GitError(Exception):
    """A git command failed in a way that is not a plain yes or no answer."""


@dataclass(frozen=True)
class Finding:
    """One failed check: the rule id it is reported under and a message."""

    rule: str
    check: int
    message: str

    def render(self) -> str:
        return f"FAIL [{self.rule}] check {self.check}: {self.message}"


@dataclass(frozen=True)
class Context:
    """What the checks run against.

    ``refs`` maps each tag in play to the commit it points at (or, in ``--step`` mode for a
    tag that does not exist yet, ``HEAD``). ``step`` is the tag being checked for creation,
    or None under ``--verify-all``.
    """

    repo: Path
    refs: dict[str, str]
    step: str | None = None


Check = Callable[[Context], list[Finding]]


# --- git helpers -------------------------------------------------------------------------


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc


def git(repo: Path, *args: str) -> str:
    """Run git and return stdout; raise GitError on a non-zero exit."""
    done = _run(repo, *args)
    if done.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def tag_commit(repo: Path, tag: str) -> str | None:
    """Commit SHA the tag points at, or None when the tag does not exist."""
    done = _run(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def head_commit(repo: Path) -> str:
    return git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    """True when ``ancestor`` is an ancestor of ``descendant`` (or the same commit)."""
    done = _run(repo, "merge-base", "--is-ancestor", ancestor, descendant)
    if done.returncode == 0:
        return True
    if done.returncode == 1:
        return False
    raise GitError(f"git merge-base --is-ancestor failed: {done.stderr.strip()}")


def commit_date_utc(repo: Path, rev: str) -> datetime:
    """Committer date of ``rev`` converted to UTC."""
    raw = git(repo, "log", "-1", "--format=%cI", rev).strip()
    return datetime.fromisoformat(raw).astimezone(UTC)


def first_add_commit(repo: Path, rev: str, paths: Sequence[str]) -> str | None:
    """Earliest commit reachable from ``rev`` that added any of ``paths`` (None if none)."""
    out = git(
        repo,
        "log",
        "--diff-filter=A",
        "--no-renames",
        "--topo-order",
        "--reverse",
        "--format=%H",
        rev,
        "--",
        *paths,
    )
    lines = out.split()
    return lines[0] if lines else None


def ls_tree_files(repo: Path, rev: str, prefix: str) -> list[str]:
    """Every file path under ``prefix`` at ``rev``."""
    out = git(repo, "ls-tree", "-r", "--name-only", "-z", rev, "--", prefix)
    return [p for p in out.split("\0") if p]


def show_bytes(repo: Path, rev: str, path: str) -> bytes | None:
    """Raw bytes of ``path`` at ``rev``, or None when the path is absent there."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), "show", f"{rev}:{path}"],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc
    return done.stdout if done.returncode == 0 else None


def show_blob(repo: Path, rev: str, path: str) -> str | None:
    """Text of ``path`` at ``rev``, or None when the path is absent there."""
    done = _run(repo, "show", f"{rev}:{path}")
    return done.stdout if done.returncode == 0 else None


# --- checks ------------------------------------------------------------------------------


def _short(sha: str) -> str:
    return sha[:10]


def check_order(ctx: Context) -> list[Finding]:
    """Check 1: tags exist in order, and each is a strict descendant of the one before."""
    findings: list[Finding] = []
    last = max((i for i, t in enumerate(TAG_SEQUENCE) if t in ctx.refs), default=-1)
    previous: str | None = None
    for tag in TAG_SEQUENCE[: last + 1]:
        if tag not in ctx.refs:
            findings.append(Finding(RULE_ORDER, 1, f"tag {tag} is missing but a later tag exists"))
            continue
        if previous is not None:
            a, b = ctx.refs[previous], ctx.refs[tag]
            if a == b:
                findings.append(
                    Finding(RULE_ORDER, 1, f"{previous} and {tag} point at the same commit")
                )
            elif not is_ancestor(ctx.repo, a, b):
                findings.append(
                    Finding(RULE_ORDER, 1, f"{previous} is not an ancestor of {tag} (out of order)")
                )
        previous = tag
    return findings


def check_no_data_early(ctx: Context) -> list[Finding]:
    """Check 2 (MV2-ORD-2): the frozen tag holds no held-out data and no amendment entry."""
    commit = ctx.refs.get(FROZEN_TAG)
    if commit is None:
        return []
    findings: list[Finding] = []
    extra = sorted(set(ls_tree_files(ctx.repo, commit, HELDOUT_DIR)) - FROZEN_HELDOUT_ALLOWED)
    for path in extra:
        findings.append(Finding(RULE_EARLY, 2, f"{path} exists at {FROZEN_TAG}"))
    text = show_blob(ctx.repo, commit, AMENDMENTS_PATH)
    if text is not None and re.search(r"^## ", text, flags=re.MULTILINE):
        findings.append(Finding(RULE_EARLY, 2, f"{AMENDMENTS_PATH} has an entry at {FROZEN_TAG}"))
    return findings


def check_artefact_timing(ctx: Context) -> list[Finding]:
    """Check 3: each group's first add lies after the previous tag and within its own tag."""
    findings: list[Finding] = []
    for index, tag in enumerate(TAG_SEQUENCE):
        commit = ctx.refs.get(tag)
        if commit is None:
            continue
        paths = ARTEFACT_GROUPS[tag]
        first = first_add_commit(ctx.repo, commit, paths)
        if first is None:
            findings.append(Finding(RULE_ORDER, 3, f"no commit up to {tag} adds its artefacts"))
            continue
        if index == 0:
            # first_add_commit searches the history of the tag, so it is an ancestor of it.
            continue
        previous = ctx.refs.get(TAG_SEQUENCE[index - 1])
        if previous is None:
            continue
        if first == previous or not is_ancestor(ctx.repo, previous, first):
            findings.append(
                Finding(
                    RULE_ORDER,
                    3,
                    f"artefacts of {tag} were first added in {_short(first)}, "
                    f"which is not after {TAG_SEQUENCE[index - 1]}",
                )
            )
    return findings


# --- checks 4 and 5: category A and B ----------------------------------------------------

FROZEN_MODEL_PATH = "eval/FROZEN_MODEL.v2.json"
FROZEN_HARNESS_PATH = "eval/heldout/FROZEN_HARNESS.json"

# Category A paths besides the files listed in FROZEN_MODEL.v2.json (design 13.2, check 4).
# Entries ending in "/" are directories.
CATEGORY_A_FIXED: tuple[str, ...] = (
    "backend/core/scoring/weights.v2.yaml",
    FROZEN_MODEL_PATH,
    "eval/FROZEN_WEIGHTS.v2.sha256",
    "eval/V1_LOCK.json",
    HELDOUT_DIR + "dataset.yaml",
    HELDOUT_DIR + "gate.yaml",
    HELDOUT_DIR + "f/queries.tsv",
    "scripts/capture_anchors.py",
    "scripts/capture_eval.py",
    "backend/sources/",
    "backend/core/sources/",
)

# Files outside A and B whose change passes with a notice (tests, report modules and tools).
_NOTICE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^backend/eval/tests/"),
    re.compile(r"^backend/tests/"),
    re.compile(r"^backend/eval/(?:heldout/)?(?:report|compare|analysis|probe|merge|__main__)\.py$"),
)

_ENTRY_HEADER = re.compile(r"^## (\d{4}-\d{2}-\d{2}) (\S.*?)\s*$")
_PATHS_LINE = re.compile(r"^paths:\s*(\S.*?)\s*$")
_REASON_LINE = re.compile(r"^reason:\s*\S")


@dataclass(frozen=True)
class Amendment:
    """One entry of AMENDMENTS.md: its header line, date, name and the paths it names."""

    header: str
    date: str
    name: str
    paths: frozenset[str]


def parse_amendments(text: str) -> list[Amendment]:
    """Entries with a ``## YYYY-MM-DD <name>`` header, a ``paths:`` line and a ``reason:`` line.

    An entry runs to the next ``## `` line. An entry missing either line, or with a date that
    is not a real calendar date, is ignored (it cannot amend anything).
    """
    blocks: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        if line.startswith("## "):
            blocks.append((line.rstrip(), []))
        elif blocks:
            blocks[-1][1].append(line)
    entries: list[Amendment] = []
    for header, body in blocks:
        match = _ENTRY_HEADER.match(header)
        if match is None:
            continue
        try:
            datetime.strptime(match.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        paths: set[str] = set()
        for line in body:
            paths_match = _PATHS_LINE.match(line)
            if paths_match:
                paths.update(p.strip() for p in paths_match.group(1).split(",") if p.strip())
        if not paths or not any(_REASON_LINE.match(line) for line in body):
            continue
        entries.append(Amendment(header, match.group(1), match.group(2), frozenset(paths)))
    return entries


def _later_tags(ctx: Context) -> list[str]:
    """Tags after the frozen tag that are in play, in sequence order."""
    if FROZEN_TAG not in ctx.refs:
        return []
    start = TAG_SEQUENCE.index(FROZEN_TAG) + 1
    return [t for t in TAG_SEQUENCE[start:] if t in ctx.refs]


def _json_files(ctx: Context, path: str) -> list[str]:
    """Keys of the ``files`` object of a JSON record at the frozen tag (empty if unusable)."""
    text = show_blob(ctx.repo, ctx.refs[FROZEN_TAG], path)
    if text is None:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    files = data.get("files") if isinstance(data, dict) else None
    return sorted(str(k) for k in files) if isinstance(files, dict) else []


def category_a_paths(ctx: Context) -> list[str]:
    return sorted({*CATEGORY_A_FIXED, *_json_files(ctx, FROZEN_MODEL_PATH)})


def category_b_paths(ctx: Context) -> list[str]:
    a_paths = category_a_paths(ctx)
    return [
        p
        for p in _json_files(ctx, FROZEN_HARNESS_PATH)
        if not any(p == a or (a.endswith("/") and p.startswith(a)) for a in a_paths)
    ]


def _changed(ctx: Context, tag: str, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    out = git(
        ctx.repo, "diff", "--name-only", "-z", ctx.refs[FROZEN_TAG], ctx.refs[tag], "--", *paths
    )
    return [p for p in out.split("\0") if p]


def check_category_a(ctx: Context) -> list[Finding]:
    """Check 4 (MV2-ORD-5): no category A file changes after the frozen tag; no amendment helps."""
    findings: list[Finding] = []
    a_paths = category_a_paths(ctx) if FROZEN_TAG in ctx.refs else []
    for tag in _later_tags(ctx):
        for path in _changed(ctx, tag, a_paths):
            findings.append(
                Finding(
                    RULE_AMEND,
                    4,
                    f"{path} changed between {FROZEN_TAG} and {tag}; "
                    "a category A file is never amendable (new model version)",
                )
            )
    return findings


def _first_touch(ctx: Context, tag: str, path: str) -> str | None:
    out = git(
        ctx.repo,
        "log",
        "--reverse",
        "--topo-order",
        "--format=%H",
        f"{ctx.refs[FROZEN_TAG]}..{ctx.refs[tag]}",
        "--",
        path,
    )
    lines = out.split()
    return lines[0] if lines else None


def _entry_first_commit(ctx: Context, tag: str, entry: Amendment) -> str | None:
    out = git(
        ctx.repo,
        "log",
        "--reverse",
        "--topo-order",
        "--format=%H",
        f"-S{entry.header}",
        ctx.refs[tag],
        "--",
        AMENDMENTS_PATH,
    )
    lines = out.split()
    return lines[0] if lines else None


def _amendment_problem(ctx: Context, tag: str, path: str, change: str) -> str | None:
    """None if an entry at ``tag`` validly amends ``path`` for the change commit, else why not."""
    text = show_blob(ctx.repo, ctx.refs[tag], AMENDMENTS_PATH)
    entries = [e for e in parse_amendments(text or "") if path in e.paths]
    if not entries:
        return f"{AMENDMENTS_PATH} has no entry naming it"
    change_date = commit_date_utc(ctx.repo, change).date().isoformat()
    reasons: list[str] = []
    for entry in entries:
        if entry.date > change_date:
            reasons.append(
                f"entry '{entry.name}' is dated {entry.date}, after the change ({change_date})"
            )
            continue
        first = _entry_first_commit(ctx, tag, entry)
        if first is None:
            reasons.append(f"entry '{entry.name}' has no first-appearance commit")
        elif first == change or not is_ancestor(ctx.repo, first, change):
            reasons.append(
                f"entry '{entry.name}' first appears in {_short(first)}, "
                f"which is not a strict ancestor of the change commit {_short(change)}"
            )
        else:
            return None
    return "; ".join(reasons)


def _deleted_lines(ctx: Context, tag: str) -> int:
    """Lines deleted from AMENDMENTS.md by any commit in ``frozen..tag``.

    Summed per commit, so a line that is edited or removed and then restored still counts;
    a net diff against the frozen tag would miss that.
    """
    out = git(
        ctx.repo,
        "log",
        "--numstat",
        "--format=",
        f"{ctx.refs[FROZEN_TAG]}..{ctx.refs[tag]}",
        "--",
        AMENDMENTS_PATH,
    )
    total = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            total += int(parts[1]) if parts[1].isdigit() else 1
    return total


def check_category_b(ctx: Context) -> list[Finding]:
    """Check 5 (amendment A5): a harness file changes only after a prior, dated, named entry."""
    findings: list[Finding] = []
    tags = _later_tags(ctx)
    if not tags:
        return findings
    b_paths = category_b_paths(ctx)
    for tag in tags:
        for path in _changed(ctx, tag, b_paths):
            change = _first_touch(ctx, tag, path)
            if change is None:
                continue
            problem = _amendment_problem(ctx, tag, path, change)
            if problem is not None:
                findings.append(
                    Finding(
                        RULE_AMEND,
                        5,
                        f"{path} changed after {FROZEN_TAG} (commit {_short(change)}): {problem}",
                    )
                )
        removed = _deleted_lines(ctx, tag)
        if removed:
            findings.append(
                Finding(
                    RULE_AMEND,
                    5,
                    f"{AMENDMENTS_PATH} is append-only but {removed} line(s) were deleted "
                    f"or edited between {FROZEN_TAG} and {tag}",
                )
            )
    # Changes outside A and B that pass with a notice (reported once, for the latest tag).
    a_and_b = category_a_paths(ctx) + b_paths
    out = git(ctx.repo, "diff", "--name-only", "-z", ctx.refs[FROZEN_TAG], ctx.refs[tags[-1]])
    for path in sorted(p for p in out.split("\0") if p):
        covered = any(path == x or (x.endswith("/") and path.startswith(x)) for x in a_and_b)
        if not covered and any(pat.search(path) for pat in _NOTICE_PATTERNS):
            print(
                f"NOTICE [{RULE_AMEND}] check 5: {path} changed; outside A and B, allowed",
                file=sys.stderr,
            )
    return findings


# --- checks 6 to 9 -----------------------------------------------------------------------

RULE_DRAW = "MV2-RUN-2"
RULE_RESULT = "MV2-ORD-4"
RULE_V1 = "MV2-ISO-1"

SEED = "graveyard-mortality-v2-heldout-1"
DRAW_JSON = HELDOUT_DIR + "draw/draw.json"
PINS_JSON = HELDOUT_DIR + "snapshot/pins.json"
QUERIES_TSV = HELDOUT_DIR + "f/queries.tsv"
QUERY_LOG = HELDOUT_DIR + "f/raw/query-log.tsv"
LABELS_CSV = HELDOUT_DIR + "labelled_packages.csv"
FIXTURES_DIR = HELDOUT_DIR + "fixtures/"
CAPTURE_LOG = HELDOUT_DIR + "capture-log.tsv"
V1_LOCK_PATH = "eval/V1_LOCK.json"
RESULT_FILES: tuple[str, ...] = (HELDOUT_DIR + "results.v1.json", HELDOUT_DIR + "results.v2.json")
WINDOW_DAYS = 3

CAPTURE_LOG_COLUMNS: tuple[str, ...] = (
    "ecosystem",
    "name",
    "attempt",
    "form",
    "failure_class",
    "as_of",
    "date",
)
RECAPTURE_FORMS = frozenset({"refetch_unavailable", "only"})
NOT_CAPTURED_FORM = "not_captured"
# Transient failure classes of the capture script's retry logic (HTTP 429 or 5xx, timeouts,
# network errors). ``http_5xx`` stands for any 5xx; ``http_5NN`` is accepted too.
TRANSIENT_CLASSES = frozenset({"http_429", "http_5xx", "timeout", "network", "network_error"})
_HTTP_5NN = re.compile(r"^http_5\d\d$")

# Where each recorded provenance hash comes from: (key in ``provenance``, tag, path).
# A path of None means the fixture-set hash (sha256 over sorted ``path<TAB>sha256`` lines,
# path relative to eval/heldout/fixtures/, each line ended by a newline).
PROVENANCE_SOURCES: tuple[tuple[str, str, str | None], ...] = (
    ("weights_sha256", FROZEN_TAG, "backend/core/scoring/weights.v2.yaml"),
    ("manifest_sha256", FROZEN_TAG, FROZEN_MODEL_PATH),
    ("labels_sha256", ANSWER_KEY_TAG, LABELS_CSV),
    ("fixture_set_sha256", CAPTURE_TAG, None),
    ("gate_config_sha256", FROZEN_TAG, HELDOUT_DIR + "gate.yaml"),
    ("frozen_harness_sha256", RESULT_TAG, FROZEN_HARNESS_PATH),
    ("amendments_sha256", RESULT_TAG, AMENDMENTS_PATH),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tsv_rows(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.splitlines() if line.strip()]


def _json_object(text: str | None) -> dict[str, object] | None:
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def check_draw_record(ctx: Context) -> list[Finding]:
    """Check 6: seed, draw date, pinned snapshot hashes and one query-log line per grid row."""
    commit = ctx.refs.get(DRAW_TAG)
    if commit is None:
        return []
    repo = ctx.repo
    findings: list[Finding] = []

    def fail(message: str) -> None:
        findings.append(Finding(RULE_DRAW, 6, message))

    draw = _json_object(show_blob(repo, commit, DRAW_JSON))
    if draw is None:
        fail(f"{DRAW_JSON} is missing or not a JSON object at {DRAW_TAG}")
    else:
        if draw.get("seed") != SEED:
            fail(f"{DRAW_JSON} seed is not the literal {SEED!r}")
        raw_date = draw.get("draw_date")
        try:
            drawn = date.fromisoformat(raw_date) if isinstance(raw_date, str) else None
        except ValueError:
            drawn = None
        if drawn is None:
            fail(f"{DRAW_JSON} has no valid draw_date")
        elif drawn > commit_date_utc(repo, commit).date():
            fail(f"draw date {drawn} is after the {DRAW_TAG} commit date")
    findings.extend(_pin_findings(ctx, commit))
    findings.extend(_grid_findings(ctx, commit))
    return findings


def _pin_findings(ctx: Context, commit: str) -> list[Finding]:
    pins = _json_object(show_blob(ctx.repo, commit, PINS_JSON))
    sources = pins.get("sources") if pins else None
    if not isinstance(sources, dict) or not sources:
        return [Finding(RULE_DRAW, 6, f"{PINS_JSON} is missing or has no sources")]
    findings: list[Finding] = []
    for source_id, entry in sources.items():
        name = entry.get("file") if isinstance(entry, dict) else None
        expected = entry.get("trimmed_sha256") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(expected, str) or "/" in name:
            findings.append(Finding(RULE_DRAW, 6, f"pin {source_id} needs `file` and a hash"))
            continue
        data = show_bytes(ctx.repo, commit, f"{HELDOUT_DIR}snapshot/{name}")
        if data is None:
            findings.append(Finding(RULE_DRAW, 6, f"pin {source_id}: snapshot/{name} is missing"))
        elif _sha256(data) != expected:
            findings.append(Finding(RULE_DRAW, 6, f"pin {source_id}: snapshot/{name} hash differs"))
    return findings


def _grid_ids(text: str | None) -> list[str] | None:
    """The ``id`` column of a TSV with a header, or None when unusable."""
    if text is None:
        return None
    rows = _tsv_rows(text)
    if not rows or "id" not in rows[0]:
        return None
    index = rows[0].index("id")
    return [r[index] for r in rows[1:] if len(r) > index]


def _grid_findings(ctx: Context, commit: str) -> list[Finding]:
    queries = _grid_ids(show_blob(ctx.repo, commit, QUERIES_TSV))
    log = _grid_ids(show_blob(ctx.repo, commit, QUERY_LOG))
    if queries is None:
        return [Finding(RULE_DRAW, 6, f"{QUERIES_TSV} is missing or has no id column")]
    if log is None:
        return [Finding(RULE_DRAW, 6, f"{QUERY_LOG} is missing or has no id column")]
    findings: list[Finding] = []
    missing = sorted(set(queries) - set(log), key=lambda v: (len(v), v))
    if missing:
        findings.append(
            Finding(
                RULE_DRAW, 6, f"query-log.tsv has no line for grid cell(s) {', '.join(missing)}"
            )
        )
    extra = sorted(set(log) - set(queries), key=lambda v: (len(v), v))
    if extra:
        findings.append(
            Finding(RULE_DRAW, 6, f"query-log.tsv has line(s) outside the grid: {', '.join(extra)}")
        )
    if len(log) != len(set(log)):
        findings.append(Finding(RULE_DRAW, 6, "query-log.tsv repeats a grid cell"))
    return findings


def _fixture_as_ofs(ctx: Context, commit: str) -> tuple[dict[str, str], list[Finding]]:
    """Map ``<ecosystem>/<name>`` to the fixture's ``as_of``; findings for unusable fixtures."""
    found: dict[str, str] = {}
    findings: list[Finding] = []
    for path in ls_tree_files(ctx.repo, commit, FIXTURES_DIR):
        if not path.endswith(".json"):
            continue
        key = path[len(FIXTURES_DIR) : -len(".json")]
        doc = _json_object(show_blob(ctx.repo, commit, path))
        value = doc.get("as_of") if doc else None
        if not isinstance(value, str):
            findings.append(Finding(RULE_DRAW, 7, f"{path} has no as_of"))
            continue
        found[key] = value
    return found, findings


def _labelled_keys(text: str | None) -> set[str] | None:
    if text is None:
        return None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    keys: set[str] = set()
    for row in reader:
        eco, name = row.get("ecosystem"), row.get("name")
        if eco and name:
            keys.add(f"{eco}/{name}")
    return keys


def check_capture(ctx: Context) -> list[Finding]:
    """Check 7: capture window and the rules of capture-log.tsv."""
    commit = ctx.refs.get(CAPTURE_TAG)
    key_commit = ctx.refs.get(ANSWER_KEY_TAG)
    if commit is None or key_commit is None:
        return []
    repo = ctx.repo
    findings: list[Finding] = []

    def fail(message: str) -> None:
        findings.append(Finding(RULE_DRAW, 7, message))

    as_ofs, problems = _fixture_as_ofs(ctx, commit)
    findings.extend(problems)
    distinct = sorted(set(as_ofs.values()))
    as_of: date | None = None
    if not distinct:
        fail("no fixture carries an as_of")
    elif len(distinct) > 1:
        fail(f"fixtures carry more than one as_of: {', '.join(distinct)}")
    else:
        try:
            as_of = date.fromisoformat(distinct[0])
        except ValueError:
            fail(f"fixture as_of {distinct[0]!r} is not a date")
    if as_of is not None:
        first = commit_date_utc(repo, key_commit).date()
        if not first <= as_of <= first + timedelta(days=WINDOW_DAYS):
            fail(
                f"as_of {as_of} is outside {first} to {first + timedelta(days=WINDOW_DAYS)} "
                f"(date of {ANSWER_KEY_TAG})"
            )
    findings.extend(_log_findings(ctx, commit, key_commit, set(as_ofs), distinct))
    return findings


def _log_findings(
    ctx: Context, commit: str, key_commit: str, fixture_keys: set[str], as_ofs: list[str]
) -> list[Finding]:
    findings: list[Finding] = []

    def fail(message: str) -> None:
        findings.append(Finding(RULE_DRAW, 7, message))

    text = show_blob(ctx.repo, commit, CAPTURE_LOG)
    if text is None:
        return [Finding(RULE_DRAW, 7, f"{CAPTURE_LOG} is missing at {CAPTURE_TAG}")]
    rows = _tsv_rows(text)
    if rows and tuple(rows[0]) == CAPTURE_LOG_COLUMNS:
        rows = rows[1:]
    recaptures: dict[str, int] = {}
    not_captured: set[str] = set()
    for cols in rows:
        if len(cols) != len(CAPTURE_LOG_COLUMNS):
            fail(f"capture-log.tsv line has {len(cols)} columns, expected 7: {cols[:2]}")
            continue
        eco, name, _attempt, form, failure, as_of_text, _logged = cols
        key = f"{eco}/{name}"
        if as_ofs and as_of_text not in as_ofs:
            fail(f"capture-log.tsv {key}: as_of {as_of_text} differs from the fixtures")
        if form == NOT_CAPTURED_FORM:
            not_captured.add(key)
        elif form in RECAPTURE_FORMS:
            recaptures[key] = recaptures.get(key, 0) + 1
            if failure not in TRANSIENT_CLASSES and not _HTTP_5NN.match(failure):
                fail(f"capture-log.tsv {key}: failure_class {failure!r} is not transient")
        else:
            fail(f"capture-log.tsv {key}: unknown form {form!r}")
    for key, count in sorted(recaptures.items()):
        if count > 1:
            fail(f"capture-log.tsv {key}: {count} re-captures (at most one)")
    labelled = _labelled_keys(show_blob(ctx.repo, key_commit, LABELS_CSV))
    if labelled is None:
        fail(f"{LABELS_CSV} is missing at {ANSWER_KEY_TAG}")
    else:
        for key in sorted(labelled - fixture_keys - not_captured):
            fail(f"{key} has no fixture and no form=not_captured line")
        never = sorted(not_captured & labelled - fixture_keys)
        if never:
            print(
                f"NOTICE [{RULE_DRAW}] check 7: never captured: {', '.join(never)}",
                file=sys.stderr,
            )
    return findings


def _fixture_set_hash(ctx: Context, commit: str) -> str:
    lines: list[str] = []
    for path in ls_tree_files(ctx.repo, commit, FIXTURES_DIR):
        data = show_bytes(ctx.repo, commit, path) or b""
        lines.append(f"{path[len(FIXTURES_DIR) :]}\t{_sha256(data)}\n")
    return _sha256("".join(sorted(lines)).encode("utf-8"))


def _expected_hash(ctx: Context, tag: str, path: str | None) -> str | None:
    commit = ctx.refs[tag]
    if path is None:
        return _fixture_set_hash(ctx, commit)
    data = show_bytes(ctx.repo, commit, path)
    return None if data is None else _sha256(data)


def check_result_files(ctx: Context) -> list[Finding]:
    """Check 8: each result file added by one commit, after capture, with matching hashes."""
    result = ctx.refs.get(RESULT_TAG)
    if result is None:
        return []
    findings: list[Finding] = []

    def fail(message: str) -> None:
        findings.append(Finding(RULE_RESULT, 8, message))

    expected: dict[str, str | None] = {}
    for key, tag, path in PROVENANCE_SOURCES:
        expected[key] = _expected_hash(ctx, tag, path) if tag in ctx.refs else None
    capture = ctx.refs.get(CAPTURE_TAG)
    for path in RESULT_FILES:
        commits = git(ctx.repo, "log", "--format=%H", result, "--", path).split()
        if len(commits) != 1:
            fail(f"{path} was touched by {len(commits)} commits at {RESULT_TAG}, expected 1")
        elif capture is not None and (
            commits[0] == capture or not is_ancestor(ctx.repo, capture, commits[0])
        ):
            fail(f"{path} was added in {_short(commits[0])}, not after {CAPTURE_TAG}")
        doc = _json_object(show_blob(ctx.repo, result, path))
        provenance = doc.get("provenance") if doc else None
        if not isinstance(provenance, dict):
            fail(f"{path} has no provenance object")
            continue
        for key, want in expected.items():
            have = provenance.get(key)
            if want is None and key == "amendments_sha256":
                if have is not None:
                    fail(f"{path}: {key} is {have!r} but {AMENDMENTS_PATH} is absent")
            elif want is None:
                fail(f"{path}: cannot compute {key} (source file or tag missing)")
            elif have != want:
                fail(f"{path}: provenance {key} does not match the committed bytes")
    return findings


def check_v1_intact(ctx: Context) -> list[Finding]:
    """Check 9: every file listed in V1_LOCK.json is unchanged at each tag after the analysis."""
    base = ctx.refs.get(ANALYSIS_TAG)
    if base is None:
        return []
    lock = _json_object(show_blob(ctx.repo, base, V1_LOCK_PATH))
    files = lock.get("files") if lock else None
    if not isinstance(files, dict):
        return [Finding(RULE_V1, 9, f"{V1_LOCK_PATH} is missing or has no files at {ANALYSIS_TAG}")]
    paths = sorted(str(p) for p in files)
    findings: list[Finding] = []
    start = TAG_SEQUENCE.index(ANALYSIS_TAG) + 1
    for tag in (t for t in TAG_SEQUENCE[start:] if t in ctx.refs):
        for path in _diff_names(ctx, base, ctx.refs[tag], paths):
            findings.append(Finding(RULE_V1, 9, f"locked v1 file {path} differs at {tag}"))
    return findings


def _diff_names(ctx: Context, a: str, b: str, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    out = git(ctx.repo, "diff", "--name-only", "-z", a, b, "--", *paths)
    return [p for p in out.split("\0") if p]


CHECKS: tuple[Check, ...] = (
    check_order,
    check_no_data_early,
    check_artefact_timing,
    check_category_a,
    check_category_b,
    check_draw_record,
    check_capture,
    check_result_files,
    check_v1_intact,
)


# --- command line ------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_heldout_order.py",
        description="Check the held-out order of work (design 13.2).",
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--verify-all", action="store_true", help="check every tag that exists")
    modes.add_argument(
        "--step",
        metavar="TAG",
        choices=TAG_SEQUENCE,
        help="check the preconditions for creating this tag",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        help="with --step: create an annotated tag at HEAD if the checks pass",
    )
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="repository to check")
    return parser


def build_context(repo: Path, step: str | None) -> Context:
    refs: dict[str, str] = {}
    for tag in TAG_SEQUENCE:
        commit = tag_commit(repo, tag)
        if commit is not None:
            refs[tag] = commit
    if step is None:
        return Context(repo, refs)
    # Only the tags up to the step matter; the step tag itself is HEAD if it does not exist.
    upto = TAG_SEQUENCE[: TAG_SEQUENCE.index(step) + 1]
    refs = {t: c for t, c in refs.items() if t in upto}
    refs.setdefault(step, head_commit(repo))
    return Context(repo, refs, step)


def run_checks(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for check in CHECKS:
        findings.extend(check(ctx))
    return findings


def create_tag(repo: Path, tag: str) -> None:
    """Create an annotated tag at HEAD. Callers run the checks first."""
    git(repo, "tag", "-a", tag, "-m", f"{tag} (created by check_heldout_order.py)", "HEAD")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    if args.tag and args.step is None:
        print("check_heldout_order: --tag needs --step", file=sys.stderr)
        return 2
    if args.tag and args.step == REQUIREMENTS_TAG:
        print(f"check_heldout_order: {REJECT_REQUIREMENTS_TAG}", file=sys.stderr)
        return 2
    try:
        ctx = build_context(args.repo, args.step)
        findings = run_checks(ctx)
        if findings:
            for finding in findings:
                print(finding.render(), file=sys.stderr)
            return 1
        if args.tag:
            if tag_commit(args.repo, args.step) is not None:
                print(f"check_heldout_order: tag {args.step} already exists", file=sys.stderr)
                return 2
            create_tag(args.repo, args.step)
        if RESULT_TAG in ctx.refs:
            print(f"result tag commit: {ctx.refs[RESULT_TAG]}")
    except GitError as exc:
        print(f"check_heldout_order: {exc}", file=sys.stderr)
        return 2
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
