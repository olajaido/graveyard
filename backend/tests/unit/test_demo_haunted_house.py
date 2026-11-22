"""The haunted-house demo content (demo/haunted-house/).

Checks that every direct dependency comes from the development label set, never from the
held-out set, that EXPECTED.md matches the labels, and that the content stays inside the
scanner's default limits. Reads files only.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[3]
DEMO: Final = REPO / "demo" / "haunted-house"
LABELS: Final = REPO / "eval" / "labelled_packages.csv"
HELDOUT: Final = REPO / "eval" / "heldout"
# exclusions.tsv lists what the held-out draw *excluded* (the v1 set among others),
# so it is not held-out content.
HELDOUT_NOT_CONTENT: Final = {"exclusions.tsv"}

# SSM defaults of the data module (SB-CFG-1, SB-FET-4).
MAX_PURLS: Final = 2000
MAX_MANIFEST_BYTES: Final = 10_485_760
MAX_FILE_BYTES: Final = 5_242_880

Dep = tuple[str, str, str]  # ecosystem, lower-case name, version


def _norm(ecosystem: str, name: str) -> str:
    name = name.lower()
    return re.sub(r"[-_.]+", "-", name) if ecosystem == "pypi" else name


def direct_dependencies() -> list[Dep]:
    package = json.loads((DEMO / "package.json").read_text())
    deps: list[Dep] = [
        ("npm", _norm("npm", n), v)
        for section in ("dependencies", "devDependencies")
        for n, v in package.get(section, {}).items()
    ]
    for line in (DEMO / "services" / "worker" / "requirements.txt").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            name, sep, version = line.partition("==")
            assert sep == "==", f"not pinned with ==: {line}"
            deps.append(("pypi", _norm("pypi", name), version))
    return deps


def development_labels() -> dict[Dep, dict[str, str]]:
    with LABELS.open(newline="") as handle:
        return {
            (r["ecosystem"], _norm(r["ecosystem"], r["name"]), r["version"]): r
            for r in csv.DictReader(handle)
        }


def heldout_names() -> set[tuple[str, str]]:
    names: set[tuple[str, str]] = set()
    for path in sorted(HELDOUT.rglob("*")):
        if not path.is_file() or path.name in HELDOUT_NOT_CONTENT:
            continue
        if path.suffix in (".tsv", ".csv"):
            with path.open(newline="") as handle:
                reader = csv.DictReader(handle, delimiter="\t" if path.suffix == ".tsv" else ",")
                for row in reader:
                    if row.get("ecosystem") and row.get("name"):
                        names.add((row["ecosystem"], _norm(row["ecosystem"], row["name"])))
        elif path.suffix == ".json" and path.parent.parent.name == "fixtures":
            names.add((path.parent.name, _norm(path.parent.name, path.stem)))
    return names


def test_there_are_about_ten_node_and_eight_python_direct_dependencies() -> None:
    counts = Counter(e for e, _, _ in direct_dependencies())
    assert counts == {"npm": 10, "pypi": 8}


def test_every_direct_dependency_is_in_the_development_label_set_at_that_version() -> None:
    labels = development_labels()
    missing = [d for d in direct_dependencies() if d not in labels]
    assert missing == []


def test_no_direct_dependency_is_in_the_held_out_set() -> None:
    held = heldout_names()
    assert len(held) > 100  # the scan must be reading the real held-out files
    leaked = [(e, n) for e, n, _ in direct_dependencies() if (e, n) in held]
    assert leaked == []


def test_the_label_mix_is_the_requested_one() -> None:
    labels = development_labels()
    mix = Counter(labels[d]["label"] for d in direct_dependencies())
    assert mix["dead"] >= 4
    assert mix["ailing"] + mix["finished-healthy"] >= 3
    assert mix["alive"] >= 1
    assert set(mix) <= {"dead", "ailing", "finished-healthy", "alive"}
    dead_by_ecosystem = Counter(d[0] for d in direct_dependencies() if labels[d]["label"] == "dead")
    assert dead_by_ecosystem["npm"] >= 1 and dead_by_ecosystem["pypi"] >= 1


def test_expected_md_matches_the_labels() -> None:
    labels = development_labels()
    text = (DEMO / "EXPECTED.md").read_text()
    rows = re.findall(
        r"^\| (npm|pypi) \| `([^`]+)` \| ([^ |]+) \| [^|]+ \| \*\*([a-z-]+)\*\* \|", text, re.M
    )
    assert len(rows) == len(direct_dependencies())
    for ecosystem, name, version, label in rows:
        assert labels[(ecosystem, _norm(ecosystem, name), version)]["label"] == label
    assert {(e, _norm(e, n), v) for e, n, v, _ in rows} == set(direct_dependencies())
    assert "eval/labelled_packages.csv" in text


def test_the_lockfile_matches_package_json_and_has_no_install_scripts() -> None:
    lock = json.loads((DEMO / "package-lock.json").read_text())
    package = json.loads((DEMO / "package.json").read_text())
    assert lock["lockfileVersion"] == 3
    packages = lock["packages"]
    root = packages[""]
    assert root.get("dependencies") == package["dependencies"]
    assert root.get("devDependencies") == package["devDependencies"]
    for section in ("dependencies", "devDependencies"):
        for name, version in package[section].items():
            assert packages[f"node_modules/{name}"]["version"] == version
    assert [k for k, v in packages.items() if v.get("hasInstallScript")] == []


def test_the_content_stays_inside_the_scanner_default_limits() -> None:
    lock = json.loads((DEMO / "package-lock.json").read_text())
    npm = {(k.split("node_modules/")[-1], v["version"]) for k, v in lock["packages"].items() if k}
    total_purls = len(npm) + Counter(e for e, _, _ in direct_dependencies())["pypi"]
    assert total_purls <= MAX_PURLS
    manifests = [DEMO / "package-lock.json", DEMO / "services" / "worker" / "requirements.txt"]
    sizes = [os.path.getsize(p) for p in manifests]
    assert max(sizes) <= MAX_FILE_BYTES
    assert sum(sizes) <= MAX_MANIFEST_BYTES


def test_there_is_no_app_code_or_installed_tree() -> None:
    files = {p.relative_to(DEMO).as_posix() for p in DEMO.rglob("*") if p.is_file()}
    assert files == {
        "README.md",
        "EXPECTED.md",
        "package.json",
        "package-lock.json",
        "services/worker/requirements.txt",
    }
