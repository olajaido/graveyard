#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1"]
# ///
"""
Spike Q1+Q4: deps.dev v3 signal coverage and Scorecard.

For each package calls:
  GET /v3/systems/{sys}/packages/{name}            -> versions, isDeprecated per version (S1, S1b, S2)
  GET /v3/systems/{sys}/packages/{name}/versions/{v} -> publishedAt, links, advisoryKeys (S2, S7-partial)
  GET /v3/projects/{id}                              -> scorecard Maintained + overall (S4, S8), openIssues (S6-partial)

Reports which of S1-S9 are obtainable from deps.dev per package.
"""
from __future__ import annotations

import json
import sys
import urllib.parse

import httpx

BASE = "https://api.deps.dev/v3"

NPM = ["request", "node-uuid", "moment", "express", "left-pad", "uuid"]
PYPI = ["pycrypto", "nose", "requests", "pycryptodome", "six"]

# Signal descriptions (from PRD §7.1)
SIG_DESC = {
    "S1": "Declared death (npm deprecated on latest / archived / PyPI status)",
    "S1b": "Version deprecated (resolved version deprecated, latest is not)",
    "S2": "Release staleness (months since latest release)",
    "S3": "Commit staleness (months since last push)",
    "S4": "Maintenance activity (Scorecard Maintained 0-10)",
    "S5": "Bus factor (distinct committers in 12 mo)",
    "S6": "Issue neglect (open/closed ratio)",
    "S7": "Vulnerabilities (OSV advisories)",
    "S8": "Scorecard overall",
    "S9": "Popularity / dependents count",
}


def get(client: httpx.Client, path: str) -> dict | None:
    r = client.get(f"{BASE}{path}")
    if r.status_code != 200:
        return None
    return r.json()


def extract_project_id(ver: dict) -> str | None:
    """Extract a deps.dev project ID from a version's SOURCE_REPO link."""
    for link in ver.get("links", []):
        if link.get("label") != "SOURCE_REPO":
            continue
        url = link.get("url", "").replace("git+", "")
        # Handle github:owner/repo shorthand (e.g. "github:moment/moment")
        if url.startswith("github:"):
            path = url[len("github:"):]
            if path.endswith(".git"):
                path = path[:-4]
            path = path.rstrip("/")
            return f"github.com/{path}"
        # Handle full URLs
        for host in ("github.com/", "gitlab.com/", "bitbucket.org/"):
            if host in url:
                path = url.split(host, 1)[1]
                if path.endswith(".git"):
                    path = path[:-4]
                path = path.rstrip("/")
                return f"{host}{path}"
    return None


def analyse(client: httpx.Client, system: str, name: str) -> dict:
    key = f"{system}:{name}"
    pkg = get(client, f"/systems/{system}/packages/{name}")
    if not pkg:
        return {"key": key, "error": "package not found"}

    versions = pkg.get("versions", [])
    default = next((v for v in versions if v.get("isDefault")), None)
    if not default:
        return {"key": key, "error": "no default version"}

    latest = default["versionKey"]["version"]

    ver = get(client, f"/systems/{system}/packages/{name}/versions/{latest}")

    project_id = extract_project_id(ver) if ver else None
    project = None
    if project_id:
        encoded = urllib.parse.quote(project_id, safe="")
        project = get(client, f"/projects/{encoded}")

    sigs: dict[str, str] = {}

    # S1: deprecated on latest
    sigs["S1"] = f"deprec={'YES' if default.get('isDeprecated') else 'no'}"
    if default.get("isDeprecated"):
        sigs["S1"] += f" reason={default.get('deprecatedReason', '')[:60]!r}"
    sigs["S1_source"] = "deps.dev version.isDeprecated"

    # S1b: older versions deprecated
    older_dep = [v for v in versions if v.get("isDeprecated") and not v.get("isDefault")]
    sigs["S1b"] = f"older_deprecated={len(older_dep)}" + (
        f" example={older_dep[0].get('deprecatedReason', '')[:50]!r}" if older_dep else ""
    )
    sigs["S1b_source"] = "deps.dev version.isDeprecated (non-default)"

    # S2: release staleness
    if ver and ver.get("publishedAt"):
        sigs["S2"] = f"publishedAt={ver['publishedAt']}"
        sigs["S2_source"] = "deps.dev version.publishedAt"
    else:
        sigs["S2"] = "missing"
        sigs["S2_source"] = "deps.dev version.publishedAt"

    # S3: commit staleness — NOT available from deps.dev
    sigs["S3"] = "NOT AVAILABLE (needs GitHub GraphQL)"
    sigs["S3_source"] = "-"

    # S4: Scorecard Maintained check
    if project:
        for check in project.get("scorecard", {}).get("checks", []):
            if check.get("name") == "Maintained":
                sigs["S4"] = f"score={check.get('score')} reason={check.get('reason', '')[:50]!r}"
                break
        sigs["S4_source"] = "deps.dev project.scorecard.checks[Maintained]"
    else:
        sigs["S4"] = "missing (no project/scorecard)"
        sigs["S4_source"] = "deps.dev project.scorecard"

    # S5: bus factor — NOT available from deps.dev
    sigs["S5"] = "NOT AVAILABLE (needs GitHub stats / ecosyste.ms)"
    sigs["S5_source"] = "-"

    # S6: issue neglect — only openIssuesCount from deps.dev (partial)
    if project and project.get("openIssuesCount") is not None:
        sigs["S6"] = f"openIssues={project['openIssuesCount']} (partial — no closed count or response time)"
    else:
        sigs["S6"] = "missing"
    sigs["S6_source"] = "deps.dev project.openIssuesCount (PARTIAL only)"

    # S7: advisories from version (partial; OSV gives better data)
    if ver:
        adv = ver.get("advisoryKeys", [])
        sigs["S7"] = f"advisoryKeys={len(adv)} (partial; OSV gives full details)"
    else:
        sigs["S7"] = "missing"
    sigs["S7_source"] = "deps.dev version.advisoryKeys (use OSV instead)"

    # S8: Scorecard overall
    if project and project.get("scorecard", {}).get("overallScore") is not None:
        sigs["S8"] = f"overall={project['scorecard']['overallScore']}"
    else:
        sigs["S8"] = "missing"
    sigs["S8_source"] = "deps.dev project.scorecard.overallScore"

    # S9: dependents — NOT available from deps.dev v3
    sigs["S9"] = "NOT AVAILABLE (deps.dev v3 has no dependents endpoint)"
    sigs["S9_source"] = "-"
    if project:
        sigs["S9_extra"] = f"stars={project.get('starsCount')} forks={project.get('forksCount')} (popularity proxies, not dependents)"

    # Scorecard detail for Q4
    scorecard_detail = {}
    if project:
        sc = project.get("scorecard", {})
        scorecard_detail = {
            "overallScore": sc.get("overallScore"),
            "checks": {
                c["name"]: c.get("score")
                for c in sc.get("checks", [])
            },
        }

    return {
        "key": key,
        "latest_version": latest,
        "project_id": project_id,
        "has_scorecard": project is not None,
        "signals": sigs,
        "scorecard_detail": scorecard_detail,
    }


def main() -> None:
    results: list[dict] = []
    with httpx.Client(timeout=30) as client:
        for name in NPM:
            results.append(analyse(client, "npm", name))
            print(f"  done: npm:{name}", file=sys.stderr)
        for name in PYPI:
            results.append(analyse(client, "pypi", name))
            print(f"  done: pypi:{name}", file=sys.stderr)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
