#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1"]
# ///
"""
Spike Q1+Q3: PyPI JSON API — S1 (declared death) and S2 (release dates).

For each PyPI package fetches the JSON document and reports:
  - Does the API expose a project status field (archived/deprecated, PEP 792)?
  - Is the "Development Status :: 7 - Inactive" classifier present?
  - What Development Status classifier IS present?
  - Latest version and release date for S2.
"""
from __future__ import annotations

import json
import sys

import httpx

PYPI = "https://pypi.org/pypi"
PACKAGES = ["pycrypto", "nose", "requests", "pycryptodome", "six"]


def main() -> None:
    output = []
    with httpx.Client(timeout=30) as client:
        for name in PACKAGES:
            r = client.get(f"{PYPI}/{name}/json")
            if r.status_code != 200:
                output.append({"name": name, "error": f"HTTP {r.status_code}"})
                print(f"  done: {name} (error)", file=sys.stderr)
                continue

            data = r.json()
            info = data.get("info", {})

            # Check all info keys for any status-like field
            all_keys = list(info.keys())
            status_keys = [k for k in all_keys if any(w in k.lower() for w in ("status", "archiv", "deprecat"))]

            # Check classifiers for Development Status
            classifiers = info.get("classifiers", [])
            dev_status = [c for c in classifiers if "Development Status" in c]
            inactive_classifier = [c for c in classifiers if "7 - Inactive" in c]

            # Latest version and release date
            latest = info.get("version")
            releases = data.get("releases", {})
            latest_release_info = releases.get(latest, [])
            latest_upload_time = None
            if latest_release_info:
                latest_upload_time = latest_release_info[0].get("upload_time_iso_8601")

            # Check project URLs for archived/deprecated hints
            project_urls = info.get("project_urls", {}) or {}
            all_urls = list(project_urls.values())

            # Check yanked
            yanked = info.get("yanked", False)
            yanked_reason = info.get("yanked_reason")

            # Verdict for S1
            if inactive_classifier:
                s1_verdict = "S1 via classifier 'Development Status :: 7 - Inactive'"
            elif status_keys:
                s1_verdict = f"S1 via status field(s): {status_keys}"
            else:
                s1_verdict = "NOT AVAILABLE (no PEP 792 status, no Inactive classifier)"

            output.append({
                "name": name,
                "latest_version": latest,
                "S1_status_keys_found": status_keys,
                "S1_all_info_keys": all_keys,
                "S1_classifiers_dev_status": dev_status,
                "S1_inactive_classifier": bool(inactive_classifier),
                "S1_verdict": s1_verdict,
                "S2_latest_upload_time": latest_upload_time,
                "S2_source": "PyPI releases[latest].upload_time",
                "yanked": yanked,
                "yanked_reason": yanked_reason,
                "project_urls": all_urls[:5],
            })
            print(f"  done: {name} -> {s1_verdict}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
