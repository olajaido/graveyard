"""Contract test against the real Syft 1.56.0 (T13.5; CLI-TEST-13, CLI-TEST-14).

Marked ``syft``. It runs the real binary through ``collect_inputs`` on the anchors-project,
so it covers ``syft.py`` (version check, the fixed environment), discovery, the lockfile
scopes and ``augment.py`` together, and asserts what the stub-based tests assume: nine
packages after augmentation, with the design §9.2 ``path_infos``.

Skipped, with a reason, unless a ``syft`` binary that reports exactly ``1.56.0`` is found on
``PATH`` or at ``~/.local/bin/syft``. Syft only reads the fixture files; there is no network.
Run everything else with ``pytest -m "not syft"``.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from cli.args import parse_args
from cli.pipeline import collect_inputs
from cli.syft import SYFT_VERSION
from cli.tests.support import make_env
from core.graph import build_graph

pytestmark = pytest.mark.syft

PROJECT = Path(__file__).resolve().parent / "fixtures" / "anchors-project"

# design §9.2: package key -> [(runtime, direct)]
EXPECTED = {
    "pypi/pycrypto@2.6.1": [(True, True)],
    "npm/left-pad@1.3.0": [(True, True)],
    "npm/request@2.88.2": [(False, True)],
    "npm/node-uuid@1.4.8": [(True, False)],
    "pypi/nose@1.3.7": [(False, True)],
    "pypi/six@1.17.0": [(True, True)],
    "npm/uuid@3.4.0": [(False, False)],
    "npm/moment@2.29.1": [(True, True)],
    "npm/express@4.17.1": [(True, True)],
}


def _find_syft() -> tuple[str | None, str]:
    """The first ``syft`` that reports exactly the pinned version, or why none was found."""
    candidates = [shutil.which("syft"), str(Path.home() / ".local" / "bin" / "syft")]
    seen: list[str] = []
    for candidate in dict.fromkeys(c for c in candidates if c):
        if not Path(candidate).is_file():
            continue
        try:
            proc = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                env={"SYFT_CHECK_FOR_APP_UPDATE": "false", "PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        line = proc.stdout.strip()
        if line == f"syft {SYFT_VERSION}":
            return candidate, line
        seen.append(f"{candidate}: {line or 'no output'}")
    detail = "; ".join(seen) if seen else "no syft binary on PATH or in ~/.local/bin"
    return None, f"needs a syft binary reporting exactly {SYFT_VERSION} ({detail})"


SYFT_BINARY, SKIP_REASON = _find_syft()

requires_syft = pytest.mark.skipif(SYFT_BINARY is None, reason=SKIP_REASON)


@requires_syft
def test_real_syft_gives_nine_packages_after_augmentation() -> None:
    opts = parse_args(
        ["autopsy", str(PROJECT), "--syft", str(SYFT_BINARY)], today=date(2026, 11, 11)
    )
    inputs = collect_inputs(opts, make_env())
    assert inputs.mode == "syft"
    assert inputs.syft_version == SYFT_VERSION
    assert [s.path for s in inputs.services] == ["api", "web"]
    assert inputs.direct_edges_added == 2  # request (web) and nose (api): the real Syft omits both
    assert inputs.cli_warnings == ()

    graph = build_graph(inputs.services)
    assert graph.warnings == ()
    assert sorted(n.key for n in graph.nodes) == sorted(EXPECTED)
    for key, expected in EXPECTED.items():
        node = graph.node(key)
        assert node is not None, key
        assert [(p.runtime, p.direct) for p in node.path_infos] == expected, key
        assert node.services_affected == 1, key


@requires_syft
def test_real_syft_includes_the_dev_packages_only_because_of_the_variable() -> None:
    """The reason for CLI-DEV-1, checked against the binary itself (no CLI code involved)."""
    web = PROJECT / "web"

    def libraries(env_extra: dict[str, str]) -> set[str]:
        proc = subprocess.run(
            [str(SYFT_BINARY), f"dir:{web}", "-q", "-o", "cyclonedx-json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
            env={"PATH": "/usr/bin:/bin", "SYFT_CHECK_FOR_APP_UPDATE": "false", **env_extra},
        )
        import json

        document = json.loads(proc.stdout)
        return {c["name"] for c in document["components"] if c["type"] == "library"}

    without = libraries({})
    with_dev = libraries({"SYFT_JAVASCRIPT_INCLUDE_DEV_DEPENDENCIES": "true"})
    assert {"request", "uuid"}.isdisjoint(without)
    assert {"request", "uuid"} <= with_dev


def test_the_skip_reason_names_the_pinned_version() -> None:
    """Runs everywhere: if the binary is missing, the reason says what is needed."""
    if SYFT_BINARY is None:
        assert SYFT_VERSION in SKIP_REASON
    else:
        assert Path(SYFT_BINARY).is_file()
