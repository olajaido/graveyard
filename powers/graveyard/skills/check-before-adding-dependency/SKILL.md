---
name: check-before-adding-dependency
description: Check whether an npm or PyPI package is abandoned, deprecated or has an unfixable vulnerability. Use before adding or installing a dependency with npm, pnpm, yarn, pip, uv or poetry, when choosing a library, or when an install is blocked by the dead-install hook.
---

# Check before adding a dependency

Graveyard autopsies a package and says whether it is alive or dead. Use it before a new dependency goes into the project, not after.

## When to consult it

- Before you run or propose `npm install`, `npm add`, `pnpm add`, `yarn add`, `pip install`, `uv add` or `poetry add` for a package.
- Before you pick a library from memory, or because another tool or model suggested it. Training data goes stale; a package you remember as popular may have been abandoned since.

Skip it for installs that add nothing new, such as `npm ci` or restoring from a lock file.

## How to check

1. Work out the version you would install. For an unpinned add, that is the latest published version.
2. Call the `autopsy_package` tool with a versioned purl: `pkg:npm/<name>@<version>`, `pkg:npm/%40<scope>/<name>@<version>` for a scoped package, or `pkg:pypi/<name>@<version>`.
3. Read the verdict (see the `reading-a-verdict` skill). Prefer packages that are Alive. Resting is fine.
4. If the verdict is Dead or Cursed, tell the user before installing anything, and suggest a maintained alternative if you know of one.

For a whole project, call `autopsy_project` with a path to a manifest, lock file or SBOM.

## If the dead-install hook blocks an install

The hook found a package it can show is Dead or Cursed.

- Stop. Tell the user which package was blocked and quote the reason the hook gave.
- You may offer maintained alternatives you know of. Say plainly that Graveyard has not verified them, then check each one with `autopsy_package` before recommending it.
- Do not work around the block. Do not retry with another package manager, add a flag, edit the manifest by hand, or split the command to hide the package.
- Ask the user how to proceed. The decision is theirs.

## If the check could not run or is partial

If the tool failed, timed out, or a note says "range not checked" or a package is unverified, say so. An install that was not checked is not an endorsement, and a missing warning is not a clean bill of health.
