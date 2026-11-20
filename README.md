# Graveyard

Dependabot upgrades what's alive. Graveyard deals with what's dead.

Graveyard checks whether npm and PyPI packages are abandoned, deprecated or have an unfixable vulnerability.

## Kiro Power

The `powers/graveyard` folder is a Kiro Power in the Agent Plugins format. It adds:

- an MCP server, `graveyard`, with two read-only tools: `autopsy_package` and `autopsy_project`;
- skills, including `install-blocker-hook`, which carries a hook template that blocks an install command naming a package Graveyard can show is Dead or Cursed.

To install it:

```sh
git clone https://github.com/olajaido/graveyard.git
```

In Kiro, open the Powers panel, choose Add Custom Power, then *Import power from a folder* and select `powers/graveyard` in the clone.

The hook is not installed automatically: ask the agent to set it up through the `install-blocker-hook` skill. The hook fails open, so a failed or incomplete check allows the command.

See [`powers/graveyard/README.md`](powers/graveyard/README.md) for the full install steps, the dry-run check, exit codes and limits.

## Production hardening

Graveyard currently shares an AWS account with other projects. The INF-SHARED controls (name prefixes, `Project` tag conditions, a tag-filtered budget) reduce the blast radius but do not replace account separation. Before real production use, move Graveyard into its own account (or organisation unit) and tighten the roles accordingly.

## Third-party components

The held-out evaluation draws candidates from two third-party lists, pinned in `eval/heldout/snapshot/pins.json`. Only package names and download counts are used.

- **npm-high-impact** by wooorm, version 1.13.0. Licence: MIT (the `license` field of the registry record for 1.13.0).
- **top-pypi-packages** by Hugo van Kemenade et al., [hugovk/top-pypi-packages](https://github.com/hugovk/top-pypi-packages), pinned at commit `29c0d4c38c28c0e6b99e73fa09cb91a2323ca51b`. There is no licence file at that commit (the GitHub licence API returns Not Found). The project's archived releases on Zenodo are published under CC BY 4.0: [hugovk/top-pypi-packages: Release 2026.07](https://zenodo.org/records/21096183), Hugo van Kemenade et al.
