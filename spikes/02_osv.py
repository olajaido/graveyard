#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1"]
# ///
"""
Spike Q1: OSV /v1/querybatch — Signal S7 (vulnerabilities).

Queries OSV for each package at its latest version (resolved via deps.dev).
Reports how many advisories affect each version and whether fix info is present.
"""
from __future__ import annotations

import json
import sys

import httpx

DEPSDEV = "https://api.deps.dev/v3"
OSV = "https://api.osv.dev/v1"

NPM = ["request", "node-uuid", "moment", "express", "left-pad", "uuid"]
PYPI = ["pycrypto", "nose", "requests", "pycryptodome", "six"]


def get_latest_version(client: httpx.Client, system: str, name: str) -> str | None:
    r = client.get(f"{DEPSDEV}/systems/{system}/packages/{name}")
    if r.status_code != 200:
        return None
    for v in r.json().get("versions", []):
        if v.get("isDefault"):
            return v["versionKey"]["version"]
    return None


def query_osv_batch(client: httpx.Client, queries: list[dict]) -> list:
    r = client.post(f"{OSV}/querybatch", json={"queries": queries})
    if r.status_code != 200:
        return [{}] * len(queries)
    return r.json().get("results", [])


def get_vuln_details(client: httpx.Client, vuln_id: str) -> dict:
    r = client.get(f"{OSV}/vulns/{vuln_id}")
    if r.status_code != 200:
        return {}
    return r.json()


def main() -> None:
    queries = []
    pkg_labels: list[str] = []

    with httpx.Client(timeout=30) as client:
        for name in NPM:
            ver = get_latest_version(client, "npm", name)
            if ver:
                queries.append({"package": {"name": name, "ecosystem": "npm"}, "version": ver})
                pkg_labels.append(f"npm:{name}@{ver}")
            else:
                pkg_labels.append(f"npm:{name}@?")
        for name in PYPI:
            ver = get_latest_version(client, "pypi", name)
            if ver:
                queries.append({"package": {"name": name, "ecosystem": "PyPI"}, "version": ver})
                pkg_labels.append(f"pypi:{name}@{ver}")
            else:
                pkg_labels.append(f"pypi:{name}@?")

        print("Querying OSV batch...", file=sys.stderr)
        results = query_osv_batch(client, queries)

        output = []
        for label, res in zip(pkg_labels, results):
            vulns = res.get("vulns", [])
            vuln_ids = [v.get("id", "?") for v in vulns]

            # Fetch details for first 3 vulns to check fix availability
            fix_info = []
            for vid in vuln_ids[:3]:
                details = get_vuln_details(client, vid)
                # Check if any affected entry has a fixed version
                has_fix = False
                for aff in details.get("affected", []):
                    for rng in aff.get("ranges", []):
                        for ev in rng.get("events", []):
                            if "fixed" in ev:
                                has_fix = True
                                break
                fix_info.append({"id": vid, "has_fix": has_fix})

            output.append({
                "package": label,
                "S7_vuln_count": len(vulns),
                "vuln_ids": vuln_ids[:5],
                "sample_fix_info": fix_info,
                "obtainable": True if res else False,
            })

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
