#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1"]
# ///
"""
Spike Q1+Q2: npm registry — S1/S1b (deprecation on latest vs older) and S2 (release dates).

For each npm package fetches the full registry document and reports:
  - Is `deprecated` set on the LATEST version (dist-tags.latest)?
  - Is `deprecated` set on any older version?
  - Release dates for staleness (S2)
"""
from __future__ import annotations

import json
import sys

import httpx

REGISTRY = "https://registry.npmjs.org"
PACKAGES = ["request", "node-uuid", "moment", "express", "left-pad", "uuid"]


def main() -> None:
    output = []
    with httpx.Client(timeout=30) as client:
        for name in PACKAGES:
            r = client.get(f"{REGISTRY}/{name}")
            if r.status_code != 200:
                output.append({"name": name, "error": f"HTTP {r.status_code}"})
                print(f"  done: {name} (error)", file=sys.stderr)
                continue

            data = r.json()
            versions = data.get("versions", {})
            dist_tags = data.get("dist-tags", {})
            latest = dist_tags.get("latest")
            time = data.get("time", {})

            latest_deprecated = versions.get(latest, {}).get("deprecated")
            latest_publish_time = time.get(latest)

            # Count deprecated versions
            deprecated_versions = []
            for ver, info in versions.items():
                if info.get("deprecated"):
                    deprecated_versions.append({
                        "version": ver,
                        "reason": info["deprecated"][:80],
                    })

            older_deprecated = [v for v in deprecated_versions if v["version"] != latest]

            # Verdict for S1 vs S1b
            if latest_deprecated:
                verdict = "S1 (deprecated on latest = declared death)"
            elif older_deprecated:
                verdict = "S1b (older versions deprecated, latest is not = upgrade advised)"
            else:
                verdict = "neither (no deprecation)"

            output.append({
                "name": name,
                "latest_version": latest,
                "latest_deprecated": latest_deprecated,
                "latest_deprecated_reason": latest_deprecated[:100] if latest_deprecated else None,
                "latest_publish_time": latest_publish_time,
                "S2_release_date_source": "npm registry time[latest]",
                "total_versions": len(versions),
                "deprecated_count": len(deprecated_versions),
                "older_deprecated_count": len(older_deprecated),
                "older_deprecated_examples": older_deprecated[:3],
                "verdict": verdict,
            })
            print(f"  done: {name} -> {verdict}", file=sys.stderr)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
