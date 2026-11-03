#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""
Spike Q5: Syft CycloneDX output — does it include dependency relationships?

Steps:
  1. Generate npm lockfile (npm install --package-lock-only --ignore-scripts)
  2. Generate Python lockfile (uv lock)
  3. Run Syft v1.56.0 on both fixtures with -o cyclonedx-json
  4. Parse the CycloneDX JSON and report whether `dependencies` array is present
     and whether it distinguishes direct vs transitive relationships.

No external Python deps — uses stdlib subprocess + json.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SYFT = os.path.expanduser("~/.local/bin/syft")
NPM_FIXTURE = Path(__file__).parent / "fixtures" / "npm"
PY_FIXTURE = Path(__file__).parent / "fixtures" / "py"


def run(cmd: list[str], cwd: Path, label: str) -> subprocess.CompletedProcess:
    print(f"  [{label}] $ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def run_syft(target: Path) -> dict:
    """Run Syft on a directory and return parsed CycloneDX JSON."""
    result = subprocess.run(
        [SYFT, f"dir:{target}", "-o", "cyclonedx-json"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return {"error": result.stderr[:500], "stdout": result.stdout[:500]}

    # Syft prints JSON to stdout; there may be log lines before it
    lines = result.stdout.strip().splitlines()
    json_start = 0
    for i, line in enumerate(lines):
        if line.startswith("{"):
            json_start = i
            break
    json_str = "\n".join(lines[json_start:])
    return json.loads(json_str)


def analyse_cyclonedx(bom: dict, label: str) -> dict:
    """Check whether the CycloneDX BOM has meaningful dependency relationships."""
    if "error" in bom:
        return {"label": label, "error": bom["error"]}

    components = bom.get("components", [])
    dependencies = bom.get("dependencies", [])

    # Find root component (metadata.component)
    meta = bom.get("metadata", {}).get("component", {})
    root_ref = meta.get("bom-ref") if meta else None

    # Find the root's dependencies (direct deps)
    root_dep_entry = None
    if root_ref:
        root_dep_entry = next((d for d in dependencies if d.get("ref") == root_ref), None)

    direct_refs = set()
    if root_dep_entry:
        direct_refs = set(root_dep_entry.get("dependsOn", []))

    # Classify components as direct or transitive
    direct = []
    transitive = []
    for comp in components:
        ref = comp.get("bom-ref", "")
        if ref in direct_refs:
            direct.append(ref)
        elif ref != root_ref:
            transitive.append(ref)

    # Count how many dependency entries have non-empty dependsOn
    with_deps = sum(1 for d in dependencies if d.get("dependsOn"))

    return {
        "label": label,
        "bom_format": bom.get("bomFormat"),
        "spec_version": bom.get("specVersion"),
        "num_components": len(components),
        "num_dependencies": len(dependencies),
        "dependencies_with_dependsOn": with_deps,
        "has_direct_vs_transitive": len(direct) > 0 or len(transitive) > 0,
        "direct_count": len(direct),
        "transitive_count": len(transitive),
        "root_ref": root_ref,
        "root_dependsOn_count": len(direct_refs),
        "sample_components": [c.get("bom-ref") for c in components[:5]],
        "sample_direct": sorted(direct)[:5],
        "sample_transitive": sorted(transitive)[:5],
        "verdict": "YES — relationships present" if with_deps > 0 else "NO — flat list only",
    }


def main() -> None:
    print("Step 1: Generate npm lockfile", file=sys.stderr)
    r = run(["npm", "install", "--package-lock-only", "--ignore-scripts"],
            NPM_FIXTURE, "npm lock")
    if r.returncode != 0:
        print(f"  npm lock FAILED: {r.stderr[:200]}", file=sys.stderr)
    else:
        print("  npm lockfile generated", file=sys.stderr)

    print("Step 2: Generate Python lockfile", file=sys.stderr)
    r = run(["uv", "lock"], PY_FIXTURE, "uv lock")
    if r.returncode != 0:
        print(f"  uv lock FAILED: {r.stderr[:200]}", file=sys.stderr)
    else:
        print("  uv.lock generated", file=sys.stderr)

    print("Step 3: Run Syft on npm fixture", file=sys.stderr)
    npm_bom = run_syft(NPM_FIXTURE)
    print("Step 4: Run Syft on Python fixture", file=sys.stderr)
    py_bom = run_syft(PY_FIXTURE)

    print("\nStep 5: Analyse CycloneDX output", file=sys.stderr)
    npm_analysis = analyse_cyclonedx(npm_bom, "npm (express, request, moment)")
    py_analysis = analyse_cyclonedx(py_bom, "pypi (requests, six, nose)")

    # Also save raw BOMs for inspection
    out_dir = Path(__file__).parent
    if "error" not in npm_bom:
        (out_dir / "npm-sbom.cdx.json").write_text(json.dumps(npm_bom, indent=2))
    if "error" not in py_bom:
        (out_dir / "py-sbom.cdx.json").write_text(json.dumps(py_bom, indent=2))

    print(json.dumps([npm_analysis, py_analysis], indent=2))


if __name__ == "__main__":
    main()
